"""
Groq LLM Service — primary LLM provider for DIAL-a-DEAL AI.
Uses the Groq OpenAI-compatible API with openai/gpt-oss-20b (or llama fallback).
Reuses GROQ_API_KEY already used by Whisper STT.
"""
import ssl
import time
import httpx
from typing import List, Dict
from app.services.llm.base import BaseLLMService, LLMError
from app.config import settings
from app.utils.logger import logger

try:
    import truststore
    _SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except Exception:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

# Models are configurable via GROQ_LLM_MODEL / GROQ_LLM_FALLBACK_MODEL (see config.py)
PRIMARY_MODEL = settings.GROQ_LLM_MODEL
FALLBACK_MODEL = settings.GROQ_LLM_FALLBACK_MODEL


class GroqLLMService(BaseLLMService):
    """
    Groq-based LLM provider using the OpenAI-compatible chat completions API.
    Maintains full conversation history and multilingual sales-agent context.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = PRIMARY_MODEL

    @staticmethod
    def _payload(model: str, messages, json_mode: bool, max_tokens: int, temperature: float) -> dict:
        p = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if model.startswith("openai/gpt-oss"):
            # Reasoning models: keep thinking minimal for voice latency and don't spend the token budget on it.
            p["reasoning_effort"] = "low"
            p["include_reasoning"] = False
        elif model.startswith("qwen/"):
            p["reasoning_effort"] = "none"
        if json_mode:
            p["response_format"] = {"type": "json_object"}
        return p

    async def complete(self, messages, *, json_mode: bool = False, max_tokens: int = 300,
                       temperature: float = 0.3) -> str:
        if not self.api_key:
            raise LLMError("GROQ_API_KEY is not configured")
        import asyncio
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        candidates = list(dict.fromkeys([self.model, FALLBACK_MODEL, "qwen/qwen3.8-27b"]))
        last_err = ""
        async with httpx.AsyncClient(timeout=25.0, verify=_SSL_CONTEXT) as client:
            for model in candidates:
                start = time.time()
                try:
                    res = await client.post(GROQ_CHAT_URL, headers=headers,
                                            json=self._payload(model, messages, json_mode, max_tokens, temperature))
                except (httpx.HTTPError, ssl.SSLError) as e:
                    last_err = f"{model}: network error {e}"
                    logger.warning(f"[LLM-Groq] {last_err}")
                    await asyncio.sleep(0.3)
                    continue
                if res.status_code == 200:
                    choices = res.json().get("choices") or []
                    text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
                    if text:
                        logger.info(f"[LLM-Groq] {model} {(time.time() - start) * 1000:.0f}ms")
                        return text
                    last_err = f"{model}: empty completion"
                elif res.status_code == 429:
                    last_err = f"{model}: HTTP 429 {res.text[:160]}"
                    logger.warning(f"[LLM-Groq] {last_err} — rotating model")
                    await asyncio.sleep(0.5)
                    continue
                else:
                    last_err = f"{model}: HTTP {res.status_code} {res.text[:200]}"
                logger.warning(f"[LLM-Groq] {last_err}")
        raise LLMError(last_err or "LLM request failed")

    async def generate_response(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        temperature: float = 0.6,
    ) -> str:
        start = time.time()

        if not self.api_key:
            logger.warning("[LLM-Groq] GROQ_API_KEY not set — using fallback response.")
            return self._fallback_response(conversation_history)

        # Build OpenAI-compatible messages array
        messages = [{"role": "system", "content": system_prompt}]
        for msg in conversation_history:
            role = "user" if msg.get("role") == "customer" else "assistant"
            messages.append({"role": role, "content": msg.get("text", "")})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 220,          # keep responses concise & speakable
            "top_p": 0.9,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                res = await client.post(GROQ_CHAT_URL, json=payload, headers=headers)

                if res.status_code == 200:
                    data = res.json()
                    choices = data.get("choices", [])
                    if choices:
                        text = choices[0].get("message", {}).get("content", "").strip()
                        if text and len(text) > 1:
                            ms = (time.time() - start) * 1000
                            logger.info(f"[LLM-Groq] {self.model} → {ms:.0f}ms | '{text[:80]}...'")
                            return text
                    return self._fallback_response(conversation_history)

                # Try fallback model on model-not-found or quota errors
                if res.status_code in (404, 429):
                    logger.warning(
                        f"[LLM-Groq] {self.model} returned {res.status_code}, "
                        f"retrying with {FALLBACK_MODEL}"
                    )
                    payload["model"] = FALLBACK_MODEL
                    res2 = await client.post(GROQ_CHAT_URL, json=payload, headers=headers)
                    if res2.status_code == 200:
                        text = res2.json()["choices"][0]["message"]["content"].strip()
                        logger.info(f"[LLM-Groq] Fallback {FALLBACK_MODEL} responded OK.")
                        return text

                logger.error(f"[LLM-Groq] API error {res.status_code}: {res.text[:300]}")
                return self._fallback_response(conversation_history)

            except httpx.TimeoutException:
                logger.error("[LLM-Groq] Request timed out.")
                return self._fallback_response(conversation_history)
            except Exception as e:
                logger.error(f"[LLM-Groq] Unexpected error: {e}")
                return self._fallback_response(conversation_history)

    def _fallback_response(self, conversation_history: List[Dict[str, str]]) -> str:
        """Graceful spoken fallback when network or API experiences momentary jitter."""
        last = ""
        for msg in reversed(conversation_history):
            if msg.get("role") == "customer":
                last = msg.get("text", "").lower()
                break

        if any(w in last for w in ["नमस्ते", "namaste", "kya", "haan"]):
            return "माफ़ कीजिए, क्या आप एक बार फिर बोल सकते हैं? मैं आपकी बात ठीक से समझना चाहता हूँ।"
        elif any(w in last for w in ["வணக்கம்", "vanakkam"]):
            return "மன்னிக்கவும், உங்கள் குரல் தெளிவாகக் கேட்கவில்லை. தயவுசெய்து மீண்டும் கூற முடியுமா?"
        elif any(w in last for w in ["నమస్కారం", "namaskaram"]):
            return "క్షమించండి, మీ వాయిస్ స్పష్టంగా రాలేదు. దయచేసి మళ్ళీ చెప్పగలరా?"
        elif any(w in last for w in ["നമസ്കാരം"]):
            return "ക്ഷമിക്കണം, ശബ്ദം വ്യക്തമായി കേട്ടില്ല. ദയവായി ഒരിക്കൽ കൂടി പറയാമോ?"

        return "I caught that, but the line broke up slightly. Could you please repeat that? I want to make sure I answer your question accurately."
