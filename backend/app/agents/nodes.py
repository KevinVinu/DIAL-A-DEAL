"""
LangGraph nodes for the Fortivex sales agent.

Each node has one responsibility and returns a partial state update. Action nodes never talk to the customer
directly — they set a DIRECTIVE (what must be communicated, and which facts are confirmed) that the single
`generate_response` node turns into short spoken language. That is what guarantees the agent can only claim a
booking / email after the real API call succeeded.
"""
import asyncio
import hashlib
import json
import re
from dataclasses import asdict
from typing import Any, Dict, List

from app.agents import prompts
from app.agents.routing import (KNOWLEDGE_INTENTS, decide_next_action, has_name, missing_meeting_fields)
from app.agents.state import new_meeting, slot_key
from app.config import settings
from app.rag import retriever
from app.services.llm.base import LLMError
from app.services.llm.groq_llm import GroqLLMService
from app.tools import calendar_tools as cal
from app.tools import gmail_tools, lead_tools
from app.tools.calendar_tools import CalendarError
from app.tools.customer_tools import snapshot_customer
from app.tools.gmail_tools import EmailError, is_valid_email
from app.tools.google_auth import GoogleAuthError
from app.utils.logger import logger

_llm = None
_policy_cache: List[str] | None = None


def get_llm():
    """Single place to swap the conversational LLM provider (must implement BaseLLMService.complete)."""
    global _llm
    if _llm is None:
        _llm = GroqLLMService()
    return _llm


def set_llm(llm):  # used by tests
    global _llm
    _llm = llm


SAFE_ERROR_LINE = {
    "en-IN": "Sorry, I didn't quite catch that. Could you please say that again?",
    "hi-IN": "माफ़ कीजिए, मैं ठीक से सुन नहीं पाया। क्या आप दोबारा बोल सकते हैं?",
    "ta-IN": "மன்னிக்கவும், எனக்கு சரியாகக் கேட்கவில்லை. தயவுசெய்து மீண்டும் சொல்ல முடியுமா?",
    "te-IN": "క్షమించండి, నాకు సరిగా వినిపించలేదు. దయచేసి మళ్ళీ చెప్పగలరా?",
    "ml-IN": "ക്ഷമിക്കണം, എനിക്ക് വ്യക്തമായി കേൾക്കാനായില്ല. ദയവായി ഒന്നുകൂടി പറയാമോ?",
}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


# ------------------------------------------------------------------------------------------------ helpers
def _spoken_email(email: str) -> str:
    return (email or "").replace("@", " at ").replace(".", " dot ")


def _norm_time(t) -> str | None:
    m = TIME_RE.match(str(t or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return f"{h:02d}:{mi:02d}" if 0 <= h < 24 and 0 <= mi < 60 else None


def _norm_date(d) -> str | None:
    try:
        return cal.datetime.strptime(str(d), "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return None


def _norm_phone(p) -> str | None:
    digits = re.sub(r"\D", "", str(p or ""))
    return ("+" + digits if str(p).strip().startswith("+") else digits) if 8 <= len(digits) <= 15 else None


def _slot_dt(m: Dict[str, Any]):
    return cal.parse_slot(m["date"], m["time"])


def _meeting_ctx(m: Dict[str, Any]) -> str:
    st = m.get("stage")
    if st == "suggested":
        return "the agent just offered to schedule a meeting and is waiting for a yes/no"
    if st == "collecting":
        alts = "; ".join(f"{i + 1}) {a['label']}" for i, a in enumerate(m.get("alternatives", [])))
        return (f"collecting meeting details (date={m.get('date')}, time={m.get('time')}, "
                f"email asked separately). Alternative slots offered: {alts or 'none'}")
    if st == "proposed":
        return f"the agent proposed {m.get('date')} {m.get('time')} and waits for the customer to confirm (yes/no)"
    if st == "booked":
        return f"a meeting is already booked for {m.get('date')} {m.get('time')}"
    return "no meeting is being scheduled"


def _qualification(c: Dict[str, Any], intent: str, stage: str, customer_turns: int):
    s = 0
    s += 25 if c.get("requirement") else 0
    s += 15 if c.get("product_interest") else 0
    s += {"high": 20, "medium": 12, "low": 3}.get((c.get("purchase_intent") or "").lower(), 0)
    s += 8 if c.get("company") else 0
    s += 7 if c.get("industry") else 0
    s += 5 if has_name(c) else 0
    s += 10 if is_valid_email(c.get("email")) else 0
    s += 5 if c.get("phone") else 0
    s += 5 if c.get("challenges") else 0
    s += 5 if c.get("budget") else 0
    s = min(s, 100)
    status = "New"
    if c.get("requirement") or c.get("product_interest"):
        status = "Engaged"
    interested = ((c.get("purchase_intent") or "").lower() in ("high", "medium")
                  or intent in ("purchase_interest", "agree_meeting", "request_callback")
                  or stage in ("collecting", "proposed", "booked"))
    if status == "Engaged" and interested and s >= 40 and customer_turns >= 2:
        status = "Qualified"
    return s, status


def _lead_summary(state: Dict[str, Any]) -> str:
    c, m = state.get("customer", {}), state.get("meeting", {})
    who = c.get("name") if has_name(c) else "The caller"
    bits = [who + (f" ({', '.join(x for x in (c.get('company'), c.get('industry')) if x)})"
                   if (c.get("company") or c.get("industry")) else "")]
    s = bits[0]
    if c.get("requirement"):
        s += f" is looking for: {c['requirement']}."
    else:
        s += " has not stated a requirement yet."
    if c.get("product_interest"):
        s += f" Product interest: {c['product_interest']}."
    if c.get("challenges"):
        s += f" Challenges: {c['challenges']}."
    if c.get("budget"):
        s += f" Budget (customer-stated): {c['budget']}."
    if m.get("stage") == "booked":
        s += f" Meeting scheduled for {m.get('date')} {m.get('time')}."
    elif m.get("stage") in ("collecting", "proposed", "pending_followup"):
        s += " Meeting requested; scheduling in progress / awaiting team follow-up."
    elif m.get("stage") == "cancelled":
        s += " Meeting was cancelled."
    return s


def _meeting_status_for_lead(stage: str) -> str:
    return {"suggested": "Suggested", "collecting": "Pending", "proposed": "Pending", "pending_followup": "Pending",
            "booked": "Scheduled", "cancelled": "Cancelled"}.get(stage, "None")


def _extend(state, key, item):
    return list(state.get(key, [])) + [item]


async def _persist(state: Dict[str, Any], flags: Dict[str, Any]) -> Dict[str, Any]:
    """Persist customer + lead when something changed. Returns state updates (ids may change after a merge)."""
    cust, lead = state.get("customer", {}), dict(state.get("lead", {}))
    lead["meeting_status"] = _meeting_status_for_lead(state.get("meeting", {}).get("stage", "none"))
    lead["summary"] = _lead_summary(state)
    digest = hashlib.md5(json.dumps([cust, lead], sort_keys=True, default=str).encode()).hexdigest()
    if flags.get("last_persist_hash") == digest:
        return {"lead": lead}
    try:
        ids = await asyncio.to_thread(lead_tools.persist_lead, customer_id=state["customer_id"],
                                      lead_id=state["lead_id"], customer=cust, lead=lead)
        flags["last_persist_hash"] = digest
        return {"lead": lead, "customer_id": ids["customer_id"], "lead_id": ids["lead_id"], "flags": flags}
    except Exception as e:
        logger.error(f"[Agent] Lead persistence failed: {e}")
        return {"lead": lead, "errors": _extend(state, "errors", f"lead_persist: {e}")}


def _clean_speech(text: str) -> str:
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    t = re.sub(r"[*_`#>]+", "", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    t = re.sub(r"\s+", " ", t).strip().strip('"')
    if len(t) > 520:
        cut = t[:520]
        last = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        t = cut[: last + 1] if last > 150 else cut
    return t


_BOOKING_CLAIM = re.compile(
    r"(your\s+meeting|it)\s+(is|has been)\s+(booked|scheduled|confirmed)\b|(have|has) been (booked|scheduled|sent)|"
    r"(invite|invitation|confirmation email)\b.*\b(sent|on its way)|you(?:'| a)re all set\b",
    re.I)


# ------------------------------------------------------------------------------------------------ nodes
async def intake(state: Dict[str, Any]) -> Dict[str, Any]:
    """Conversation input: record the customer's utterance and reset per-turn transients."""
    text = (state.get("user_input") or "").strip()
    history = list(state.get("history", []))
    if text and not state.get("is_greeting"):
        history.append({"role": "customer", "text": text})
    return {"history": history, "analysis": {}, "intent": "", "retrieved": [], "grounded": False,
            "next_action": "", "directive": "", "response": "", "tool_log": [], "errors": []}


async def detect_intent(state: Dict[str, Any]) -> Dict[str, Any]:
    now = cal.now_local()
    last_agent = next((h["text"] for h in reversed(state["history"]) if h["role"] == "ai"), "")
    system = prompts.ANALYSIS_SYSTEM.format(
        now=now.strftime("%A, %d %B %Y, %H:%M"), tz=settings.DEFAULT_TIMEZONE,
        known=prompts.format_known(state.get("customer", {})),
        meeting_ctx=_meeting_ctx(state.get("meeting", {})),
        last_agent=last_agent[:400].replace('"', "'"), intents=json.dumps(prompts.INTENTS))
    try:
        raw = await get_llm().complete(
            [{"role": "system", "content": system}, {"role": "user", "content": state["user_input"]}],
            json_mode=True, max_tokens=700, temperature=0.1)
        analysis = json.loads(raw)
        if not isinstance(analysis, dict):
            raise ValueError("analysis is not an object")
    except (LLMError, ValueError, json.JSONDecodeError) as e:
        logger.error(f"[Agent] Intent analysis failed: {e}")
        analysis = {"intent": "smalltalk", "needs_company_knowledge": True, "extracted": {}, "meeting": {},
                    "search_query": state["user_input"]}
        return {"analysis": analysis, "intent": "smalltalk", "errors": _extend(state, "errors", f"analysis: {e}")}
    intent = analysis.get("intent")
    if intent not in prompts.INTENTS:
        intent = "unrelated"
    analysis["extracted"] = analysis.get("extracted") or {}
    analysis["meeting"] = analysis.get("meeting") or {}
    logger.info(f"[Agent] intent={intent} extracted={ {k: v for k, v in analysis['extracted'].items() if v} } "
                f"meeting={ {k: v for k, v in analysis['meeting'].items() if v} } conf={analysis.get('confirmation')}")
    return {"analysis": analysis, "intent": intent}


async def retrieve_knowledge(state: Dict[str, Any]) -> Dict[str, Any]:
    """RAG: fetch verified Fortivex records from ChromaDB for company-related questions."""
    a = state.get("analysis", {})
    if not (state.get("intent") in KNOWLEDGE_INTENTS or a.get("needs_company_knowledge")):
        return {"retrieved": [], "grounded": False}
    query = (a.get("search_query") or state.get("user_input") or "").strip()
    hint = state.get("customer", {}).get("product_interest") or ""
    try:
        docs = await asyncio.to_thread(retriever.retrieve, query, hint)
    except Exception as e:
        logger.error(f"[Agent] Retrieval failed: {e}")
        return {"retrieved": [], "grounded": False, "errors": _extend(state, "errors", f"rag: {e}")}
    return {"retrieved": [asdict(d) for d in docs], "grounded": bool(docs)}


async def load_memory(state: Dict[str, Any]) -> Dict[str, Any]:
    """Customer context / memory: fill gaps from the DB record of THIS conversation's customer only."""
    snap = await asyncio.to_thread(snapshot_customer, state.get("customer_id"))
    cust = dict(state.get("customer", {}))
    for k, v in snap.items():
        if not cust.get(k):
            cust[k] = v
    return {"customer": cust}


async def qualify(state: Dict[str, Any]) -> Dict[str, Any]:
    """Customer qualification: merge what the customer said, score the lead. Progressive — never overwrites with null."""
    ex = (state.get("analysis") or {}).get("extracted") or {}
    cust = dict(state.get("customer", {}))
    for key in ("name", "company", "industry", "requirement", "product_interest", "challenges", "budget"):
        v = ex.get(key)
        if isinstance(v, str) and v.strip():
            cust[key] = v.strip()
    if ex.get("email") and is_valid_email(str(ex["email"])):
        cust["email"] = str(ex["email"]).strip().lower()
    if _norm_phone(ex.get("phone")):
        cust["phone"] = _norm_phone(ex["phone"])
    pi = str(ex.get("purchase_intent") or "").lower()
    if pi in ("high", "medium", "low"):
        cust["purchase_intent"] = pi
    turns = sum(1 for h in state.get("history", []) if h["role"] == "customer")
    score, status = _qualification(cust, state.get("intent", ""), state.get("meeting", {}).get("stage", "none"), turns)
    lead = dict(state.get("lead", {}))
    if lead.get("status") == "Qualified" and status != "Qualified":
        status = "Qualified"  # never downgrade
    lead.update(score=score, status=status)
    return {"customer": cust, "lead": lead}


async def meeting_info(state: Dict[str, Any]) -> Dict[str, Any]:
    """Meeting information collection: extract scheduling details already mentioned and advance the stage machine."""
    a = state.get("analysis") or {}
    intent, conf = state.get("intent", ""), a.get("confirmation")
    mt = a.get("meeting") or {}
    m = dict(state.get("meeting") or new_meeting())
    flags = dict(state.get("flags", {}))
    m["slot_changed"] = False
    stage = m["stage"]

    agrees = (
        intent in ("agree_meeting", "request_callback", "confirm_slot")
        or (stage == "suggested" and conf == "yes")
        or (stage in ("none", "suggested") and bool(mt.get("date") or mt.get("time")) and intent != "cancel_meeting")
    )
    declines = intent == "decline_meeting" or (stage == "suggested" and conf == "no")

    if declines and stage in ("suggested", "collecting", "proposed", "pending_followup"):
        flags["meeting_declined"] = True
        m.update(stage="none", date=None, time=None, time_hint=None, checked_key=None, alternatives=[])
        return {"meeting": m, "flags": flags}

    if agrees and stage in ("none", "suggested", "cancelled", "pending_followup"):
        m["stage"] = "collecting"
        flags["meeting_declined"] = False
        if stage in ("cancelled", "pending_followup"):
            m.update(checked_key=None, alternatives=[])
        stage = "collecting"

    new_date, new_time = _norm_date(mt.get("date")), _norm_time(mt.get("time"))

    if intent == "change_meeting" and stage in ("booked", "proposed", "collecting", "pending_followup"):
        if stage == "booked":
            m.update(old_event_id=m.get("event_id"), old_meeting_id=m.get("meeting_id"),
                     event_id=None, meeting_id=None, link=None, email_status="not_sent")
        if not (new_date or new_time):
            m.update(date=None, time=None, time_hint=None)
        m.update(stage="collecting", checked_key=None, alternatives=[])
        stage = "collecting"

    if stage in ("collecting", "proposed"):
        idx = mt.get("choice_index")
        alts = m.get("alternatives") or []
        if isinstance(idx, int) and 1 <= idx <= len(alts):
            new_date, new_time = alts[idx - 1]["date"], alts[idx - 1]["time"]
        changed = False
        if new_date and new_date != m.get("date"):
            m["date"], changed = new_date, True
        if new_time and new_time != m.get("time"):
            m["time"], changed = new_time, True
        if mt.get("time_hint") and not m.get("time"):
            m["time_hint"] = str(mt["time_hint"])
        if isinstance(mt.get("duration_min"), int) and 10 <= mt["duration_min"] <= 240:
            if mt["duration_min"] != m.get("duration"):
                m["duration"], changed = mt["duration_min"], True
        if isinstance(mt.get("purpose"), str) and mt["purpose"].strip():
            m["purpose"] = mt["purpose"].strip()
        if changed:
            m["slot_changed"] = True
            m["alternatives"] = [] if not (isinstance(idx, int) and alts) else m["alternatives"]
            if stage == "proposed":
                m["stage"] = "collecting"
        elif stage == "proposed" and (conf == "no" or intent == "reject_slot"):
            m.update(stage="collecting", date=None, time=None, time_hint=None, checked_key=None, alternatives=[])
    return {"meeting": m, "flags": flags}


async def manage_lead(state: Dict[str, Any]) -> Dict[str, Any]:
    """Lead management: create-once / update the structured lead in the database (no duplicates)."""
    flags = dict(state.get("flags", {}))
    return await _persist(state, flags)


async def decide(state: Dict[str, Any]) -> Dict[str, Any]:
    action = decide_next_action(state)
    logger.info(f"[Agent] next_action={action} stage={state.get('meeting', {}).get('stage')} "
                f"lead={state.get('lead', {}).get('status')}/{state.get('lead', {}).get('score')}")
    return {"next_action": action}


# ------------------------------------------------------------------------------------------------ action nodes
def _next_qualification_hint(c: Dict[str, Any]) -> str:
    if not c.get("requirement"):
        return "Ask ONE open question about what they are looking for or what they want to achieve."
    if not c.get("industry") and not c.get("company"):
        return "Ask ONE question about their business (what kind of organisation they run)."
    if not c.get("challenges"):
        return "Ask ONE question about the main challenge they currently face with this."
    return ("You now understand their need. Briefly reflect it back and ask whether they want to know more "
            "about the relevant Fortivex offering or discuss it with the Fortivex team.")


def _pending_step_hint(state: Dict[str, Any]) -> str:
    m = state.get("meeting", {})
    if m.get("stage") == "proposed":
        return (f"Then gently return to the meeting: ask whether they confirm the proposed slot "
                f"({m.get('date')} {m.get('time')}).")
    if m.get("stage") in ("collecting", "suggested"):
        return "Then gently return to arranging the meeting with the Fortivex team."
    return ""


async def greet(state: Dict[str, Any]) -> Dict[str, Any]:
    c = state.get("customer", {})
    name = c.get("name") if has_name(c) else None
    d = ("The call has just connected. Greet the caller warmly" + (f" by first name ({name.split()[0]})" if name else "") +
         ", introduce yourself as Alex, the AI sales representative for Fortivex AI, and ask how you can help today. "
         "Keep it to two short sentences.")
    return {"directive": d}


async def answer_company(state: Dict[str, Any]) -> Dict[str, Any]:
    if state.get("grounded"):
        d = ("Answer the customer's question using ONLY the VERIFIED KNOWLEDGE for company/product facts, and "
             "CUSTOMER-STATED DETAILS / MEETING STATE if they are asking about their own requirements or scheduled "
             "meeting. Be concise: give the 2-3 most relevant points. If the knowledge covers only part of a company "
             "question, answer that part and say the rest is not verified and the Fortivex team can clarify. If you "
             "mention prices, say they are published website prices and the team will confirm current pricing.")
    else:
        d = (f'There is no verified knowledge for this question. Reply with this meaning in the call language: '
             f'"{prompts.FALLBACK_LINE}" Do not add any company facts.')
    tail = _pending_step_hint(state) or (_next_qualification_hint(state.get("customer", {}))
                                         if state.get("meeting", {}).get("stage") == "none" else "")
    return {"directive": f"{d} {tail}".strip()}


async def continue_conversation(state: Dict[str, Any]) -> Dict[str, Any]:
    intent, c = state.get("intent"), state.get("customer", {})
    if intent == "unrelated":
        d = ("The customer's message is unrelated to Fortivex. Politely say you can help with questions about Fortivex AI "
             "and its solutions, then steer back with one short question about their business needs.")
    elif intent == "end_call":
        pend = " Mention the Fortivex team will follow up on the meeting request." if (
            state.get("meeting", {}).get("stage") == "pending_followup") else ""
        d = "The customer wants to wrap up. Thank them warmly and say goodbye in one short sentence." + pend
    elif intent == "decline_meeting" or state.get("flags", {}).get("meeting_declined") and intent == "smalltalk":
        d = ("The customer prefers not to schedule a meeting. Respect that, say they can reach the Fortivex team any time, "
             "and ask if there is anything else you can help with.")
    elif intent == "provide_contact":
        d = ("Acknowledge the details they just shared (without reading them back). " + _next_qualification_hint(c))
    else:
        d = "Acknowledge what the customer said naturally. " + _next_qualification_hint(c)
    return {"directive": d + " " + _pending_step_hint(state)}


async def suggest_meeting(state: Dict[str, Any]) -> Dict[str, Any]:
    m = dict(state["meeting"])
    m["stage"] = "suggested"
    flags = dict(state.get("flags", {}))
    flags["meeting_suggested"] = True
    req = state.get("customer", {}).get("requirement") or "their requirements"
    d = (f"Based on what they told you ({req}), say the Fortivex team could help them explore a suitable solution and ask "
         "if they would like to schedule a quick discussion with the team. One short question; do not mention dates or "
         "times yet and do not pressure them.")
    return {"meeting": m, "flags": flags, "directive": d}


def _reason_text(reason: str, start) -> str:
    if reason == "past":
        return "that time has already passed"
    if reason == "outside_hours":
        days = ", ".join(DAY_NAMES[i] for i in settings.MEETING_WORK_DAYS)
        return (f"it is outside the team's meeting hours ({settings.MEETING_WORK_START_HOUR}:00 to "
                f"{settings.MEETING_WORK_END_HOUR}:00 India time, {days})")
    return "the team already has a commitment at that time"


async def collect_meeting_details(state: Dict[str, Any]) -> Dict[str, Any]:
    m, c = dict(state["meeting"]), state.get("customer", {})
    if m["stage"] in ("none", "suggested", "cancelled"):
        m["stage"] = "collecting"
    missing = missing_meeting_fields(state)

    # slot was checked and found unavailable -> re-offer the real alternatives
    if not missing and m.get("alternatives") and slot_key(m) == m.get("checked_key"):
        alts = "; ".join(f"option {i + 1}: {a['label']}" for i, a in enumerate(m["alternatives"]))
        return {"meeting": m, "directive": (
            f"The requested slot is not available. Offer these real free slots (India time) and ask which one suits: {alts}.")}

    known_bits = []
    if m.get("date"):
        known_bits.append(f"date {m['date']}")
    if m.get("time_hint") and not m.get("time"):
        known_bits.append(f"they prefer the {m['time_hint']}")
    already = f" They already gave: {', '.join(known_bits)}. Do not ask for that again." if known_bits else ""

    if "date" in missing and "time" in missing:
        ask = "Ask which day and what time works for them (times are in India Standard Time)."
    elif "date" in missing:
        ask = "Ask which day works for them."
    elif "time" in missing:
        ask = (f"Ask what exact time works for them" +
               (f" in the {m['time_hint']}" if m.get("time_hint") else "") + " (India Standard Time).")
    elif "email" in missing:
        ask = ("Ask for their email address so the calendar invitation and confirmation can be sent. "
               "Ask them to say it slowly and clearly.")
    elif "name" in missing:
        ask = "Ask for their name so the invitation is addressed correctly."
    elif "purpose" in missing:
        ask = "Ask what they would like to discuss in the meeting."
    else:
        ask = "Confirm the details."
    d = ("The customer agreed to a meeting with the Fortivex team. Briefly acknowledge. " + ask + already +
         " Ask for ONLY this one thing; do not ask for anything else.")
    return {"meeting": m, "directive": d}


async def check_availability(state: Dict[str, Any]) -> Dict[str, Any]:
    """Check the team's real Google Calendar; propose the slot if free, otherwise offer real alternatives."""
    m, c = dict(state["meeting"]), state.get("customer", {})
    try:
        start = _slot_dt(m)
    except (ValueError, TypeError):
        m.update(date=None, time=None, checked_key=None)
        return {"meeting": m, "directive": "The date or time was not understood. Ask them to repeat the day and exact time."}
    purpose = m.get("purpose") or c.get("requirement") or "Discussion with Fortivex AI"
    m["purpose"] = purpose
    m["meeting_id"] = await asyncio.to_thread(
        lead_tools.upsert_pending_meeting, session_id=state["session_id"], customer_id=state["customer_id"],
        lead_id=state.get("lead_id"), date=m["date"], time=m["time"], duration=m["duration"],
        purpose=purpose, timezone=m["timezone"], meeting_id=m.get("meeting_id"))
    try:
        av = await asyncio.to_thread(cal.check_availability, start, m["duration"])
    except (GoogleAuthError, CalendarError) as e:
        logger.error(f"[Agent] Calendar availability check failed: {e}")
        await asyncio.to_thread(lead_tools.mark_meeting_failed, m["meeting_id"], f"availability: {e}")
        m.update(stage="pending_followup", checked_key=slot_key(m))
        return {"meeting": m, "errors": _extend(state, "errors", f"calendar: {e}"),
                "tool_log": _extend(state, "tool_log", "calendar_availability: FAILED"),
                "directive": (
                    f"You could NOT check the team calendar (technical problem). Do not say the slot is available or booked. "
                    f"Tell them you have noted their preferred time ({cal.spoken_slot(start)}) and that the Fortivex team will "
                    f"confirm the meeting with them shortly. Then ask if there is anything else you can help with.")}

    m["checked_key"] = slot_key(m)
    if av.available:
        m.update(stage="proposed", alternatives=[])
        name = c.get("name") if has_name(c) else "the customer"
        d = (f"The slot {cal.spoken_slot(start)} (India time) for {m['duration']} minutes is FREE on the team calendar. "
             f"Read back the date and time and that the invitation will go to {_spoken_email(c.get('email', ''))}, then ask "
             f"{name} to confirm that you should book it. Do NOT say it is booked yet.")
    else:
        alts = [{"date": a.strftime("%Y-%m-%d"), "time": a.strftime("%H:%M"), "label": cal.spoken_slot(a)}
                for a in av.alternatives]
        m.update(stage="collecting", alternatives=alts)
        why = _reason_text(av.reason, start)
        if alts:
            listing = "; ".join(f"option {i + 1}: {a['label']}" for i, a in enumerate(alts))
            d = (f"The requested slot ({cal.spoken_slot(start)}) is not available because {why}. Say so briefly and offer "
                 f"these real free slots (India time): {listing}. Ask which one suits them.")
        else:
            d = (f"The requested slot is not available because {why}, and no free slot was found in the next week. "
                 f"Apologise and ask for another day.")
    return {"meeting": m, "directive": d, "tool_log": _extend(state, "tool_log", f"calendar_availability: {av.available}")}


async def create_event(state: Dict[str, Any]) -> Dict[str, Any]:
    """Create the Google Calendar event (+ Meet) after the customer confirmed the exact slot."""
    m, c = dict(state["meeting"]), state.get("customer", {})
    start = _slot_dt(m)
    purpose = m.get("purpose") or c.get("requirement") or "Discussion with Fortivex AI"

    # duplicate prevention: this meeting already has a confirmed calendar event
    if m.get("meeting_id"):
        existing = await asyncio.to_thread(lead_tools.get_meeting, m["meeting_id"])
        if existing and existing.get("calendar_event_id") and existing.get("meeting_status") == "Scheduled":
            m.update(stage="booked", event_id=existing["calendar_event_id"], link=existing.get("meeting_link"))
            return {"meeting": m, "directive": (
                f"This meeting is already confirmed for {cal.spoken_slot(start)}. Tell them it is already booked and ask "
                f"if there is anything else.")}

    m["meeting_id"] = await asyncio.to_thread(
        lead_tools.upsert_pending_meeting, session_id=state["session_id"], customer_id=state["customer_id"],
        lead_id=state.get("lead_id"), date=m["date"], time=m["time"], duration=m["duration"], purpose=purpose,
        timezone=m["timezone"], meeting_id=m.get("meeting_id"))
    try:
        av = await asyncio.to_thread(cal.check_availability, start, m["duration"])  # last-moment re-check
        if not av.available:
            alts = [{"date": a.strftime("%Y-%m-%d"), "time": a.strftime("%H:%M"), "label": cal.spoken_slot(a)}
                    for a in av.alternatives]
            m.update(stage="collecting", alternatives=alts, checked_key=slot_key(m))
            listing = "; ".join(f"option {i + 1}: {a['label']}" for i, a in enumerate(alts)) or "none this week"
            return {"meeting": m, "directive": (
                f"Sorry — that slot was just taken. Apologise briefly and offer these free slots: {listing}. Ask which suits them.")}
        ev = await asyncio.to_thread(
            cal.create_event, meeting_id=m["meeting_id"], start=start, duration_min=m["duration"],
            customer_name=c.get("name") if has_name(c) else "Customer", customer_email=c["email"], purpose=purpose,
            requirement=c.get("requirement", ""), product_interest=c.get("product_interest", ""),
            company=c.get("company", ""), lead_summary=_lead_summary(state))
    except (GoogleAuthError, CalendarError) as e:
        logger.error(f"[Agent] Calendar event creation failed: {e}")
        await asyncio.to_thread(lead_tools.mark_meeting_failed, m["meeting_id"], f"create_event: {e}")
        m["stage"] = "pending_followup"
        return {"meeting": m, "errors": _extend(state, "errors", f"calendar_create: {e}"),
                "tool_log": _extend(state, "tool_log", "calendar_create: FAILED"),
                "directive": (
                    "The meeting could NOT be created in the calendar (technical problem). Do not say it is booked. Apologise "
                    "briefly and say the Fortivex team will confirm the meeting with them by email shortly. Ask if there is "
                    "anything else.")}

    await asyncio.to_thread(lead_tools.mark_meeting_scheduled, m["meeting_id"], ev["event_id"], ev["meet_link"])
    m.update(stage="booked", event_id=ev["event_id"], link=ev["meet_link"], alternatives=[])
    # rescheduling: remove the previous event now that the new one exists
    if m.get("old_event_id"):
        try:
            await asyncio.to_thread(cal.delete_event, m["old_event_id"])
            if m.get("old_meeting_id"):
                await asyncio.to_thread(lead_tools.mark_meeting_cancelled, m["old_meeting_id"])
        except (GoogleAuthError, CalendarError) as e:
            logger.error(f"[Agent] Could not delete the previous event: {e}")
        m.update(old_event_id=None, old_meeting_id=None)
    upd = await _persist({**state, "meeting": m}, dict(state.get("flags", {})))
    return {"meeting": m, **upd, "tool_log": _extend(state, "tool_log", "calendar_create: OK"),
            "directive": f"The meeting is confirmed for {cal.spoken_slot(start)}."}


async def send_email(state: Dict[str, Any]) -> Dict[str, Any]:
    """Send the Gmail confirmation — only reached after the calendar event was really created."""
    m, c = dict(state["meeting"]), state.get("customer", {})
    start = _slot_dt(m)
    tzname = "IST" if settings.DEFAULT_TIMEZONE == "Asia/Kolkata" else start.tzname()
    topic = m.get("purpose") or c.get("requirement") or "Discussion with the Fortivex AI team"
    booked = f"{cal.spoken_slot(start)} (India time)"
    try:
        await asyncio.to_thread(
            gmail_tools.send_confirmation_email, to_email=c["email"], name=c.get("name") or "there",
            date_text=start.strftime("%A, %d %B %Y"), time_text=f"{start.strftime('%I:%M %p')} {tzname}",
            duration_min=m["duration"], meet_link=m.get("link") or "", topic=topic)
        await asyncio.to_thread(lead_tools.set_email_status, m["meeting_id"], "sent")
        m["email_status"] = "sent"
        d = (f"CONFIRMED: the meeting is booked for {booked} and a confirmation email with the details has been sent to "
             f"{_spoken_email(c['email'])}. The Google Meet link is in the calendar invitation. Tell them this briefly and ask "
             f"if there is anything else you can help with.")
        log = "gmail_send: OK"
    except (GoogleAuthError, EmailError) as e:
        logger.error(f"[Agent] Confirmation email failed: {e}")
        await asyncio.to_thread(lead_tools.set_email_status, m["meeting_id"], "failed")
        m["email_status"] = "failed"
        d = (f"CONFIRMED: the meeting is booked for {booked} and the calendar invitation goes to their email. HOWEVER the "
             f"separate confirmation email could NOT be sent right now — do not say an email was sent; say the team will "
             f"make sure they receive the details. Ask if there is anything else.")
        log = "gmail_send: FAILED"
        state = {**state, "errors": _extend(state, "errors", f"gmail: {e}")}
    return {"meeting": m, "directive": d, "errors": state.get("errors", []),
            "tool_log": _extend(state, "tool_log", log)}


async def handle_meeting_change(state: Dict[str, Any]) -> Dict[str, Any]:
    """Cancel an existing / pending meeting (rescheduling is handled by the stage machine in meeting_info)."""
    m = dict(state["meeting"])
    if m.get("event_id"):
        try:
            await asyncio.to_thread(cal.delete_event, m["event_id"])
        except (GoogleAuthError, CalendarError) as e:
            logger.error(f"[Agent] Cancel failed: {e}")
            return {"errors": _extend(state, "errors", f"calendar_cancel: {e}"), "directive": (
                "You could NOT cancel the meeting automatically (technical problem). Do not say it is cancelled. Say the "
                "Fortivex team will take care of the cancellation and confirm with them.")}
    if m.get("meeting_id"):
        await asyncio.to_thread(lead_tools.mark_meeting_cancelled, m["meeting_id"])
    m.update(stage="cancelled", event_id=None, meeting_id=None, link=None, date=None, time=None, time_hint=None,
             checked_key=None, alternatives=[], email_status="not_sent")
    return {"meeting": m, "directive": (
        "The meeting has been CANCELLED. Confirm this briefly and ask if they would like to reschedule for another time "
        "or if there is anything else.")}


# ------------------------------------------------------------------------------------------------ response
async def _policies() -> str:
    global _policy_cache
    if _policy_cache is None:
        try:
            _policy_cache = await asyncio.to_thread(retriever.get_policies)
        except Exception as e:
            logger.error(f"[Agent] Could not load policies: {e}")
            _policy_cache = []
    return "\n".join(f"- {p}" for p in _policy_cache) or "- Answer only from verified knowledge."


def _knowledge_block(state: Dict[str, Any]) -> str:
    docs = state.get("retrieved") or []
    if not docs:
        return "NONE"
    lines = []
    for d in docs:
        note = f" [Note: {d['qualification']}]" if d.get("qualification") else ""
        lines.append(f"({d['id']} | {d['entity']}) {d['title']}: {d['content']}{note}")
    return "\n".join(lines)


async def generate_response(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate the short natural spoken reply from the directive."""
    lang = state.get("language", "en-IN")
    language = prompts.language_name(lang)
    system = prompts.PERSONA.format(language=language, fallback=prompts.FALLBACK_LINE, policies=await _policies())
    booked_confirmed = state.get("meeting", {}).get("stage") == "booked" and "CONFIRMED" in state.get("directive", "")

    def build(extra: str = "") -> List[Dict[str, str]]:
        m = state.get("meeting") or {}
        if m.get("stage") == "booked" and m.get("date") and m.get("time"):
            try:
                m_sum = f"BOOKED for {cal.spoken_slot(_slot_dt(m))} ({m.get('duration', 30)} min, India time), topic: {m.get('purpose') or 'Fortivex discussion'}, email_status={m.get('email_status')}"
            except Exception:
                m_sum = f"BOOKED for {m.get('date')} {m.get('time')}"
        else:
            m_sum = _meeting_ctx(m)
        user = prompts.RESPONSE_USER.format(
            known=prompts.format_known(state.get("customer", {})),
            meeting_summary=m_sum,
            knowledge=_knowledge_block(state),
            transcript=prompts.format_transcript(state.get("history", [])[:-1] if not state.get("is_greeting") else []),
            user_input=state.get("user_input") or "(call just connected)",
            directive=state.get("directive", "Continue naturally.") + extra, language=language)
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    try:
        text = _clean_speech(await get_llm().complete(build(), max_tokens=320, temperature=0.5))
        if not booked_confirmed and _BOOKING_CLAIM.search(text):
            logger.warning(f"[Agent] Blocked premature booking claim: {text!r}")
            text = _clean_speech(await get_llm().complete(
                build(" IMPORTANT: nothing has been booked, sent or confirmed yet — do not say or imply that it has."),
                max_tokens=320, temperature=0.4))
            if _BOOKING_CLAIM.search(text):
                text = SAFE_ERROR_LINE.get(lang, SAFE_ERROR_LINE["en-IN"])
    except LLMError as e:
        logger.error(f"[Agent] Response generation failed: {e}")
        text = SAFE_ERROR_LINE.get(lang, SAFE_ERROR_LINE["en-IN"])
        return {"response": text, "errors": _extend(state, "errors", f"llm: {e}")}
    return {"response": text}


async def update_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Update conversation state and persist it (so an interrupted call can resume)."""
    history = list(state.get("history", []))
    history.append({"role": "ai", "text": state["response"]})
    history = history[-60:]
    flags = dict(state.get("flags", {}))
    upd = await _persist({**state, "history": history}, flags)
    merged = {**state, **upd, "history": history}
    snapshot = {k: merged.get(k) for k in ("language", "customer", "lead", "meeting", "flags")}
    try:
        await asyncio.to_thread(lead_tools.save_session, state["session_id"], merged.get("customer_id"),
                                merged.get("lead_id"), history, snapshot)
    except Exception as e:
        logger.error(f"[Agent] Session persistence failed: {e}")
    return {"history": history, **upd}
