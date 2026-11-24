from typing import Literal
from pydantic import BaseModel,Field
from langchain_core.messages import SystemMessage,HumanMessage

from app.core.llm import get_llm
from app.graph.state import IncidentState
from app.rag.pinecone_client import get_runbook_store


class TriageOutput(BaseModel):
    severity: Literal["P1", "P2", "P3", "P4"] = Field(description="P1=Critical outage, P2=High degradation, P3=Minor issue, P4=Low/Info") # kitna serious
    domain: Literal["database", "network", "auth", "application", "general"] = Field(description="Primary IT domain affected by the incident" )
    triage_summary: str = Field(description="One-sentence summary of the incident for search and routing") # summary in one lIne

class SignalOutput(BaseModel) :
    error_type : str = Field(description="Primary exception, HTTP status, or exit code")
    affected_service: str = Field(description="Service, container, or component name")
    key_indicators: list[str] = Field(description="Up to 4 concrete clues from the log")

class RCAOutput(BaseModel) :
    root_cause : str = Field(description="Clear, concise technical root cause")
    remediation_steps : list[str] = Field(description="Ordered, safe, actionable steps to resolve the incident")
    proposed_commands : list[str] = Field(description="Exact CLI or SQL commands to inspect or fix the issue safely")

class SafetyOutput(BaseModel):
    safety_approved: bool = Field(description="True ONLY if all steps and commands are non-destructive and safe for production")
    safety_feedback: str = Field(description="If rejected, explain the exact unsafe command/step and how to make it safe. If approved, write 'Passed safety checks.'")

# node 1 : -- Triage Router --
def triage_node(state : IncidentState) -> dict :
    llm = get_llm("fast").with_structured_output(TriageOutput,method = "json_mode")
    result : TriageOutput = llm.invoke([ SystemMessage(content = ("You are an L2 SRE Triage Router. Classify the raw IT incident log into "
                "severity (P1-P4), domain (database, network, auth, application, general), "
                'Respond strictly in valid JSON with these exact keys: {"severity": "P1|P2|P3", "domain": "string", "triage_summary": "string"}.'
                "and a crisp one-sentence summary.")),
                HumanMessage(content = (f"Raw Incident Log:\n{state['raw_log']}"),)])
    return {
        "severity": result.severity,
        "domain": result.domain,
        "triage_summary": result.triage_summary,
        "revision_count": state.get("revision_count", 0),
        "agent_trace": [f"[Triage] Classified as {result.severity} | Domain: {result.domain}"],
    }

# Node 2A: -- Parallel Investigator — Pinecone Runbook RAG ---
def retrieve_runbooks_node(state: IncidentState) -> dict:
    store = get_runbook_store()
    domain = state.get("domain", "general")
    domain_filter = None if domain == "general" else domain

    query = f"{state.get('triage_summary', '')} {state['raw_log'][:300]}"
    matches = store.search_runbooks(query=query, top_k=2, domain_filter=domain_filter)

    # Fallback to unfiltered search if domain filter returned nothing
    if not matches and domain_filter is not None:
        matches = store.search_runbooks(query=query, top_k=2, domain_filter=None)

    titles = [m["title"] for m in matches]
    return {
        "retrieved_runbooks": matches,
        "agent_trace": [f"[RAG] Retrieved {len(matches)} runbook(s): {', '.join(titles) or 'None'}"],
    }
# --- Node 2B: Parallel Investigator — Stack-Trace & Signal Parser (8B) ---

def parse_signals_node(state: IncidentState) -> dict:
    llm = get_llm("fast").with_structured_output(SignalOutput,method = "json_mode")
    result: SignalOutput = llm.invoke([
        SystemMessage(
            content=(
                "You are an SRE Log Parser. Extract the exact error type, affected service, "
                "and concrete technical indicators from the raw log,"
              'Respond strictly with a SINGLE JSON object (never a JSON list or array) summarizing the primary incident across all log lines using these exact keys: {"error_type": "string", "affected_service": "string", "key_indicators": ["string"]}.'
            )
        ),
        HumanMessage(content=state["raw_log"]),
    ])

    return {
        "parsed_signals": result.model_dump(),
        "agent_trace": [
            f"[Parser] Extracted {result.error_type} on {result.affected_service}"
        ],
    }


# --- Node 3: RCA & Remediation Synthesizer  ---

def rca_synthesis_node(state: IncidentState) -> dict:
    llm = get_llm("reasoning").with_structured_output(RCAOutput,method = "json_mode")

    runbooks_text = "\n\n".join(
        f"- {rb['title']} (score {rb['score']}): {rb['text']}"
        for rb in state.get("retrieved_runbooks", [])
    ) or "No historical runbooks matched."

    feedback_block = ""
    if state.get("safety_feedback") and not state.get("safety_approved", True):
        feedback_block = (
            f"\n\nPREVIOUS REMEDIATION REJECTED BY SAFETY CRITIC:\n"
            f"{state['safety_feedback']}\n"
            "You MUST fix these safety issues in your revised plan."
        )

    prompt = (
        f"Severity: {state.get('severity')} | Domain: {state.get('domain')}\n"
        f"Parsed Signals: {state.get('parsed_signals')}\n\n"
        f"Raw Log:\n{state['raw_log']}\n\n"
        f"Historical Runbooks:\n{runbooks_text}"
        f"{feedback_block}"
    )

    result: RCAOutput = llm.invoke([
        SystemMessage(
            content=(
                "You are a Principal SRE. Synthesize the root cause and a safe, production-ready "
               'Respond strictly in valid JSON with these exact keys: {"root_cause": "string", "remediation_steps": ["string"], "proposed_commands": ["string"]}.'
                "remediation plan grounded in the raw log and historical runbooks. "
                "Never propose destructive commands (DROP, TRUNCATE, rm -rf, FLUSHALL, force-kill primary DB)."
            )
        ),
        HumanMessage(content=prompt),
    ])

    return {
        "root_cause": result.root_cause,
        "remediation_steps": result.remediation_steps,
        "proposed_commands": result.proposed_commands,
        "agent_trace": ["[RCA 70B] Drafted root cause and remediation plan"],
    }


# --- Node 4: Safety Verification Critic (8B) ---

def safety_critic_node(state: IncidentState) -> dict:
    llm = get_llm("fast").with_structured_output(SafetyOutput,method = "json_mode")

    plan_text = (
        f"Remediation Steps:\n{state.get('remediation_steps', [])}\n\n"
        f"Proposed Commands:\n{state.get('proposed_commands', [])}"
    )

    result: SafetyOutput = llm.invoke([
        SystemMessage(
            content=(
                "You are a strict Production Safety Critic. Reject any plan that contains "
                "destructive database commands (DROP, TRUNCATE, DELETE without WHERE), "
                'Respond strictly in valid JSON with these exact keys: {"safety_approved": true, "safety_feedback": "string"}.'
                "destructive shell commands (rm -rf, kill -9 on primary DB), cache wipes (FLUSHALL), "
                "or unverified restarts without health checks. Approve only safe diagnostic and remediation steps."
            )
        ),
        HumanMessage(content=plan_text),
    ])

    new_revision = state.get("revision_count", 0) + (0 if result.safety_approved else 1)
    status = "APPROVED" if result.safety_approved else f"REJECTED (rev {new_revision})"

    return {
        "safety_approved": result.safety_approved,
        "safety_feedback": result.safety_feedback,
        "revision_count": new_revision,
        "agent_trace": [f"[Safety Critic] {status}: {result.safety_feedback}"],
    }


# --- Node 5: Finalize Incident Report (Post-HITL) ---

def finalize_report_node(state: IncidentState) -> dict:
    approved = state.get("human_approved", False)
    decision_str = "APPROVED BY ENGINEER" if approved else "REJECTED / ESCALATED BY ENGINEER"
    human_note = state.get("human_feedback") or "No additional engineer notes."

    steps_md = "\n".join(
        f"{i}. {step}" for i, step in enumerate(state.get("remediation_steps", []), start=1)
    )
    cmds_md = "\n".join(f"   - `{cmd}`" for cmd in state.get("proposed_commands", []))

    report = (
        f"## Incident RCA Report ({state.get('incident_id', 'N/A')})\n"
        f"- **Severity:** {state.get('severity')} | **Domain:** {state.get('domain')}\n"
        f"- **Human Review Status:** {decision_str}\n"
        f"- **Engineer Notes:** {human_note}\n\n"
        f"### Root Cause\n{state.get('root_cause', 'N/A')}\n\n"
        f"### Remediation Plan\n{steps_md}\n\n"
        f"### Proposed Commands\n{cmds_md or '   - None'}\n"
    )

    return {
        "final_report": report,
        "agent_trace": [f"[Finalize] Report generated ({decision_str})"],
    }
