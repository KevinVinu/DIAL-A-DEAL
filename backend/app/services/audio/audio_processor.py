import base64
from typing import Optional
from app.utils.logger import logger

class AudioProcessor:
    @staticmethod
    def decode_base64_chunk(b64_string: str) -> Optional[bytes]:
        try:
            return base64.b64decode(b64_string)
        except Exception as e:
            logger.error(f"[AudioProcessor] Failed to decode base64 chunk: {str(e)}")
            return None

    @staticmethod
    def encode_base64_chunk(audio_bytes: bytes) -> str:
        return base64.b64encode(audio_bytes).decode("utf-8")
