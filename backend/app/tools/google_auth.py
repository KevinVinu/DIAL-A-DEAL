"""
Google OAuth 2.0 helper shared by the Calendar and Gmail tools.

Authorisation is a one-time, user-consented step:  python scripts/google_authorize.py
That stores a refresh-token file (GOOGLE_TOKEN_FILE). At runtime tokens are refreshed automatically.
If credentials are missing / revoked / expired, GoogleAuthError is raised so callers can report the failure
internally and NEVER pretend that a calendar event or email was created.
"""
import json
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import settings
from app.utils.logger import logger


class GoogleAuthError(Exception):
    """Google integration is not authorised / authorisation expired."""


def client_config() -> dict | None:
    """OAuth client config from a secrets file or from GOOGLE_CLIENT_ID/SECRET env vars."""
    p = Path(settings.GOOGLE_CLIENT_SECRETS_FILE)
    if p.exists():
        return json.loads(p.read_text())
    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        return {"installed": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }}
    return None


def load_credentials() -> Credentials:
    token_path = Path(settings.GOOGLE_TOKEN_FILE)
    if not token_path.exists():
        raise GoogleAuthError(
            "Google is not authorised yet. Run `python scripts/google_authorize.py` once to grant "
            "Calendar + Gmail access."
        )
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), settings.GOOGLE_SCOPES)
    except Exception as e:
        raise GoogleAuthError(f"Stored Google token is unreadable: {e}")

    missing = [s for s in settings.GOOGLE_SCOPES if creds.scopes and s not in creds.scopes]
    if missing:
        raise GoogleAuthError(f"Google token lacks required scopes: {missing}. Re-run google_authorize.py")

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json())
                logger.info("[Google] Access token refreshed")
            except RefreshError as e:
                raise GoogleAuthError(f"Google refresh token expired or revoked ({e}). Re-run google_authorize.py")
        else:
            raise GoogleAuthError("Google credentials are invalid and cannot be refreshed. Re-run google_authorize.py")
    return creds


def calendar_service():
    return build("calendar", "v3", credentials=load_credentials(), cache_discovery=False)


def gmail_service():
    return build("gmail", "v1", credentials=load_credentials(), cache_discovery=False)


def auth_status() -> dict:
    """Non-secret diagnostic used by /api/google/status."""
    status = {
        "client_configured": client_config() is not None,
        "token_present": Path(settings.GOOGLE_TOKEN_FILE).exists(),
        "authorised": False,
        "error": None,
    }
    try:
        load_credentials()
        status["authorised"] = True
    except GoogleAuthError as e:
        status["error"] = str(e)
    return status
