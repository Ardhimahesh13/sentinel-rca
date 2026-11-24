import json
import uuid
from typing import Iterator

from pathlib import Path
from fastapi.staticfiles import StaticFiles

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.graph.workflow import get_workflow
from app.schemas.incident import (
    HumanReviewRequest,
    IncidentCreateRequest,
    IncidentResponse,
)

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Autonomous IT Incident Triage & Root-Cause Analysis Multi-Agent Engine",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _build_response(thread_id: str, values: dict, is_paused: bool) -> IncidentResponse:
    return IncidentResponse(
        incident_id=values.get("incident_id", "UNKNOWN"),
        thread_id=thread_id,
        status="awaiting_approval" if is_paused else "completed",
        severity=values.get("severity"),
        domain=values.get("domain"),
        triage_summary=values.get("triage_summary"),
        root_cause=values.get("root_cause"),
        remediation_steps=values.get("remediation_steps", []),
        proposed_commands=values.get("proposed_commands", []),
        safety_approved=values.get("safety_approved"),
        safety_feedback=values.get("safety_feedback"),
        retrieved_runbooks=values.get("retrieved_runbooks", []),
        parsed_signals=values.get("parsed_signals"),
        agent_trace=values.get("agent_trace", []),
        final_report=values.get("final_report"),
    )


def _sse_event(event_type : str,payload : dict) -> str : # ( Server sent events)
    return f"event: {event_type}\ndata: {json.dumps(payload, default=str)}\n\n"

@app.get("/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
    }

@app.post("/api/v1/incidents/analyze", response_model=IncidentResponse)
def analyze_incident(payload: IncidentCreateRequest) -> IncidentResponse:
    workflow = get_workflow()
    thread_id = str(uuid.uuid4())
    incident_id = payload.incident_id or f"INC-{thread_id[:8].upper()}"
    config = {"configurable": {"thread_id": thread_id}}

    try:
        workflow.invoke(
            {"incident_id": incident_id, "raw_log": payload.raw_log},
            config=config,
        )
        snapshot = workflow.get_state(config)
        return _build_response(thread_id, snapshot.values, bool(snapshot.next))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {exc}")

@app.post("/api/v1/incidents/analyze/stream")
def analyze_incident_stream(payload: IncidentCreateRequest) -> StreamingResponse:
    workflow = get_workflow()
    thread_id = str(uuid.uuid4())
    incident_id = payload.incident_id or f"INC-{thread_id[:8].upper()}"
    config = {"configurable": {"thread_id": thread_id}}

    def event_generator() -> Iterator[str]:
        yield _sse_event(
            "started",
            {"incident_id": incident_id, "thread_id": thread_id},
        )
        try:
            for update in workflow.stream(
                {"incident_id": incident_id, "raw_log": payload.raw_log},
                config=config,
                stream_mode="updates",
            ):
                for node_name, node_output in update.items():
                    if node_name == "__interrupt__":
                        continue
                    yield _sse_event(
                        "node_update",
                        {
                            "node": node_name,
                            "data": node_output,
                        },
                    )

            snapshot = workflow.get_state(config)
            response = _build_response(thread_id, snapshot.values, bool(snapshot.next))
            yield _sse_event("paused", response.model_dump())
        except Exception as exc:
            yield _sse_event("error", {"detail": str(exc)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@app.post("/api/v1/incidents/{thread_id}/review", response_model=IncidentResponse)
def review_incident(thread_id: str, payload: HumanReviewRequest) -> IncidentResponse:
    workflow = get_workflow()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = workflow.get_state(config)

    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Incident thread not found.")
    if not snapshot.next:
        raise HTTPException(status_code=400, detail="Incident is already completed.")

    try:
        workflow.update_state(
            config,
            {
                "human_approved": payload.approved,
                "human_feedback": payload.feedback,
            },
        )
        workflow.invoke(None, config=config)
        final_snapshot = workflow.get_state(config)
        return _build_response(thread_id, final_snapshot.values, bool(final_snapshot.next))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Resume failed: {exc}")


@app.get("/api/v1/incidents/{thread_id}", response_model=IncidentResponse)
def get_incident(thread_id: str) -> IncidentResponse:
    workflow = get_workflow()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = workflow.get_state(config)

    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Incident thread not found.")

    return _build_response(thread_id, snapshot.values, bool(snapshot.next))

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

