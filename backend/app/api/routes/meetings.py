"""Meetings & Google OAuth status routes."""
from typing import Optional
from fastapi import APIRouter, HTTPException

from app.tools import google_auth, lead_tools

router = APIRouter(prefix="/api/v1", tags=["Meetings & Integrations"])


@router.get("/meetings")
def list_meetings(customer_id: Optional[str] = None, limit: int = 50):
    return lead_tools.list_meetings(customer_id=customer_id, limit=limit)


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: str):
    m = lead_tools.get_meeting(meeting_id)
    if not m:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return m


@router.get("/google/status")
def google_status():
    """Reports whether Google OAuth 2.0 (Calendar + Gmail) is configured and authorised (no secrets exposed)."""
    return google_auth.auth_status()
