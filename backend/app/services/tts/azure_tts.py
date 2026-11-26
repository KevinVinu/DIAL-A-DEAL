import time
import httpx
from xml.sax.saxutils import escape
from app.services.tts.base import BaseTTSService
from app.config import settings
from app.utils.logger import logger

class AzureTTSService(BaseTTSService):
    def __init__(self, key: str = None, region: str = None):
        self.key = key or settings.AZURE_SPEECH_KEY
        self.region = region or settings.AZURE_SPEECH_REGION
        self.endpoint = f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1"

    async def synthesize_speech(self, text: str, language: str = "en-IN") -> bytes:
        start_time = time.time()
        
        # Select appropriate Neural voice
        voice_name = settings.AZURE_VOICES.get(language, settings.AZURE_VOICES["en-IN"])
        
        # Check if Azure credentials exist
        if not self.key or not self.region:
            logger.warning("[TTS] AZURE_SPEECH_KEY or AZURE_SPEECH_REGION not set. Generating synthetic audio response.")
            return self._generate_fallback_audio()

        # Build standard SSML
        clean_text = escape(text)
        ssml = f"""<speak version='1.0' xml:lang='{language}'>
            <voice xml:lang='{language}' xml:gender='Female' name='{voice_name}'>
                <prosody rate='0%'>{clean_text}</prosody>
            </voice>
        </speak>"""

        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-16khz-32kbitrate-mono-mp3",
            "User-Agent": "DIAL-a-DEAL-AI"
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(self.endpoint, headers=headers, content=ssml.encode("utf-8"))
                if res.status_code == 200:
                    latency = (time.time() - start_time) * 1000
                    audio_bytes = res.content
                    logger.info(f"[TTS] Azure Speech synthesized {len(audio_bytes)} bytes in {latency:.1f}ms for voice '{voice_name}'")
                    return audio_bytes
                else:
                    logger.error(f"[TTS] Azure Speech returned error {res.status_code}: {res.text}")
                    return self._generate_fallback_audio()
        except Exception as e:
            logger.error(f"[TTS] Azure Speech error: {str(e)}")
            return self._generate_fallback_audio()

    def _generate_fallback_audio(self) -> bytes:
        """Returns a valid minimal MP3 frame header or silence so browser Audio player never crashes."""
        # Standard silent/short tone mp3 frame
        return b'\xff\xfb\x90d\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00' * 50
