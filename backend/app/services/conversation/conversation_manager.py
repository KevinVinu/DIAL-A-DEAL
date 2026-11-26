from typing import Optional, Dict, Any
from app.services.stt.sarvam_stt import SarvamSTTService, SUPPORTED_BCP47
from app.services.tts.azure_tts import AzureTTSService
from app.services.conversation.context_manager import ConversationContext
from app.services.conversation_service import agent_service, AgentConversationService
from app.utils.logger import logger


class ConversationManager:
    """
    Orchestrates the end-to-end voice loop:
      Customer Microphone -> Sarvam Saaras V4 STT -> LangGraph Agent (RAG + ChromaDB + DB + Calendar + Gmail) -> Azure Speech TTS
    """

    def __init__(
        self,
        stt_service: Optional[SarvamSTTService] = None,
        tts_service: Optional[AzureTTSService] = None,
        conv_agent: Optional[AgentConversationService] = None,
    ):
        self.stt = stt_service or SarvamSTTService()
        self.tts = tts_service or AzureTTSService()
        self.agent = conv_agent or agent_service

    async def process_customer_audio(
        self,
        context: ConversationContext,
        audio_bytes: bytes,
        *,
        customer_id: Optional[str] = None,
        lead_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        1. Transcribe customer speech (Sarvam Saaras V4)
        2. Run LangGraph agent turn (Intent -> RAG -> Memory -> Qualification -> Lead DB -> Tools -> Spoken Reply)
        3. Synthesize speech (Azure TTS)
        Returns: { 'customer_text', 'ai_text', 'audio_bytes', 'agent_state', 'detected_language' }
        """
        stt_res = await self.stt.transcribe_with_metadata(audio_bytes, language=context.language)
        customer_text = (stt_res.transcript or "").strip()
        if not customer_text:
            return {
                "customer_text": "",
                "ai_text": "",
                "audio_bytes": None,
                "agent_state": None,
                "detected_language": stt_res.detected_language,
            }

        # When auto-detect is active ('unknown'/'auto'), route LangGraph + TTS to the detected supported language
        active_lang = context.language
        if (not active_lang or active_lang.lower() in ("auto", "unknown")) and stt_res.detected_language in SUPPORTED_BCP47:
            active_lang = stt_res.detected_language
        elif active_lang.lower() in ("auto", "unknown"):
            active_lang = "en-IN"

        return await self.process_customer_text(
            context,
            customer_text,
            customer_id=customer_id,
            lead_id=lead_id,
            active_lang=active_lang,
            detected_language=stt_res.detected_language or active_lang,
        )

    async def process_customer_text(
        self,
        context: ConversationContext,
        customer_text: str,
        *,
        customer_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        active_lang: Optional[str] = None,
        detected_language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a typed/transcribed customer turn through LangGraph + Azure TTS."""
        if not active_lang:
            active_lang = "en-IN" if (not context.language or context.language.lower() in ("auto", "unknown")) else context.language

        context.add_turn("customer", customer_text)

        agent_state = await self.agent.run_turn(
            session_id=context.call_session_id,
            user_input=customer_text,
            language=active_lang,
            customer_id=customer_id,
            lead_id=lead_id,
            caller_name=context.lead_name,
        )
        ai_text = agent_state.get("response", "")
        context.add_turn("ai", ai_text)

        tts_audio = await self.tts.synthesize_speech(ai_text, language=active_lang)
        return {
            "customer_text": customer_text,
            "ai_text": ai_text,
            "audio_bytes": tts_audio,
            "agent_state": agent_state,
            "detected_language": detected_language or active_lang,
        }

    async def generate_greeting(
        self,
        context: ConversationContext,
        *,
        customer_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        caller_age: Optional[int] = None,
        caller_company: str = "",
    ) -> Dict[str, Any]:
        """Generates the opening greeting via the LangGraph agent and synthesizes it via Azure TTS."""
        greeting_lang = "en-IN" if (not context.language or context.language.lower() in ("auto", "unknown")) else context.language
        agent_state = await self.agent.run_greeting(
            session_id=context.call_session_id,
            language=greeting_lang,
            customer_id=customer_id,
            lead_id=lead_id,
            caller_name=context.lead_name,
            caller_age=caller_age,
            caller_company=caller_company,
        )
        ai_text = agent_state.get("response", "")
        context.add_turn("ai", ai_text)

        tts_audio = await self.tts.synthesize_speech(ai_text, language=greeting_lang)
        return {
            "ai_text": ai_text,
            "audio_bytes": tts_audio,
            "agent_state": agent_state,
        }
