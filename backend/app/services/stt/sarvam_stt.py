"""
Sarvam AI Saaras V4 Speech-to-Text Service.

Uses the official Sarvam REST API:
  POST https://api.sarvam.ai/speech-to-text
  Header: api-subscription-key: <SARVAM_API_KEY>
  Model: saaras:v4
"""
import json
import ssl
import struct
import time
from typing import Optional, Tuple

import httpx

try:
    import truststore
    _SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except Exception:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

from app.config import settings
from app.services.stt.base import BaseSTTService, STTResult
from app.utils.logger import logger

SUPPORTED_BCP47 = {"en-IN", "hi-IN", "ta-IN", "te-IN", "ml-IN"}
SHORT_TO_BCP47 = {
    "en": "en-IN",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "ml": "ml-IN",
}
FORTIVEX_KEYTERMS = [
    "Fortivex",
    "Fortivex AI",
    "Fortivex CRM",
    "FAMS",
    "Empowers Academy",
    "Medivex AI",
    "DIAL-a-DEAL",
]


def _detect_audio_format(audio_bytes: bytes) -> Tuple[str, str]:
    if audio_bytes.startswith(b"RIFF") and len(audio_bytes) >= 12 and audio_bytes[8:12] == b"WAVE":
        return "audio.wav", "audio/wav"
    if audio_bytes.startswith(b"ID3") or audio_bytes[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio.mp3", "audio/mpeg"
    if audio_bytes.startswith(b"fLaC"):
        return "audio.flac", "audio/flac"
    if audio_bytes.startswith(b"OggS"):
        return "audio.ogg", "audio/ogg"
    if audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio.webm", "audio/webm"
    return "audio.wav", "audio/wav"


def _wav_duration_seconds(audio_bytes: bytes) -> Optional[float]:
    """Compute exact duration in seconds from a RIFF WAVE header, if valid."""
    if not (audio_bytes.startswith(b"RIFF") and len(audio_bytes) >= 44 and audio_bytes[8:12] == b"WAVE"):
        return None
    try:
        byte_rate = struct.unpack_from("<I", audio_bytes, 28)[0]
        if byte_rate <= 0:
            return None
        payload_bytes = max(0, len(audio_bytes) - 44)
        return round(payload_bytes / float(byte_rate), 3)
    except Exception:
        return None


def _resolve_language_code(language: Optional[str]) -> str:
    """
    Use the caller's selected BCP-47 language when explicitly provided;
    otherwise pass 'unknown' to enable Sarvam Saaras V4 automatic language detection.
    """
    lang = (language or "").strip()
    if not lang or lang.lower() in ("auto", "unknown"):
        return "unknown"
    if lang in SUPPORTED_BCP47:
        return lang
    short = lang.split("-")[0].lower()
    return SHORT_TO_BCP47.get(short, "unknown")


class SarvamSTTService(BaseSTTService):
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.SARVAM_API_KEY
        self.endpoint = settings.SARVAM_STT_URL
        self.model = settings.SARVAM_STT_MODEL
        self.mode = settings.SARVAM_STT_MODE
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0, verify=_SSL_CONTEXT)
        return self._client

    async def transcribe_audio(self, audio_bytes: bytes, language: str = "unknown") -> str:
        res = await self.transcribe_with_metadata(audio_bytes, language=language)
        return res.transcript

    async def transcribe_with_metadata(self, audio_bytes: bytes, language: str = "unknown") -> STTResult:
        start_time = time.time()
        audio_duration_s = _wav_duration_seconds(audio_bytes)

        if not audio_bytes or len(audio_bytes) < 64:
            logger.debug("[STT] Skipped empty/tiny audio payload (%d bytes)", len(audio_bytes or b""))
            return STTResult(transcript="", audio_duration_s=audio_duration_s, provider="sarvam", model=self.model)

        if not self.api_key:
            logger.error("[STT] provider=sarvam model=%s error='SARVAM_API_KEY is not configured'", self.model)
            return STTResult(transcript="", audio_duration_s=audio_duration_s, provider="sarvam", model=self.model)

        req_lang = _resolve_language_code(language)
        file_name, mime_type = _detect_audio_format(audio_bytes)

        files = {"file": (file_name, audio_bytes, mime_type)}
        data = {
            "model": self.model,
            "mode": self.mode,
            "language_code": req_lang,
            "keyterms": json.dumps(FORTIVEX_KEYTERMS),
        }
        headers = {"api-subscription-key": self.api_key}

        try:
            client = self._get_client()
            try:
                response = await client.post(self.endpoint, headers=headers, data=data, files=files)
            except (httpx.ConnectError, ssl.SSLError) as tls_err:
                logger.warning("[STT] Transient connection/TLS error (%s); retrying once...", tls_err)
                await client.aclose()
                self._client = None
                response = await self._get_client().post(self.endpoint, headers=headers, data=data, files=files)
            latency_ms = (time.time() - start_time) * 1000.0

            if response.status_code == 200:
                payload = response.json()
                transcript = (payload.get("transcript") or "").strip()
                detected_lang = payload.get("language_code") or (None if req_lang == "unknown" else req_lang)
                lang_prob = payload.get("language_probability")
                request_id = payload.get("request_id")

                logger.info(
                    "[STT] provider=sarvam model=%s req_lang=%s detected_lang=%s prob=%s "
                    "duration_s=%s latency_ms=%.1f transcript_len=%d request_id=%s",
                    self.model,
                    req_lang,
                    detected_lang,
                    f"{lang_prob:.2f}" if isinstance(lang_prob, (int, float)) else "n/a",
                    f"{audio_duration_s:.2f}" if audio_duration_s is not None else "n/a",
                    latency_ms,
                    len(transcript),
                    request_id,
                )
                return STTResult(
                    transcript=transcript,
                    detected_language=detected_lang,
                    language_probability=lang_prob,
                    latency_ms=latency_ms,
                    audio_duration_s=audio_duration_s,
                    provider="sarvam",
                    model=self.model,
                    request_id=request_id,
                )

            logger.error(
                "[STT] provider=sarvam model=%s http_status=%d latency_ms=%.1f duration_s=%s error=%s",
                self.model,
                response.status_code,
                latency_ms,
                f"{audio_duration_s:.2f}" if audio_duration_s is not None else "n/a",
                response.text[:300],
            )
            return STTResult(
                transcript="",
                latency_ms=latency_ms,
                audio_duration_s=audio_duration_s,
                provider="sarvam",
                model=self.model,
            )

        except httpx.TimeoutException:
            latency_ms = (time.time() - start_time) * 1000.0
            logger.error(
                "[STT] provider=sarvam model=%s timeout_ms=%.1f duration_s=%s",
                self.model,
                latency_ms,
                f"{audio_duration_s:.2f}" if audio_duration_s is not None else "n/a",
            )
            return STTResult(
                transcript="",
                latency_ms=latency_ms,
                audio_duration_s=audio_duration_s,
                provider="sarvam",
                model=self.model,
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000.0
            logger.error("[STT] provider=sarvam model=%s exception=%s", self.model, str(e))
            return STTResult(
                transcript="",
                latency_ms=latency_ms,
                audio_duration_s=audio_duration_s,
                provider="sarvam",
                model=self.model,
            )
