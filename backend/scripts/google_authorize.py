"""
One-time interactive Google OAuth 2.0 authorisation script for DIAL-a-DEAL AI.

Grants Calendar (read/write) and Gmail (send) scopes and saves a refresh-token JSON file
at GOOGLE_TOKEN_FILE (default: backend/secrets/google_token.json).

Usage:
    cd backend
    python scripts/google_authorize.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow
from app.config import settings
from app.tools.google_auth import client_config


def main():
    cfg = client_config()
    if not cfg:
        print(
            "ERROR: Google OAuth client credentials not found.\n"
            f"Either place your OAuth client JSON at: {settings.GOOGLE_CLIENT_SECRETS_FILE}\n"
            "OR set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env."
        )
        sys.exit(1)

    token_path = Path(settings.GOOGLE_TOKEN_FILE)
    token_path.parent.mkdir(parents=True, exist_ok=True)

    flow = InstalledAppFlow.from_client_config(cfg, settings.GOOGLE_SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    token_path.write_text(creds.to_json())
    print(f"SUCCESS: Google Calendar + Gmail token saved to {token_path}")


if __name__ == "__main__":
    main()
