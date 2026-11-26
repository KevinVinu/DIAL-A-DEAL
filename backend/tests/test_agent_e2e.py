"""
Phase 6 — End-to-End LangGraph Agent, RAG, Lead Persistence, Calendar & Gmail Scenarios.

Uses the real Groq LLM (`openai/gpt-oss-20b`), real ChromaDB + Sentence-Transformers RAG,
and real SQLite/SQLAlchemy persistence. Google Calendar & Gmail API clients are exercised
through dependency-injected test doubles so we test all conflict, alternative-slot,
event-creation, email-confirmation, and failure-handling paths deterministically without
requiring live Google OAuth browser tokens in CI.
"""
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agents import nodes
from app.agents.state import new_state
from app.database.connection import SessionLocal, init_db
from app.database.models import Customer, Lead, Meeting
from app.main import app
from app.rag.vector_store import ensure_index
from app.services.conversation_service import AgentConversationService
from app.tools import calendar_tools as cal
from app.tools.google_auth import GoogleAuthError


@pytest.fixture(scope="module", autouse=True)
def setup_env():
    init_db()
    ensure_index()
    yield


def _future_weekday(days_ahead: int = 2, hour: int = 14) -> datetime:
    now = cal.now_local()
    target = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=0, second=0, microsecond=0)
    while target.weekday() == 6:  # avoid Sunday
        target += timedelta(days=1)
    return target


@pytest.mark.asyncio
async def test_phase6_full_sales_and_scheduling_journey(tmp_path):
    """
    Tests scenarios 1-9 in a single continuous customer conversation:
      1. "What does Fortivex do?"
      2. "Does Fortivex offer CRM solutions?"
      3. "I run a small business and need CRM automation."
      4. Customer provides name and email -> stored in DB, single lead (no duplicates)
      5. Customer agrees to a meeting -> agent asks only missing fields
      6. Unavailable slot -> Calendar check detects conflict and proposes alternatives
      7. Customer confirms available slot -> Calendar event created + Gmail confirmation sent
      8. Post-scheduling recall -> Agent remembers requirements and meeting details
      9. Out-of-KB question -> Agent states verified info is unavailable
    """
    svc = AgentConversationService(checkpoint_db_path=str(tmp_path / "ckpt.db"))
    sid = f"e2e-{uuid.uuid4().hex[:8]}"
    test_email = f"rahul.{uuid.uuid4().hex[:6]}@example.com"

    busy_dt = _future_weekday(days_ahead=2, hour=14)
    busy_date = busy_dt.strftime("%Y-%m-%d")

    created_events = []
    sent_emails = []

    def fake_check_availability(start: datetime, duration_min: int):
        # Simulate 14:00 on busy_date as BUSY, 15:00 and 16:00 as FREE
        if start.strftime("%Y-%m-%d %H:%M") == f"{busy_date} 14:00":
            alt1 = start.replace(hour=15, minute=0)
            alt2 = start.replace(hour=16, minute=0)
            return cal.Availability(available=False, reason="busy", alternatives=[alt1, alt2])
        return cal.Availability(available=True)

    def fake_create_event(**kwargs):
        created_events.append(kwargs)
        return {
            "event_id": f"evt_{kwargs['meeting_id'][:8]}",
            "html_link": "https://calendar.google.com/event?eid=test",
            "meet_link": "https://meet.google.com/abc-defg-hij",
        }

    def fake_send_email(**kwargs):
        sent_emails.append(kwargs)
        return "msg_12345"

    try:
        with patch("app.agents.nodes.cal.check_availability", side_effect=fake_check_availability), \
             patch("app.agents.nodes.cal.create_event", side_effect=fake_create_event), \
             patch("app.agents.nodes.gmail_tools.send_confirmation_email", side_effect=fake_send_email):

            # Greeting
            g = await svc.run_greeting(sid, language="en-IN")
            assert len(g["response"]) > 0
            assert "Fortivex" in g["response"] or "Alex" in g["response"]

            # 1. "What does Fortivex do?"
            t1 = await svc.run_turn(sid, "What does Fortivex do?")
            assert t1["grounded"] is True
            assert any(d["id"] in ("sales.faq.001", "company.identity.002") for d in t1["retrieved"])
            assert len(t1["response"]) > 10

            # 2. "Does Fortivex offer CRM solutions?"
            t2 = await svc.run_turn(sid, "Does Fortivex offer CRM solutions?")
            assert t2["grounded"] is True
            assert any(d["id"].startswith("product.crm") for d in t2["retrieved"])
            assert "CRM" in t2["response"]

            # 3. "I run a small business and need CRM automation."
            t3 = await svc.run_turn(sid, "I run a small business and need CRM automation.")
            assert t3["customer"].get("requirement")
            assert t3["lead"]["score"] > 0

            # 4. Customer provides name and email
            t4 = await svc.run_turn(sid, f"My name is Rahul Sharma and my email is {test_email}")
            assert t4["customer"].get("name") and "Rahul" in t4["customer"]["name"]
            assert t4["customer"].get("email") == test_email

            # Verify DB persisted customer & single lead (no duplicates)
            db = SessionLocal()
            try:
                cust = db.query(Customer).filter(Customer.id == t4["customer_id"]).first()
                assert cust is not None and "Rahul" in cust.full_name
                assert cust.email == test_email
                lead_count = db.query(Lead).filter(Lead.customer_id == cust.id).count()
                assert lead_count == 1
            finally:
                db.close()

            # 5. Customer agrees to a meeting + gives unavailable slot
            t5 = await svc.run_turn(
                sid,
                f"Yes, I would like to schedule a meeting on {busy_date} at 2 PM to discuss Fortivex CRM."
            )
            assert t5["meeting"]["stage"] == "collecting"
            assert len(t5["meeting"]["alternatives"]) >= 1
            assert "calendar_availability: False" in t5["tool_log"]

            # 6. Customer picks option 1 (15:00)
            t6 = await svc.run_turn(sid, "Let's go with option 1 at 3 PM then.")
            assert t6["meeting"]["stage"] == "proposed"
            assert t6["meeting"]["time"] == "15:00"
            assert "calendar_availability: True" in t6["tool_log"]
            assert len(created_events) == 0  # NOT booked before confirmation!

            # 7. Customer confirms slot -> Calendar event created + Gmail sent
            t7 = await svc.run_turn(sid, "Yes, please book it.")
            assert t7["meeting"]["stage"] == "booked"
            assert t7["meeting"]["email_status"] == "sent"
            assert len(created_events) == 1
            assert len(sent_emails) == 1
            assert sent_emails[0]["to_email"] == test_email
            assert "calendar_create: OK" in t7["tool_log"]
            assert "gmail_send: OK" in t7["tool_log"]

            # Verify Meeting row in DB
            db = SessionLocal()
            try:
                m_row = db.query(Meeting).filter(Meeting.meeting_id == t7["meeting"]["meeting_id"]).first()
                assert m_row is not None
                assert m_row.meeting_status == "Scheduled"
                assert m_row.email_status == "sent"
                assert m_row.calendar_event_id.startswith("evt_")
            finally:
                db.close()

            # 8. Customer asks another question after scheduling -> recalls requirements & meeting
            t8 = await svc.run_turn(sid, "By the way, what time is our meeting and what did I say I needed?")
            assert "3" in t8["response"] or "15:00" in t8["response"]
            assert "CRM" in t8["response"] or "automation" in t8["response"].lower()

            # 9. Out-of-KB company question -> does not invent revenue or client names
            t9 = await svc.run_turn(sid, "What was Fortivex AI's annual revenue last year and who are your biggest clients?")
            resp_low = t9["response"].lower()
            assert any(p in resp_low for p in ("don't have verified", "do not have verified", "not verified", "fortivex team", "don't have that"))
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_google_auth_failure_does_not_claim_booking(tmp_path):
    """If Google OAuth is not authorised or expired, the agent must NEVER claim a meeting was booked."""
    svc = AgentConversationService(checkpoint_db_path=str(tmp_path / "ckpt_fail.db"))
    sid = f"fail-{uuid.uuid4().hex[:8]}"
    slot_dt = _future_weekday(days_ahead=3, hour=11)
    slot_date = slot_dt.strftime("%Y-%m-%d")

    try:
        with patch("app.agents.nodes.cal.check_availability", side_effect=GoogleAuthError("Token expired")):
            await svc.run_greeting(sid)
            out = await svc.run_turn(
                sid,
                f"I am Priya Nair, email priya@example.com. Please schedule a Fortivex CRM demo on {slot_date} at 11 AM."
            )
            assert out["meeting"]["stage"] == "pending_followup"
            assert "calendar_availability: FAILED" in out["tool_log"]
            assert not nodes._BOOKING_CLAIM.search(out["response"])
    finally:
        await svc.close()


def test_rest_chat_and_meetings_endpoints():
    with TestClient(app) as client:
        r = client.get("/api/v1/google/status")
        assert r.status_code == 200
        assert "authorised" in r.json()

        r2 = client.get("/api/v1/meetings")
        assert r2.status_code == 200
        assert isinstance(r2.json(), list)
