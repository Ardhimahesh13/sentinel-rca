import sqlite3
from functools import lru_cache
from typing import Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    finalize_report_node,
    parse_signals_node,
    rca_synthesis_node,
    retrieve_runbooks_node,
    safety_critic_node,
    triage_node,
)
from app.graph.state import IncidentState

MAX_REVISIONS = 2


def route_after_safety(state: IncidentState) -> Literal["rca_synthesis", "finalize"]:
    """Loop back to RCA synthesis if unsafe and under retry limit; otherwise proceed to HITL."""
    if state.get("safety_approved", False):
        return "finalize"
    if state.get("revision_count", 0) >= MAX_REVISIONS:
        return "finalize"
    return "rca_synthesis"


@lru_cache
def get_workflow():
    """Compile and cache the stateful LangGraph workflow with SQLite checkpointing."""
    builder = StateGraph(IncidentState)

    # 1. Register Nodes
    builder.add_node("triage", triage_node)
    builder.add_node("retrieve_runbooks", retrieve_runbooks_node)
    builder.add_node("parse_signals", parse_signals_node)
    builder.add_node("rca_synthesis", rca_synthesis_node)
    builder.add_node("safety_critic", safety_critic_node)
    builder.add_node("finalize", finalize_report_node)

    # 2. Entry -> Triage -> Parallel Fan-Out
    builder.add_edge(START, "triage")
    builder.add_edge("triage", "retrieve_runbooks")
    builder.add_edge("triage", "parse_signals")

    # 3. Fan-In -> RCA Synthesis -> Safety Critic
    builder.add_edge("retrieve_runbooks", "rca_synthesis")
    builder.add_edge("parse_signals", "rca_synthesis")
    builder.add_edge("rca_synthesis", "safety_critic")

    # 4. Conditional Self-Correction Loop
    builder.add_conditional_edges(
        "safety_critic",
        route_after_safety,
        {
            "rca_synthesis": "rca_synthesis",
            "finalize": "finalize",
        },
    )

    builder.add_edge("finalize", END)

    # 5. Persistent SQLite Checkpointer + HITL Interrupt
    conn = sqlite3.connect("checkpoints.db", check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["finalize"],
    )