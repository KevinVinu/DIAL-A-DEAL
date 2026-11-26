import time
import httpx
from typing import List, Dict
from app.services.llm.base import BaseLLMService
from app.config import settings
from app.utils.logger import logger

class GeminiLLMService(BaseLLMService):
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = "gemini-1.5-flash"
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    async def generate_response(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        temperature: float = 0.6
    ) -> str:
        start_time = time.time()
        
        # If API key is not set, use contextual AI sales simulation fallback
        if not self.api_key:
            logger.warning("[LLM] GEMINI_API_KEY is not set. Operating in graceful simulation mode.")
            return self._fallback_response(conversation_history)

        try:
            # Build Gemini API contents payload
            contents = []
            
            # Format history
            for msg in conversation_history:
                role = "user" if msg["role"] == "customer" else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg["text"]}]
                })

            payload = {
                "systemInstruction": {
                    "parts": [{"text": system_prompt}]
                },
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": 200,
                    "topP": 0.8
                }
            }

            url = f"{self.endpoint}?key={self.api_key}"
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        latency = (time.time() - start_time) * 1000
                        logger.info(f"[LLM] Gemini Flash response generated in {latency:.1f}ms: '{text}'")
                        return text.strip()
                logger.error(f"[LLM] Gemini API error: {res.status_code} - {res.text}")
                return self._fallback_response(conversation_history)
        except Exception as e:
            logger.error(f"[LLM] Error during Gemini response generation: {str(e)}")
            return self._fallback_response(conversation_history)

    def _fallback_response(self, conversation_history: List[Dict[str, str]]) -> str:
        turn_count = len(conversation_history)
        last_customer_text = ""
        for msg in reversed(conversation_history):
            if msg.get("role") == "customer":
                last_customer_text = msg.get("text", "")
                break

        # Multilingual conversational smart fallback
        if any(w in last_customer_text for w in ["नमस्ते", "कीमत", "फीचर्स"]):
            return "DIAL-a-DEAL AI आपके सेल्स पाइपलाइन को 24/7 ऑटोमेट करता है। हमारा एंटरप्राइज प्लान ₹8 लाख प्रति वर्ष से शुरू होता है जिसमें कस्टम RAG और फुल CRM इंटीग्रेशन शामिल है। क्या आप 30 मिनट का लाइव डेमो देखना चाहेंगे?"
        elif any(w in last_customer_text for w in ["வணக்கம்", "விலை", "சேல்ஸ்"]):
            return "DIAL-a-DEAL AI உங்கள் வணிகத்திற்கான தானியங்கி விற்பனை பிரதிநிதியாக செயல்படுகிறது. எங்கள் என்டர்பிரைஸ் பிளான் மூலம் உங்கள் விற்பனை 3.8 மடங்கு அதிகரிக்கும். செவ்வாய்க்கிழமை ஒரு நேரடி டெமோ ஏற்பாடு செய்யலாமா?"
        elif any(w in last_customer_text for w in ["నమస్కారం", "ధర", "డెమో"]):
            return "DIAL-a-DEAL AI మీ సేల్స్ కాల్స్‌ను ఆటోమేట్ చేసి, కస్టమర్ల అభ్యంతరాలను తక్షణమే పరిష్కరిస్తుంది. మంగళవారం ఉదయం 10 గంటలకు మీ కోసం ఎగ్జిక్యూటివ్ డెమో బుక్ చేయమంటారా?"
        elif any(w in last_customer_text for w in ["നമസ്കാരം", "ഡെമോ", "വില"]):
            return "DIAL-a-DEAL AI നിങ്ങളുടെ ഔട്ട്ബൗണ്ട് കോളുകൾ സ്വയംഭരണാധികാരത്തോടെ കൈകാര്യം ചെയ്യുന്നു. നിങ്ങൾക്ക് അടുത്ത ആഴ്ച ഒരു സാങ്കേതിക ഡെമോ ബുക്ക് ചെയ്യണമെന്നുണ്ടോ?"
        
        # English fallback turns
        responses = [
            "Hello! I am calling from DIAL-a-DEAL AI. We automate outbound sales calls and qualify leads 24/7 with sub-300ms voice speed. What are your biggest bottlenecks in outbound pipeline today?",
            "Our autonomous agent queries your sales knowledge base in real time to counter pricing or competitor objections instantly, and automatically pushes structured notes into Salesforce or HubSpot.",
            "For 100 seats on our Enterprise Plan, plans start at ₹8 lakhs annually with unlimited minutes, dedicated account management, and 99.9% uptime SLA. Would you like to schedule an executive demonstration for Tuesday at 10 AM IST?"
        ]
        return responses[turn_count % len(responses)]
