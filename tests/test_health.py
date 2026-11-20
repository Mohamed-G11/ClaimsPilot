from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["warmup"]) == {"llm", "vision", "retrieval", "decision"}
