"""Structured conversational state carried through the LangGraph StateGraph (JSON-serialisable)."""
from typing import Any, Dict, List, TypedDict

from app.config import settings


class AgentState(TypedDict, total=False):
    # identity of this conversation (never shared between customers)
    session_id: str
    language: str
    customer_id: str
    lead_id: str

    # per-turn inputs/transients (reset by the intake node)
    is_greeting: bool
    user_input: str
    analysis: Dict[str, Any]
    intent: str
    retrieved: List[Dict[str, Any]]
    grounded: bool
    next_action: str
    directive: str
    response: str
    tool_log: List[str]
    errors: List[str]

    # persistent memory
    history: List[Dict[str, str]]       # [{"role": "customer"|"ai", "text": ...}]
    customer: Dict[str, Any]            # name, company, industry, email, phone, age, requirement, product_interest,
                                        # challenges, budget, purchase_intent  (CUSTOMER-STATED, unverified)
    lead: Dict[str, Any]                # score, status, meeting_status, summary
    meeting: Dict[str, Any]
    flags: Dict[str, Any]               # meeting_suggested, meeting_declined, last_persist_hash, ...


def new_meeting() -> Dict[str, Any]:
    return {
        "stage": "none",   # none | suggested | collecting | proposed | booked | pending_followup | cancelled
        "date": None, "time": None, "time_hint": None,
        "duration": settings.MEETING_DEFAULT_DURATION_MIN,
        "purpose": None, "timezone": settings.DEFAULT_TIMEZONE,
        "meeting_id": None, "event_id": None, "link": None,
        "email_status": "not_sent",
        "alternatives": [],          # [{"date","time","label"}]
        "checked_key": None,         # slot that was last availability-checked
        "old_event_id": None, "old_meeting_id": None,
        "slot_changed": False,
    }


def new_state(session_id: str, language: str = "en-IN", customer_id: str = "", lead_id: str = "") -> AgentState:
    return AgentState(
        session_id=session_id, language=language, customer_id=customer_id, lead_id=lead_id,
        history=[], customer={}, lead={"score": 0, "status": "New", "meeting_status": "None", "summary": ""},
        meeting=new_meeting(), flags={}, tool_log=[], errors=[],
    )


def slot_key(m: Dict[str, Any]) -> str:
    return f"{m.get('date')}|{m.get('time')}|{m.get('duration')}"
