"""Chat endpoint exposing the LangGraph agent directly over REST for testing and text-mode clients."""
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.conversation_service import agent_service
from app.tools import lead_tools

router = APIRouter(prefix="/api/v1/chat", tags=["Chat Agent"])


class ChatTurnRequest(BaseModel):
    session_id: str
    message: str = ""
    language: str = "en-IN"
    is_greeting: bool = False
    caller_name: str = ""
    caller_age: Optional[int] = None
    caller_company: str = ""


class ChatTurnResponse(BaseModel):
    session_id: str
    response: str
    intent: str = ""
    next_action: str = ""
    grounded: bool = False
    retrieved_ids: list = []
    customer: Dict[str, Any] = {}
    lead: Dict[str, Any] = {}
    meeting: Dict[str, Any] = {}
    tool_log: list = []


@router.post("/turn", response_model=ChatTurnResponse)
async def chat_turn(req: ChatTurnRequest):
    if req.is_greeting:
        out = await agent_service.run_greeting(
            session_id=req.session_id,
            language=req.language,
            caller_name=req.caller_name,
            caller_age=req.caller_age,
            caller_company=req.caller_company,
        )
    else:
        if not req.message.strip():
            raise HTTPException(status_code=400, detail="message is required when is_greeting=false")
        out = await agent_service.run_turn(
            session_id=req.session_id,
            user_input=req.message,
            language=req.language,
            caller_name=req.caller_name,
            caller_age=req.caller_age,
            caller_company=req.caller_company,
        )

    return ChatTurnResponse(
        session_id=req.session_id,
        response=out.get("response", ""),
        intent=out.get("intent", ""),
        next_action=out.get("next_action", ""),
        grounded=bool(out.get("grounded")),
        retrieved_ids=[d.get("id") for d in (out.get("retrieved") or [])],
        customer=out.get("customer", {}),
        lead=out.get("lead", {}),
        meeting=out.get("meeting", {}),
        tool_log=out.get("tool_log", []),
    )


@router.get("/session/{session_id}")
def get_session(session_id: str):
    saved = lead_tools.load_session(session_id)
    if not saved:
        raise HTTPException(status_code=404, detail="Session not found")
    return saved
