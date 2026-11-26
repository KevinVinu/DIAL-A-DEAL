"""Customer helpers: spoken-email normalisation and DB snapshot for conversational memory."""
import re
from typing import Optional

from app.database.connection import SessionLocal
from app.database.models import Customer

_EMAIL_FIND = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_DIGIT_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
                "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def normalize_spoken_email(text: str) -> str:
    """'rahul dot sharma at gmail dot com' -> 'rahul.sharma@gmail.com' (best effort)."""
    t = " " + (text or "").lower().strip() + " "
    t = re.sub(r"\s+(at the rate|at the rate of|at)\s+", "@", t) if "@" not in t else t
    t = re.sub(r"\s+dot\s+", ".", t)
    t = re.sub(r"\s+(underscore)\s+", "_", t)
    t = re.sub(r"\s+(dash|hyphen)\s+", "-", t)
    for w, d in _DIGIT_WORDS.items():
        t = re.sub(rf"\b{w}\b", d, t)
    t = re.sub(r"\s*@\s*", "@", t)
    t = re.sub(r"(?<=[\w])\s+(?=[\w.]*@)", "", t)
    return t.strip()


def extract_email(text: str) -> Optional[str]:
    m = _EMAIL_FIND.search(normalize_spoken_email(text))
    return m.group(0).strip(".") if m else None


def snapshot_customer(customer_id: Optional[str]) -> dict:
    """Stored details for THIS conversation's customer only (never other customers)."""
    if not customer_id:
        return {}
    db = SessionLocal()
    try:
        c = db.query(Customer).filter(Customer.id == customer_id).first()
        if not c:
            return {}
        return {k: v for k, v in {
            "name": c.full_name if c.full_name not in ("Live Web Prospect", "Website Prospect") else None,
            "company": c.company, "industry": c.industry, "email": c.email,
            "phone": c.phone_number, "age": c.age,
        }.items() if v}
    finally:
        db.close()
