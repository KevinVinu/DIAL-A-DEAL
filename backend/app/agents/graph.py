"""
LangGraph StateGraph for the DIAL-a-DEAL AI Fortivex sales agent.

Graph flow:
  START -> intake -> (greet | detect_intent -> retrieve_knowledge -> load_memory -> qualify -> meeting_info -> manage_lead -> decide)
  decide -> (answer_company | suggest_meeting | collect_meeting_details | check_availability | create_event | handle_meeting_change | continue_conversation)
  create_event -> (send_email | generate_response)
  all action nodes -> generate_response -> update_state -> END
"""
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from app.agents import nodes
from app.agents.routing import route_after_create_event, route_after_intake
from app.agents.state import AgentState
from app.config import BACKEND_DIR

ACTION_NODES = [
    "answer_company",
    "suggest_meeting",
    "collect_meeting_details",
    "check_availability",
    "create_event",
    "handle_meeting_change",
    "continue_conversation",
]


def build_workflow() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("intake", nodes.intake)
    g.add_node("greet", nodes.greet)
    g.add_node("detect_intent", nodes.detect_intent)
    g.add_node("retrieve_knowledge", nodes.retrieve_knowledge)
    g.add_node("load_memory", nodes.load_memory)
    g.add_node("qualify", nodes.qualify)
    g.add_node("meeting_info", nodes.meeting_info)
    g.add_node("manage_lead", nodes.manage_lead)
    g.add_node("decide", nodes.decide)

    for name in ACTION_NODES:
        g.add_node(name, getattr(nodes, name))
    g.add_node("send_email", nodes.send_email)
    g.add_node("generate_response", nodes.generate_response)
    g.add_node("update_state", nodes.update_state)

    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", route_after_intake, {
        "greet": "greet",
        "detect_intent": "detect_intent",
    })
    g.add_edge("greet", "generate_response")

    g.add_edge("detect_intent", "retrieve_knowledge")
    g.add_edge("retrieve_knowledge", "load_memory")
    g.add_edge("load_memory", "qualify")
    g.add_edge("qualify", "meeting_info")
    g.add_edge("meeting_info", "manage_lead")
    g.add_edge("manage_lead", "decide")

    g.add_conditional_edges("decide", lambda s: s["next_action"], {
        name: name for name in ACTION_NODES
    })

    for name in ACTION_NODES:
        if name == "create_event":
            g.add_conditional_edges("create_event", route_after_create_event, {
                "send_email": "send_email",
                "generate_response": "generate_response",
            })
        else:
            g.add_edge(name, "generate_response")

    g.add_edge("send_email", "generate_response")
    g.add_edge("generate_response", "update_state")
    g.add_edge("update_state", END)
    return g


_CHECKPOINT_PATH = str(BACKEND_DIR / "langgraph_checkpoints.db")


def compile_graph(checkpointer=None):
    """Compile the StateGraph. Uses in-memory or passed checkpointer."""
    return build_workflow().compile(checkpointer=checkpointer)
