import struct
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.services.stt.sarvam_stt import SarvamSTTService, _wav_duration_seconds, _resolve_language_code
from app.services.llm.groq_llm import GroqLLMService
from app.services.tts.azure_tts import AzureTTSService
from app.services.conversation.context_manager import ConversationContext
from app.services.crm.lead_extractor import LeadExtractor


def _make_wav_bytes(duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    num_samples = int(duration_s * sample_rate)
    data_size = num_samples * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", data_size,
    )
    return header + (b"\x00\x00" * num_samples)


def test_sarvam_wav_duration_and_language_resolution():
    wav = _make_wav_bytes(1.5, 16000)
    assert _wav_duration_seconds(wav) == 1.5
    assert _resolve_language_code("unknown") == "unknown"
    assert _resolve_language_code("auto") == "unknown"
    assert _resolve_language_code("") == "unknown"
    assert _resolve_language_code("en-IN") == "en-IN"
    assert _resolve_language_code("hi") == "hi-IN"
    assert _resolve_language_code("ml-IN") == "ml-IN"


@pytest.mark.asyncio
async def test_sarvam_stt_request_and_auto_detect():
    wav = _make_wav_bytes(1.0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "request_id": "req_123",
        "transcript": "Namaste, Fortivex CRM ka pricing kya hai?",
        "language_code": "hi-IN",
        "language_probability": 0.94,
    }

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)) as mock_post:
        stt = SarvamSTTService(api_key="test_sarvam_key")
        res = await stt.transcribe_with_metadata(wav, language="unknown")

        assert res.provider == "sarvam"
        assert res.model == "saaras:v4"
        assert res.transcript == "Namaste, Fortivex CRM ka pricing kya hai?"
        assert res.detected_language == "hi-IN"
        assert res.language_probability == 0.94
        assert res.audio_duration_s == 1.0

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["headers"]["api-subscription-key"] == "test_sarvam_key"
        assert call_kwargs["data"]["model"] == "saaras:v4"
        assert call_kwargs["data"]["mode"] == "transcribe"
        assert call_kwargs["data"]["language_code"] == "unknown"


@pytest.mark.asyncio
async def test_sarvam_stt_errors_never_fabricate_transcript():
    wav = _make_wav_bytes(1.0)
    stt = SarvamSTTService(api_key="test_sarvam_key")

    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=httpx.TimeoutException("timeout"))):
        assert await stt.transcribe_audio(wav, language="en-IN") == ""

    bad_resp = MagicMock()
    bad_resp.status_code = 500
    bad_resp.text = "Internal error"
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=bad_resp)):
        assert await stt.transcribe_audio(wav, language="ta-IN") == ""

    no_key_stt = SarvamSTTService(api_key="")
    assert await no_key_stt.transcribe_audio(wav, language="ml-IN") == ""


@pytest.mark.asyncio
async def test_multilingual_services():
    languages = ["en-IN", "hi-IN", "ta-IN", "te-IN", "ml-IN"]
    llm = GroqLLMService()
    tts = AzureTTSService()

    for lang in languages:
        context = ConversationContext(call_session_id=f"test_{lang}", language=lang)
        context.add_turn("customer", "Hello, I am interested in Fortivex CRM pricing and booking a demo.")
        response = await llm.generate_response(
            system_prompt=f"Respond naturally in {lang} in under 20 words.",
            conversation_history=context.get_trimmed_history()
        )
        assert len(response) > 0

        audio_bytes = await tts.synthesize_speech(response, language=lang)
        assert audio_bytes is not None
        assert len(audio_bytes) > 0


@pytest.mark.asyncio
async def test_lead_extractor():
    extractor = LeadExtractor()
    sample_turns = [
        {"role": "ai", "text": "Hello! Calling from DIAL-a-DEAL AI."},
        {"role": "customer", "text": "Hi, what is the Fortivex CRM pricing?"},
        {"role": "ai", "text": "Starter is ₹999 per user per month. Would you like a demo?"},
        {"role": "customer", "text": "That sounds great, please book the demonstration."}
    ]
    extracted = await extractor.extract_lead_intelligence(sample_turns, lead_name="Rahul Sharma")
    assert extracted.purchase_intent in ("High", "Medium", "Low")
    assert extracted.lead_temperature in ("Hot", "Warm", "Cold")
    assert len(extracted.conversation_summary) > 0
