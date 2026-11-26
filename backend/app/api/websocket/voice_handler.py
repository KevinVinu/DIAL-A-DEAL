import json
import base64
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.database.connection import SessionLocal
from app.database.repositories import CallRepository, CustomerRepository, LeadRepository
from app.services.conversation.conversation_manager import ConversationManager
from app.services.conversation.context_manager import ConversationContext
from app.services.audio.audio_processor import AudioProcessor
from app.services.audio.interruption_handler import InterruptionHandler
from app.services.crm.lead_extractor import LeadExtractor
from app.utils.logger import logger

class VoiceWebSocketHandler:
    def __init__(self):
        self.conv_manager = ConversationManager()
        self.lead_extractor = LeadExtractor()

    async def handle_call(self, websocket: WebSocket, call_session_id: str):
        await websocket.accept()
        logger.info(f"[WS] WebSocket connected for session: {call_session_id}")

        db: Session = SessionLocal()
        interruption_handler = InterruptionHandler()

        # Wait for call_init from frontend (caller profile + language)
        init_language = "en-IN"
        init_caller_name = ""
        init_caller_age = None
        init_caller_company = None
        init_caller_phone = None

        try:
            raw_init = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            init_payload = json.loads(raw_init)
            if init_payload.get("type") == "call_init":
                init_language = init_payload.get("language", "en-IN")
                init_caller_name = (init_payload.get("caller_name") or init_payload.get("prospect_name") or "").strip()
                age_val = init_payload.get("caller_age")
                if age_val:
                    try:
                        init_caller_age = int(age_val)
                    except (ValueError, TypeError):
                        pass
                init_caller_company = (init_payload.get("caller_company") or init_payload.get("company") or "").strip() or None
                init_caller_phone = (init_payload.get("caller_phone") or "").strip() or None
                logger.info(f"[WS] call_init received: name='{init_caller_name}', age={init_caller_age}, company='{init_caller_company}', lang={init_language}")
        except asyncio.TimeoutError:
            logger.warning("[WS] No call_init received within 10s, using defaults.")
        except Exception as e:
            logger.warning(f"[WS] call_init parse error: {e}")

        display_name = init_caller_name if init_caller_name else "Valued Caller"

        # Initialize Customer & Lead records in DB
        from app.database.models import Customer, Lead
        customer = Customer(
            full_name=init_caller_name if init_caller_name else "Live Web Prospect",
            age=init_caller_age,
            company=init_caller_company,
            phone_number=init_caller_phone,
            preferred_language=init_language
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

        lead = Lead(
            customer_id=customer.id,
            source="Live Voice Call",
            lead_status="In Progress"
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)

        call = CallRepository.create_call(
            db,
            call_session_id=call_session_id,
            customer_id=customer.id,
            lead_id=lead.id,
            language=init_language,
        )

        language = init_language
        context = ConversationContext(
            call_session_id=call_session_id,
            language=language,
            lead_name=display_name,
        )

        try:
            # 1. Send call_started event & Greeting
            await websocket.send_json({
                "type": "call_started",
                "call_id": call.id,
                "call_session_id": call_session_id,
                "language": language,
                "status": "connected"
            })

            # Generate initial greeting from LangGraph sales agent
            greeting_result = await self.conv_manager.generate_greeting(
                context,
                customer_id=customer.id,
                lead_id=lead.id,
                caller_age=init_caller_age,
                caller_company=init_caller_company or "",
            )
            ai_text = greeting_result["ai_text"]
            audio_bytes = greeting_result["audio_bytes"]

            # Save AI turn in DB
            CallRepository.add_message(db, call_id=call.id, speaker="ai", message=ai_text, language=language)

            # Send AI response text & audio chunk to browser
            await websocket.send_json({
                "type": "ai_response",
                "text": ai_text,
                "state": "speaking"
            })

            if audio_bytes:
                b64_audio = AudioProcessor.encode_base64_chunk(audio_bytes)
                interruption_handler.start_speaking()
                await websocket.send_json({
                    "type": "ai_audio",
                    "audio": b64_audio,
                    "format": "mp3"
                })

            # 2. Main incoming event listening loop
            while True:
                data = await websocket.receive_text()
                try:
                    payload = json.loads(data)
                except Exception:
                    continue

                event_type = payload.get("type")

                # Customer Speech Audio Chunk
                if event_type == "audio_chunk":
                    raw_b64 = payload.get("audio", "")
                    if not raw_b64:
                        continue
                    
                    audio_chunk = AudioProcessor.decode_base64_chunk(raw_b64)
                    if not audio_chunk:
                        continue

                    # Process customer speech turn through LangGraph voice pipeline
                    async def process_turn():
                        try:
                            turn_result = await self.conv_manager.process_customer_audio(
                                context=context,
                                audio_bytes=audio_chunk,
                                customer_id=customer.id,
                                lead_id=lead.id,
                            )

                            customer_text = turn_result.get("customer_text", "").strip()
                            ai_resp_text = turn_result.get("ai_text", "")
                            resp_audio = turn_result.get("audio_bytes")

                            # Only proceed if actual speech was recognized
                            if customer_text and len(customer_text) > 1:
                                was_interrupted = interruption_handler.handle_customer_speech_detected()
                                if was_interrupted:
                                    await websocket.send_json({
                                        "type": "interruption",
                                        "message": "AI speech playback interrupted by customer speech."
                                    })

                                CallRepository.add_message(db, call_id=call.id, speaker="customer", message=customer_text, language=language)
                                await websocket.send_json({
                                    "type": "transcript_customer",
                                    "text": customer_text,
                                    "sender": "customer"
                                })

                                if ai_resp_text:
                                    CallRepository.add_message(db, call_id=call.id, speaker="ai", message=ai_resp_text, language=language)
                                    await websocket.send_json({
                                        "type": "ai_response",
                                        "text": ai_resp_text,
                                        "state": "speaking"
                                    })

                                # If the agent is now asking for the caller's email to schedule a meeting, show the inline email box
                                ag_state = turn_result.get("agent_state") or {}
                                from app.agents.routing import missing_meeting_fields
                                if ag_state.get("next_action") == "collect_meeting_details" and "email" in missing_meeting_fields(ag_state):
                                    await websocket.send_json({
                                        "type": "request_email_input",
                                        "prompt": "Enter your email address for the calendar invite & confirmation"
                                    })

                                if resp_audio:
                                    b64_out = AudioProcessor.encode_base64_chunk(resp_audio)
                                    interruption_handler.start_speaking()
                                    await websocket.send_json({
                                        "type": "ai_audio",
                                        "audio": b64_out,
                                        "format": "mp3"
                                    })
                                else:
                                    interruption_handler.stop_speaking()
                        except (WebSocketDisconnect, RuntimeError):
                            logger.debug("[WS] Turn finished after WebSocket closed; skipping send.")

                    # Schedule turn processing
                    task = asyncio.create_task(process_turn())
                    interruption_handler.current_task = task

                # Typed email / text confirmation from browser UI
                elif event_type in ("email_input", "text_input"):
                    typed = (payload.get("email") or payload.get("text") or "").strip()
                    if not typed:
                        continue
                    customer_msg = f"My email address is {typed}" if event_type == "email_input" else typed

                    async def process_typed_turn():
                        try:
                            turn_result = await self.conv_manager.process_customer_text(
                                context=context,
                                customer_text=customer_msg,
                                customer_id=customer.id,
                                lead_id=lead.id,
                            )
                            ai_resp_text = turn_result.get("ai_text", "")
                            resp_audio = turn_result.get("audio_bytes")

                            CallRepository.add_message(db, call_id=call.id, speaker="customer", message=customer_msg, language=language)
                            await websocket.send_json({
                                "type": "transcript_customer",
                                "text": customer_msg,
                                "sender": "customer"
                            })
                            if ai_resp_text:
                                CallRepository.add_message(db, call_id=call.id, speaker="ai", message=ai_resp_text, language=language)
                                await websocket.send_json({
                                    "type": "ai_response",
                                    "text": ai_resp_text,
                                    "state": "speaking"
                                })
                            if resp_audio:
                                b64_out = AudioProcessor.encode_base64_chunk(resp_audio)
                                interruption_handler.start_speaking()
                                await websocket.send_json({
                                    "type": "ai_audio",
                                    "audio": b64_out,
                                    "format": "mp3"
                                })
                        except (WebSocketDisconnect, RuntimeError):
                            logger.debug("[WS] Typed turn finished after WebSocket closed.")

                    task = asyncio.create_task(process_typed_turn())
                    interruption_handler.current_task = task

                # Audio playback finished on browser
                elif event_type == "playback_finished":
                    interruption_handler.stop_speaking()
                    await websocket.send_json({"type": "status_update", "state": "listening"})

                # Mute/Unmute toggle from user
                elif event_type == "mute":
                    is_muted = payload.get("is_muted", False)
                    logger.info(f"[WS] User microphone muted state: {is_muted}")

                # Call ended by user
                elif event_type == "call_ended":
                    logger.info(f"[WS] Call ended event received for session: {call_session_id}")
                    break

        except WebSocketDisconnect:
            logger.info(f"[WS] WebSocket disconnected for session: {call_session_id}")
        except Exception as e:
            logger.error(f"[WS] Unexpected WebSocket error: {str(e)}")
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass
        finally:
            # 3. Post-call Finalization & CRM Lead Extraction
            try:
                # Extract structured intelligence from conversation turns
                extracted = await self.lead_extractor.extract_lead_intelligence(
                    transcript_turns=context.history,
                    lead_name=context.lead_name
                )

                # Persist extracted caller details into Customer & Lead records in DB
                if extracted.caller_name and (not customer.full_name or customer.full_name == "Live Web Prospect"):
                    customer.full_name = extracted.caller_name
                if extracted.caller_age and not customer.age:
                    customer.age = extracted.caller_age
                if extracted.caller_company and not customer.company:
                    customer.company = extracted.caller_company

                lead.interest_level = extracted.lead_temperature
                lead.purchase_intent = extracted.purchase_intent
                lead.budget = extracted.budget
                lead.notes = extracted.conversation_summary
                lead.lead_status = "Demo Booked" if extracted.callback_requested else "Qualified"
                if extracted.products_of_interest:
                    lead.interested_products = ", ".join(extracted.products_of_interest)
                db.commit()

                # End call record in database
                CallRepository.end_call(
                    db,
                    call_id=call.id,
                    outcome="Demo Booked" if extracted.callback_requested else "Completed",
                    summary=extracted.conversation_summary,
                    extracted_data=extracted.model_dump()
                )

                # Send final summary to client if socket still open
                try:
                    await websocket.send_json({
                        "type": "call_ended",
                        "summary": {
                            "appointment_booked": extracted.callback_requested,
                            "note": extracted.conversation_summary or "Call completed.",
                            "lead_temperature": extracted.lead_temperature,
                            "purchase_intent": extracted.purchase_intent,
                            "suggested_next_action": extracted.suggested_next_action,
                        }
                    })
                except Exception:
                    pass

            except Exception as final_err:
                logger.error(f"[WS] Error during call finalization: {str(final_err)}")
            finally:
                db.close()
