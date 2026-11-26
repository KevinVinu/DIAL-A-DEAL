from typing import Optional

class ObjectionHandler:
    """Provides targeted counter-points and value propositions for common sales hesitations."""

    OBJECTION_PLAYBOOKS = {
        "pricing": {
            "triggers": ["too expensive", "high price", "cost", "budget", "महंगा", "விலை அதிகம்"],
            "response_guide": "Highlight that DIAL-a-DEAL AI replaces manual dialer seats and saves over 20 SDR hours per week, paying for itself within 60 days with 3.8x higher meeting conversions."
        },
        "timing": {
            "triggers": ["busy right now", "call later", "next quarter", "not now", "समय नहीं है"],
            "response_guide": "Respect their time immediately. Offer a quick 15-minute executive demo on Tuesday at their convenience."
        },
        "competitor": {
            "triggers": ["using another tool", "already have an agency", "already have sdr"],
            "response_guide": "Acknowledge their existing solution. Emphasize our sub-280ms voice latency, multi-language Indian dialect support, and real-time BANT qualification."
        },
        "security": {
            "triggers": ["data security", "privacy", "soc 2", "compliance"],
            "response_guide": "Confirm enterprise compliance with encrypted in-transit voice streams and zero customer PII retention without consent."
        }
    }

    @classmethod
    def get_objection_hint(cls, customer_text: str) -> Optional[str]:
        lower = customer_text.lower()
        for obj_type, data in cls.OBJECTION_PLAYBOOKS.items():
            if any(t in lower for t in data["triggers"]):
                return data["response_guide"]
        return None
