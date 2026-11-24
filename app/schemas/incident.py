from typing import Any, Literal
from pydantic import BaseModel,Field

class IncidentCreateRequest(BaseModel) :
    raw_log : str = Field(
        ...,
        min_length = 10,
        description="Raw error logs,stack trace or incident ticket text")

    incident_id : str | None = Field(default = None,
                                     description="Optional custom incident ID (auto-generated if omitted)",)

class HumanReviewRequest(BaseModel) :
    approved : bool = Field(
        ...,
        description="True to approve the remediation plan,False to reject/escalate"
    )
    feedback : str = Field(
        default = "",
        description = "Optional engineer notes or override instructions",
    )


class IncidentResponse(BaseModel):
    incident_id: str
    thread_id: str
    status: Literal["awaiting_approval", "completed"]
    severity: str | None = None
    domain: str | None = None
    triage_summary: str | None = None
    root_cause: str | None = None
    remediation_steps: list[str] = Field(default_factory=list)
    proposed_commands: list[str] = Field(default_factory=list)
    safety_approved: bool | None = None
    safety_feedback: str | None = None
    retrieved_runbooks: list[dict[str, Any]] = Field(default_factory=list)
    parsed_signals: dict[str, Any] | None = None
    agent_trace: list[str] = Field(default_factory=list)
    final_report: str | None = None


