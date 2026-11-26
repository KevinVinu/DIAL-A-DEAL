"""Lead, meeting and conversation-session persistence (SQLAlchemy). All functions open short-lived sessions."""
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.database.connection import SessionLocal
from app.database.models import Call, ConversationSession, Customer, FollowUp, Lead, Meeting
from app.utils.logger import logger

PLACEHOLDER_NAMES = ("Live Web Prospect", "Website Prospect")


# ----------------------------------------------------------------------------- customer / lead
def _merge_customers(db: Session, stub: Customer, existing: Customer):
    """The caller supplied an email/phone that already belongs to another customer -> reuse that customer."""
    for model in (Lead, Call, ConversationSession, Meeting, FollowUp):
        db.query(model).filter(model.customer_id == stub.id).update({"customer_id": existing.id})
    for attr in ("full_name", "company", "industry", "age", "location"):
        if not getattr(existing, attr) and getattr(stub, attr):
            setattr(existing, attr, getattr(stub, attr))
    db.flush()
    db.delete(stub)
    db.flush()
    logger.info(f"[Lead] Customer {stub.id} merged into existing customer {existing.id}")


def _apply_customer_fields(db: Session, customer: Customer, data: Dict) -> Customer:
    if data.get("name"):
        customer.full_name = data["name"]
    if data.get("company"):
        customer.company = data["company"]
    if data.get("industry"):
        customer.industry = data["industry"]
    if data.get("age"):
        try:
            customer.age = int(data["age"])
        except (ValueError, TypeError):
            pass
    for key, col in (("email", "email"), ("phone", "phone_number")):
        val = data.get(key)
        if not val or getattr(customer, col) == val:
            continue
        other = db.query(Customer).filter(getattr(Customer, col) == val, Customer.id != customer.id).first()
        if other:
            _merge_customers(db, customer, other)
            customer = other
        else:
            setattr(customer, col, val)
    return customer


def _score_to_interest(score: int) -> str:
    return "Hot" if score >= 70 else "Warm" if score >= 40 else "Cold"


def ensure_customer_and_lead(customer_id: Optional[str], lead_id: Optional[str], *, language: str = "en-IN",
                             name: str = "", age=None, company: str = "") -> Dict[str, str]:
    """Create (once) the customer + lead for a conversation when the caller of the agent did not supply them."""
    db = SessionLocal()
    try:
        customer = db.query(Customer).filter(Customer.id == customer_id).first() if customer_id else None
        if not customer:
            customer = Customer(full_name=name or "Live Web Prospect", age=age, company=company or None,
                                preferred_language=language)
            db.add(customer)
            db.flush()
        lead = db.query(Lead).filter(Lead.id == lead_id).first() if lead_id else None
        if not lead:
            lead = Lead(customer_id=customer.id, source="Live Voice Call", lead_status="New")
            db.add(lead)
            db.flush()
        db.commit()
        return {"customer_id": customer.id, "lead_id": lead.id}
    finally:
        db.close()


def persist_lead(*, customer_id: str, lead_id: str, customer: Dict, lead: Dict) -> Dict[str, str]:
    """Update (never duplicate) the customer and lead rows from the agent state. Returns the surviving ids."""
    db = SessionLocal()
    try:
        cust = db.query(Customer).filter(Customer.id == customer_id).first()
        if not cust:
            raise ValueError(f"customer {customer_id} not found")
        cust = _apply_customer_fields(db, cust, customer)

        lead_row = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead_row:
            lead_row = Lead(customer_id=cust.id, source="Live Voice Call")
            db.add(lead_row)
        lead_row.customer_id = cust.id
        lead_row.requirements = customer.get("requirement") or lead_row.requirements
        lead_row.product_interest = customer.get("product_interest") or lead_row.product_interest
        lead_row.interested_products = lead_row.product_interest
        lead_row.budget = customer.get("budget") or lead_row.budget
        pi = (customer.get("purchase_intent") or "").capitalize()
        if pi in ("High", "Medium", "Low"):
            lead_row.purchase_intent = pi
        score = int(lead.get("score", 0))
        lead_row.qualification_score = score
        lead_row.interest_level = _score_to_interest(score)
        if lead.get("status"):
            lead_row.lead_status = lead["status"]
        if lead.get("meeting_status"):
            lead_row.meeting_status = lead["meeting_status"]
            lead_row.follow_up_required = lead["meeting_status"] in ("Pending", "Suggested")
        if lead.get("summary"):
            lead_row.conversation_summary = lead["summary"]
            lead_row.notes = lead["summary"]
        db.commit()
        return {"customer_id": cust.id, "lead_id": lead_row.id}
    finally:
        db.close()


# ----------------------------------------------------------------------------- meetings
def _meeting_dict(m: Meeting) -> Dict:
    return {
        "meeting_id": m.meeting_id, "customer_id": m.customer_id, "lead_id": m.lead_id,
        "calendar_event_id": m.calendar_event_id, "meeting_date": m.meeting_date, "meeting_time": m.meeting_time,
        "duration": m.duration, "purpose": m.purpose, "meeting_status": m.meeting_status,
        "meeting_link": m.meeting_link, "email_status": m.email_status, "failure_reason": m.failure_reason,
    }


def upsert_pending_meeting(*, session_id: str, customer_id: str, lead_id: Optional[str], date: Optional[str],
                           time: Optional[str], duration: int, purpose: Optional[str], timezone: str,
                           meeting_id: Optional[str] = None) -> str:
    """One open (Pending) meeting per conversation; re-used when the slot changes — no duplicates."""
    db = SessionLocal()
    try:
        m = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first() if meeting_id else None
        if not m:
            m = (db.query(Meeting)
                 .filter(Meeting.session_id == session_id, Meeting.meeting_status == "Pending").first())
        if not m:
            m = Meeting(customer_id=customer_id, lead_id=lead_id, session_id=session_id, timezone=timezone)
            db.add(m)
        m.customer_id, m.lead_id = customer_id, lead_id
        m.meeting_date, m.meeting_time, m.duration, m.purpose = date, time, duration, purpose
        db.commit()
        return m.meeting_id
    finally:
        db.close()


def get_meeting(meeting_id: str) -> Optional[Dict]:
    db = SessionLocal()
    try:
        m = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
        return _meeting_dict(m) if m else None
    finally:
        db.close()


def list_meetings(customer_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
    db = SessionLocal()
    try:
        q = db.query(Meeting)
        if customer_id:
            q = q.filter(Meeting.customer_id == customer_id)
        return [_meeting_dict(m) for m in q.order_by(Meeting.created_at.desc()).limit(limit).all()]
    finally:
        db.close()


def _update_meeting(meeting_id: str, **fields):
    db = SessionLocal()
    try:
        m = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
        if m:
            for k, v in fields.items():
                setattr(m, k, v)
            db.commit()
    finally:
        db.close()


def mark_meeting_scheduled(meeting_id: str, event_id: str, link: str):
    _update_meeting(meeting_id, calendar_event_id=event_id, meeting_link=link,
                    meeting_status="Scheduled", failure_reason=None)


def mark_meeting_failed(meeting_id: str, reason: str):
    _update_meeting(meeting_id, failure_reason=reason[:500])  # stays Pending for team follow-up


def set_email_status(meeting_id: str, status: str):
    _update_meeting(meeting_id, email_status=status)


def mark_meeting_cancelled(meeting_id: str):
    _update_meeting(meeting_id, meeting_status="Cancelled")


# ----------------------------------------------------------------------------- conversation sessions
def load_session(session_id: str) -> Optional[Dict]:
    db = SessionLocal()
    try:
        row = db.query(ConversationSession).filter(ConversationSession.session_id == session_id).first()
        if not row:
            return None
        return {"state": row.agent_state or {}, "history": row.conversation_history or [],
                "customer_id": row.customer_id, "lead_id": row.lead_id}
    finally:
        db.close()


def save_session(session_id: str, customer_id: Optional[str], lead_id: Optional[str],
                 history: List[Dict], state: Dict):
    db = SessionLocal()
    try:
        row = db.query(ConversationSession).filter(ConversationSession.session_id == session_id).first()
        if not row:
            row = ConversationSession(session_id=session_id)
            db.add(row)
        row.customer_id, row.lead_id = customer_id, lead_id
        row.conversation_history = history
        row.agent_state = state
        row.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
