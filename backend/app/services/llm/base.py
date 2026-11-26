from abc import ABC, abstractmethod
from typing import List, Dict


class LLMError(Exception):
    """Raised when the LLM provider cannot produce a usable completion."""


class BaseLLMService(ABC):
    @abstractmethod
    async def generate_response(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        temperature: float = 0.6
    ) -> str:
        """Generate conversational response based on prompt and conversation history."""
        pass

    async def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        json_mode: bool = False,
        max_tokens: int = 300,
        temperature: float = 0.3,
    ) -> str:
        """Raw chat completion over OpenAI-style messages (used by the LangGraph agent). Raises LLMError."""
        raise NotImplementedError
