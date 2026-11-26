from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class STTResult:
    transcript: str
    detected_language: Optional[str] = None
    language_probability: Optional[float] = None
    latency_ms: float = 0.0
    audio_duration_s: Optional[float] = None
    provider: str = "sarvam"
    model: str = "saaras:v4"
    request_id: Optional[str] = None


class BaseSTTService(ABC):
    @abstractmethod
    async def transcribe_audio(self, audio_bytes: bytes, language: str = "en-IN") -> str:
        """Transcribe raw audio bytes into text string, preserving spoken language."""
        pass

    async def transcribe_with_metadata(self, audio_bytes: bytes, language: str = "unknown") -> STTResult:
        """Transcribe audio and return structured diagnostics + detected language."""
        text = await self.transcribe_audio(audio_bytes, language=language)
        return STTResult(transcript=text)
