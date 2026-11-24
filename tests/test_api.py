from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "app" in data


def test_analyze_rejects_short_log():
    response = client.post("/api/v1/incidents/analyze", json={"raw_log": "err"})
    assert response.status_code == 422


def test_get_unknown_incident_returns_404():
    response = client.get("/api/v1/incidents/non-existent-thread-id")
    assert response.status_code == 404


def test_review_unknown_incident_returns_404():
    response = client.post(
        "/api/v1/incidents/non-existent-thread-id/review",
        json={"approved": True, "feedback": "Test"},
    )
    assert response.status_code == 404


