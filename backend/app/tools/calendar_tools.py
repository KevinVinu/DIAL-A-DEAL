"""
Google Calendar tools: real availability (freebusy), alternative-slot search, event creation (with Google Meet),
cancellation. Blocking Google client calls — invoke via asyncio.to_thread from async code.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date as date_cls
from typing import List, Optional
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from app.config import settings
from app.tools.google_auth import GoogleAuthError, calendar_service  # noqa: F401  (GoogleAuthError re-exported)
from app.utils.logger import logger

TZ = ZoneInfo(settings.DEFAULT_TIMEZONE)
STEP_MIN = 30
SEARCH_DAYS = 7


class CalendarError(Exception):
    pass


@dataclass
class Availability:
    available: bool
    reason: str = ""                 # why unavailable: past | outside_hours | busy
    alternatives: List[datetime] = field(default_factory=list)


def now_local() -> datetime:
    return datetime.now(TZ)


def parse_slot(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


def _in_working_hours(start: datetime, duration_min: int) -> bool:
    if start.weekday() not in settings.MEETING_WORK_DAYS:
        return False
    end = start + timedelta(minutes=duration_min)
    day_start = start.replace(hour=settings.MEETING_WORK_START_HOUR, minute=0, second=0, microsecond=0)
    day_end = start.replace(hour=settings.MEETING_WORK_END_HOUR, minute=0, second=0, microsecond=0)
    return start >= day_start and end <= day_end


def _overlaps(start: datetime, end: datetime, busy: List[tuple]) -> bool:
    return any(start < b_end and end > b_start for b_start, b_end in busy)


def _calendar_ids() -> List[str]:
    ids = [settings.FORTIVEX_CALENDAR_ID]
    ids += [e for e in settings.FORTIVEX_TEAM_EMAILS if e not in ids]
    return ids


def get_busy_intervals(time_min: datetime, time_max: datetime, service=None) -> List[tuple]:
    """Busy intervals across the team calendars. Raises CalendarError if the main calendar is unreadable."""
    service = service or calendar_service()
    body = {
        "timeMin": time_min.isoformat(), "timeMax": time_max.isoformat(),
        "timeZone": settings.DEFAULT_TIMEZONE,
        "items": [{"id": cid} for cid in _calendar_ids()],
    }
    try:
        resp = service.freebusy().query(body=body).execute()
    except HttpError as e:
        raise CalendarError(f"Calendar freebusy failed: {e}")

    busy, readable = [], 0
    for cid, info in resp.get("calendars", {}).items():
        if info.get("errors"):
            logger.warning(f"[Calendar] Cannot read availability of '{cid}': {info['errors']}")
            if cid == settings.FORTIVEX_CALENDAR_ID:
                raise CalendarError(f"Main team calendar '{cid}' is not readable: {info['errors']}")
            continue
        readable += 1
        for b in info.get("busy", []):
            busy.append((datetime.fromisoformat(b["start"]).astimezone(TZ),
                         datetime.fromisoformat(b["end"]).astimezone(TZ)))
    if readable == 0:
        raise CalendarError("No team calendar could be read")
    return busy


def check_availability(start: datetime, duration_min: int, service=None) -> Availability:
    """Check the requested slot against real calendar data and suggest real alternatives when it is not free."""
    now = now_local()
    end = start + timedelta(minutes=duration_min)
    window_end = max(start, now).replace(hour=23, minute=59) + timedelta(days=SEARCH_DAYS)
    busy = get_busy_intervals(now, window_end, service)

    reason = ""
    if start <= now + timedelta(minutes=10):
        reason = "past"
    elif not _in_working_hours(start, duration_min):
        reason = "outside_hours"
    elif _overlaps(start, end, busy):
        reason = "busy"
    if not reason:
        return Availability(True)

    # Alternatives: scan forward from the requested time (or now, if the request was in the past)
    cursor = max(start, now + timedelta(minutes=30))
    cursor = cursor.replace(minute=(0 if cursor.minute < 30 else 30), second=0, microsecond=0)
    if cursor < max(start, now + timedelta(minutes=30)):
        cursor += timedelta(minutes=STEP_MIN)
    alts: List[datetime] = []
    horizon = cursor + timedelta(days=SEARCH_DAYS)
    last_day = None
    while cursor < horizon and len(alts) < 3:
        c_end = cursor + timedelta(minutes=duration_min)
        if _in_working_hours(cursor, duration_min) and not _overlaps(cursor, c_end, busy) and cursor != start:
            # spread suggestions: at most 2 on the same day
            if sum(1 for a in alts if a.date() == cursor.date()) < 2:
                alts.append(cursor)
        last_day = cursor.date()
        cursor += timedelta(minutes=STEP_MIN)
    return Availability(False, reason=reason, alternatives=alts)


def create_event(*, meeting_id: str, start: datetime, duration_min: int, customer_name: str,
                 customer_email: str, purpose: str, requirement: str, product_interest: str,
                 company: str, lead_summary: str, service=None) -> dict:
    """
    Create the Google Calendar event (+ Google Meet). Idempotent: the event id is derived from our meeting id,
    so a retry can never create a second event. Returns {event_id, html_link, meet_link}.
    """
    service = service or calendar_service()
    event_id = meeting_id.replace("-", "").lower()  # base32hex-compatible (0-9a-f)
    end = start + timedelta(minutes=duration_min)

    description = (
        f"Meeting with {customer_name}{' (' + company + ')' if company else ''}\n\n"
        f"Purpose: {purpose}\n"
        f"Customer requirements: {requirement or 'Not specified'}\n"
        f"Fortivex product / service of interest: {product_interest or 'To be discussed'}\n\n"
        f"Lead summary (DIAL-a-DEAL AI voice agent):\n{lead_summary or 'N/A'}\n\n"
        f"Customer email: {customer_email}\n"
        f"Scheduled by DIAL-a-DEAL AI on behalf of Fortivex AI."
    )
    attendees = [{"email": customer_email, "displayName": customer_name}]
    attendees += [{"email": e} for e in settings.FORTIVEX_TEAM_EMAILS if e.lower() != customer_email.lower()]

    body = {
        "id": event_id,
        "summary": f"Fortivex AI x {customer_name} — {purpose[:60]}",
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": settings.DEFAULT_TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": settings.DEFAULT_TIMEZONE},
        "attendees": attendees,
        "conferenceData": {"createRequest": {
            "requestId": event_id, "conferenceSolutionKey": {"type": "hangoutsMeet"}}},
        "reminders": {"useDefault": True},
    }
    try:
        ev = service.events().insert(
            calendarId=settings.FORTIVEX_CALENDAR_ID, body=body,
            conferenceDataVersion=1, sendUpdates="all",
        ).execute()
    except HttpError as e:
        if getattr(e.resp, "status", None) == 409:  # already created by an earlier attempt -> reuse it
            logger.warning(f"[Calendar] Event {event_id} already exists; reusing")
            ev = service.events().get(calendarId=settings.FORTIVEX_CALENDAR_ID, eventId=event_id).execute()
        else:
            raise CalendarError(f"Calendar event creation failed: {e}")

    meet_link = ev.get("hangoutLink") or ""
    if not meet_link:
        for ep in (ev.get("conferenceData") or {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")
    if not ev.get("id"):
        raise CalendarError("Calendar API returned no event id")
    return {"event_id": ev["id"], "html_link": ev.get("htmlLink", ""), "meet_link": meet_link}


def delete_event(event_id: str, service=None) -> bool:
    service = service or calendar_service()
    try:
        service.events().delete(calendarId=settings.FORTIVEX_CALENDAR_ID, eventId=event_id,
                                sendUpdates="all").execute()
        return True
    except HttpError as e:
        if getattr(e.resp, "status", None) in (404, 410):
            return True  # already gone
        raise CalendarError(f"Calendar event deletion failed: {e}")


def spoken_slot(dt: datetime) -> str:
    """e.g. 'Tuesday, 2 December at 3:30 PM'"""
    return f"{dt.strftime('%A')}, {dt.day} {dt.strftime('%B')} at {dt.strftime('%I:%M %p').lstrip('0')}"
