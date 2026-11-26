import httpx
from typing import List, Dict
from app.services.llm.base import BaseLLMService
from app.utils.logger import logger

class GptOssLLMService(BaseLLMService):
    """Alternative LLM Provider for open-weights models (e.g. GPT-OSS 20B / Llama 3 via inference endpoints)."""

    def __init__(self, api_key: str = None, endpoint: str = None):
        self.api_key = api_key or ""
        self.endpoint = endpoint or "https://api.groq.com/openai/v1/chat/completions"
        self.model = "llama-3.3-70b-versatile"

    async def generate_response(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        temperature: float = 0.6
    ) -> str:
        if not self.api_key:
            logger.warning("[LLM-Alternative] No API key configured for GPT-OSS provider.")
            return "DIAL-a-DEAL AI helps enterprises automate outbound sales qualification and book high-intent meetings 24/7."

        messages = [{"role": "system", "content": system_prompt}]
        for msg in conversation_history:
            role = "user" if msg["role"] == "customer" else "assistant"
            messages.append({"role": role, "content": msg["text"]})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 200
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(self.endpoint, json=payload, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    return data["choices"][0]["message"]["content"].strip()
                logger.error(f"[LLM-Alternative] Provider error: {res.status_code}")
                return "DIAL-a-DEAL AI automates your sales conversations and closes opportunities into confirmed meetings."
        except Exception as e:
            logger.error(f"[LLM-Alternative] Exception: {str(e)}")
            return "Our AI sales representative is ready to help qualify your leads and schedule appointments."
