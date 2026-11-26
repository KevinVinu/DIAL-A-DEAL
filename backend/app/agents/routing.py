"""
Routing logic for the LangGraph agent: decides the next action from the structured conversation state.
Pure functions (no I/O) so they are unit-testable.
"""
from typing import Any, Dict, List

from app.agents.state import slot_key
from app.tools.gmail_tools import is_valid_email

KNOWLEDGE_INTENTS = {"ask_company", "ask_product", "ask_services", "business_requirement", "purchase_interest"}
MEETING_INTENTS = {"agree_meeting", "request_callback", "confirm_slot", "reject_slot", "change_meeting",
                   "cancel_meeting", "decline_meeting"}

PLACEHOLDER_NAMES = {"", "Live Web Prospect", "Website Prospect", "Valued Caller", "Live Prospect"}


def has_name(customer: Dict[str, Any]) -> bool:
    return (customer.get("name") or "") not in PLACEHOLDER_NAMES


def missing_meeting_fields(state: Dict[str, Any]) -> List[str]:
    """Only what is genuinely missing. Duration defaults to 30 min (stated at confirmation)."""
    c, m = state.get("customer", {}), state.get("meeting", {})
    missing = []
    if not m.get("date"):
        missing.append("date")
    if not m.get("time"):
        missing.append("time")
    if not is_valid_email(c.get("email")):
        missing.append("email")
    if not has_name(c):
        missing.append("name")
    if not (m.get("purpose") or c.get("requirement")):
        missing.append("purpose")
    return missing


def provided_meeting_info(state: Dict[str, Any]) -> bool:
    """Did the customer give any scheduling data (date/time/choice/email) in this turn?"""
    a = state.get("analysis") or {}
    mt = a.get("meeting") or {}
    ex = a.get("extracted") or {}
    return bool(mt.get("date") or mt.get("time") or mt.get("time_hint") or mt.get("choice_index")
                or ex.get("email") or state.get("meeting", {}).get("slot_changed"))


def should_suggest_meeting(state: Dict[str, Any]) -> bool:
    flags, m, lead = state.get("flags", {}), state.get("meeting", {}), state.get("lead", {})
    if flags.get("meeting_suggested") or flags.get("meeting_declined"):
        return False
    if m.get("stage") != "none":
        return False
    return lead.get("status") == "Qualified"


def decide_next_action(state: Dict[str, Any]) -> str:
    a = state.get("analysis") or {}
    intent = state.get("intent", "")
    conf = a.get("confirmation")
    m = state.get("meeting", {})
    stage = m.get("stage", "none")

    if state.get("is_greeting"):
        return "greet"

    # ---- cancel an existing meeting (rescheduling is a stage transition handled in the meeting_info node)
    if intent == "cancel_meeting" and (m.get("event_id") or m.get("meeting_id") or stage in ("proposed", "collecting")):
        return "handle_meeting_change"

    # ---- active scheduling flow
    if stage == "proposed":
        if (conf == "yes" or intent == "confirm_slot") and not m.get("slot_changed"):
            ok = not missing_meeting_fields(state)
            return "create_event" if ok else "collect_meeting_details"
        # new slot / chosen alternative / rejected -> back to collecting logic below
    in_flow = stage in ("collecting", "proposed", "pending_followup") or (
        intent in ("agree_meeting", "request_callback", "confirm_slot") and stage in ("none", "suggested", "cancelled"))
    if in_flow:
        if stage == "pending_followup" and intent not in ("agree_meeting", "request_callback", "confirm_slot"):
            pass  # team will follow up; carry on with the normal conversation
        elif (intent in KNOWLEDGE_INTENTS and not provided_meeting_info(state) and conf is None
              and intent not in MEETING_INTENTS):
            return "answer_company"  # answer the side-question first, then resume the pending step
        else:
            if missing_meeting_fields(state):
                return "collect_meeting_details"
            if slot_key(m) != m.get("checked_key"):
                return "check_availability"
            return "collect_meeting_details"  # slot known to be unavailable -> re-offer alternatives

    # ---- proactive suggestion once the lead is qualified
    if should_suggest_meeting(state) and intent not in ("end_call",):
        return "suggest_meeting"

    if intent in KNOWLEDGE_INTENTS or a.get("needs_company_knowledge"):
        return "answer_company"
    return "continue_conversation"


def route_after_intake(state: Dict[str, Any]) -> str:
    return "greet" if state.get("is_greeting") else "detect_intent"


def route_after_create_event(state: Dict[str, Any]) -> str:
    m = state.get("meeting", {})
    return "send_email" if m.get("stage") == "booked" and m.get("email_status") != "sent" else "generate_response"
