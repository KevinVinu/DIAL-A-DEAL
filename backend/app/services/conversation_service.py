"""
High-level service wrapping the LangGraph StateGraph with persistent SQLite checkpointing
and DB session recovery so interrupted calls resume seamlessly without losing memory.
"""
import asyncio
from typing import Any, Dict, Optional

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.graph import _CHECKPOINT_PATH, build_workflow
from app.agents.state import AgentState, new_state
from app.tools import lead_tools
from app.utils.logger import logger


class AgentConversationService:
    def __init__(self, checkpoint_db_path: str = _CHECKPOINT_PATH):
        self.checkpoint_db_path = checkpoint_db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._graph = None
        self._init_lock = asyncio.Lock()

    async def _ensure_graph(self):
        if self._graph is not None:
            return self._graph
        async with self._init_lock:
            if self._graph is None:
                self._conn = await aiosqlite.connect(self.checkpoint_db_path)
                saver = AsyncSqliteSaver(self._conn)
                await saver.setup()
                self._graph = build_workflow().compile(checkpointer=saver)
                logger.info(f"[AgentService] LangGraph compiled with AsyncSqliteSaver ({self.checkpoint_db_path})")
        return self._graph

    async def close(self):
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            self._graph = None

    async def _seed_or_resume_state(
        self,
        session_id: str,
        language: str,
        customer_id: Optional[str],
        lead_id: Optional[str],
        caller_name: str = "",
        caller_age: Optional[int] = None,
        caller_company: str = "",
    ) -> Dict[str, Any]:
        """Ensure customer/lead rows exist and return initial state delta if thread is new."""
        graph = await self._ensure_graph()
        config = {"configurable": {"thread_id": session_id}}
        snap = await graph.aget_state(config)
        if snap and snap.values and snap.values.get("session_id"):
            # Thread already exists in LangGraph checkpointer; update language if changed
            return {"language": language}

        # Check DB ConversationSession in case checkpoint DB was cleared
        saved = await asyncio.to_thread(lead_tools.load_session, session_id)
        if saved and saved.get("state"):
            st = saved["state"]
            ids = await asyncio.to_thread(
                lead_tools.ensure_customer_and_lead,
                saved.get("customer_id") or customer_id,
                saved.get("lead_id") or lead_id,
                language=language,
                name=caller_name,
                age=caller_age,
                company=caller_company,
            )
            base = new_state(session_id, language, ids["customer_id"], ids["lead_id"])
            base.update({
                "history": saved.get("history", []),
                "customer": st.get("customer", {}),
                "lead": st.get("lead", base["lead"]),
                "meeting": st.get("meeting", base["meeting"]),
                "flags": st.get("flags", {}),
            })
            return base

        # Fresh conversation
        ids = await asyncio.to_thread(
            lead_tools.ensure_customer_and_lead,
            customer_id,
            lead_id,
            language=language,
            name=caller_name,
            age=caller_age,
            company=caller_company,
        )
        base = new_state(session_id, language, ids["customer_id"], ids["lead_id"])
        if caller_name and caller_name not in ("Live Web Prospect", "Website Prospect", "Valued Caller", "Live Prospect"):
            base["customer"]["name"] = caller_name
        if caller_age is not None:
            base["customer"]["age"] = caller_age
        if caller_company and caller_company != "Direct Client":
            base["customer"]["company"] = caller_company
        return base

    async def run_greeting(
        self,
        session_id: str,
        language: str = "en-IN",
        customer_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        caller_name: str = "",
        caller_age: Optional[int] = None,
        caller_company: str = "",
    ) -> Dict[str, Any]:
        graph = await self._ensure_graph()
        delta = await self._seed_or_resume_state(
            session_id, language, customer_id, lead_id, caller_name, caller_age, caller_company
        )
        delta.update({"is_greeting": True, "user_input": ""})
        config = {"configurable": {"thread_id": session_id}}
        out = await graph.ainvoke(delta, config=config)
        return out

    async def run_turn(
        self,
        session_id: str,
        user_input: str,
        language: str = "en-IN",
        customer_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        caller_name: str = "",
        caller_age: Optional[int] = None,
        caller_company: str = "",
    ) -> Dict[str, Any]:
        graph = await self._ensure_graph()
        delta = await self._seed_or_resume_state(
            session_id, language, customer_id, lead_id, caller_name, caller_age, caller_company
        )
        delta.update({"is_greeting": False, "user_input": user_input})
        config = {"configurable": {"thread_id": session_id}}
        out = await graph.ainvoke(delta, config=config)
        return out


# Singleton used by REST chat & VoiceWebSocketHandler
agent_service = AgentConversationService()
