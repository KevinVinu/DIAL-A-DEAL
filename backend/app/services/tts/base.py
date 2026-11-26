from abc import ABC, abstractmethod

class BaseTTSService(ABC):
    @abstractmethod
    async def synthesize_speech(self, text: str, language: str = "en-IN") -> bytes:
        """Synthesize text to audio bytes (MP3 / WAV) for streaming to browser."""
        pass
