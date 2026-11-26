from typing import List, Dict, Any, Optional
from datetime import datetime

class ConversationContext:
    def __init__(self, call_session_id: str, language: str = "en-IN", lead_name: str = "Prospect"):
        self.call_session_id = call_session_id
        self.language = language
        self.lead_name = lead_name
        self.history: List[Dict[str, str]] = []
        self.max_history_turns = 10  # Context window trimming to preserve low LLM latency
        self.started_at = datetime.utcnow()
        self.call_state = "connecting"  # connecting, speaking, listening, ended
        self.bant = {
            "budget": None,
            "authority": None,
            "need": None,
            "timeline": None
        }
        self.objections: List[str] = []
        self.requirements: List[str] = []
        self.purchase_intent = "Medium"

    def add_turn(self, role: str, text: str):
        self.history.append({
            "role": role,
            "text": text,
            "timestamp": datetime.utcnow().isoformat()
        })
        self._update_simple_signals(role, text)

    def get_trimmed_history(self) -> List[Dict[str, str]]:
        """Returns the most recent N turns for the LLM prompt."""
        return self.history[-self.max_history_turns:]

    def _update_simple_signals(self, role: str, text: str):
        if role != "customer":
            return
        lower = text.lower()
        if any(w in lower for w in ["expensive", "budget", "cost", "price", "pricing", "महंगा", "விலை"]):
            self.objections.append("Pricing / Budget inquiry")
        if any(w in lower for w in ["crm", "salesforce", "hubspot", "integration", "api"]):
            self.requirements.append("CRM integration")
        if any(w in lower for w in ["demo", "schedule", "meet", "appointment", "डेमो", "டெமோ"]):
            self.purchase_intent = "High (Demo Requested)"
            self.bant["timeline"] = "Immediate / This week"
