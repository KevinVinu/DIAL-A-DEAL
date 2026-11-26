"""Gmail tools — sends the meeting confirmation through the Gmail API (OAuth 2.0)."""
import base64
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from googleapiclient.errors import HttpError

from app.config import settings
from app.tools.google_auth import GoogleAuthError, gmail_service  # noqa: F401
from app.utils.logger import logger

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class EmailError(Exception):
    pass


def is_valid_email(email: str | None) -> bool:
    return bool(email and EMAIL_RE.match(email.strip()))


def build_confirmation(*, name: str, date_text: str, time_text: str, duration_min: int,
                       meet_link: str, topic: str) -> tuple[str, str, str]:
    first = (name or "there").split()[0]
    subject = "Your Meeting with Fortivex AI Has Been Scheduled"
    link_line = meet_link or "A Google Meet link is included in your calendar invitation."
    text = (
        f"Hello {first},\n\n"
        "Thank you for your interest in Fortivex AI.\n\n"
        "We are pleased to confirm your meeting with our team.\n\n"
        "Meeting Details:\n"
        f"Date: {date_text}\n"
        f"Time: {time_text}\n"
        f"Duration: {duration_min} minutes\n"
        f"Meeting Link: {link_line}\n\n"
        "Discussion Topic:\n"
        f"{topic}\n\n"
        "Our team looks forward to understanding your requirements and exploring how Fortivex can assist your business.\n\n"
        f"Best regards,\n{settings.EMAIL_SENDER_NAME}\n"
    )
    html = (
        f"<p>Hello {first},</p><p>Thank you for your interest in Fortivex AI.</p>"
        "<p>We are pleased to confirm your meeting with our team.</p>"
        "<p><b>Meeting Details:</b><br>"
        f"Date: {date_text}<br>Time: {time_text}<br>Duration: {duration_min} minutes<br>"
        f"Meeting Link: {('<a href=' + chr(34) + meet_link + chr(34) + '>' + meet_link + '</a>') if meet_link else link_line}</p>"
        f"<p><b>Discussion Topic:</b><br>{topic}</p>"
        "<p>Our team looks forward to understanding your requirements and exploring how Fortivex can assist your business.</p>"
        f"<p>Best regards,<br>{settings.EMAIL_SENDER_NAME}</p>"
    )
    return subject, text, html


def send_confirmation_email(*, to_email: str, name: str, date_text: str, time_text: str, duration_min: int,
                            meet_link: str, topic: str, service=None) -> str:
    """Send the confirmation. Returns the Gmail message id. Raises EmailError / GoogleAuthError on failure."""
    if not is_valid_email(to_email):
        raise EmailError(f"Invalid recipient email: {to_email!r}")
    service = service or gmail_service()
    subject, text, html = build_confirmation(
        name=name, date_text=date_text, time_text=time_text, duration_min=duration_min,
        meet_link=meet_link, topic=topic)

    msg = MIMEMultipart("alternative")
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except HttpError as e:
        raise EmailError(f"Gmail send failed: {e}")
    if not sent.get("id"):
        raise EmailError("Gmail API returned no message id")
    logger.info(f"[Gmail] Confirmation sent to {to_email} (message {sent['id']})")
    return sent["id"]
