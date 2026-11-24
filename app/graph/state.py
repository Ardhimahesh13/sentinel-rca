import operator
from typing import Annotated, Any, Literal, TypedDict

SeverityLevel = Literal["P1", "P2", "P3", "P4"]
IncidentDomain = Literal["database", "network", "auth", "application", "general"]


class IncidentState(TypedDict, total=False):
    # --- Input ---
    incident_id: str
    raw_log: str

    # --- Node 1: Triage Router (8B) ---
    severity: SeverityLevel
    domain: IncidentDomain
    triage_summary: str

    # --- Node 2A & 2B: Parallel Investigation ---
    retrieved_runbooks: list[dict[str, Any]]
    parsed_signals: dict[str, Any]

    # --- Node 3: RCA & Remediation Agent  ---
    root_cause: str
    remediation_steps: list[str]
    proposed_commands: list[str]

    # --- Node 4: Safety Verification Critic ---
    safety_approved: bool
    safety_feedback: str
    revision_count: int

    # --- Node 5: Human-in-the-Loop (HITL) & Finalization ---
    human_approved: bool | None
    human_feedback: str
    final_report: str

    # --- Execution Audit Trail (Parallel-Safe Reducer) ---
    agent_trace: Annotated[list[str], operator.add]