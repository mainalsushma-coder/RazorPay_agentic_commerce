from fastapi.testclient import TestClient

from app.main import app
from app.models.chat import AgentChatResponse, AgentEvent


client = TestClient(app)


def test_chat_is_merchant_scoped_and_passes_history(monkeypatch):
    captured = {}

    async def fake_agent(message, *, merchant_id, conversation_history):
        captured.update(message=message, merchant_id=merchant_id, history=conversation_history)
        return AgentChatResponse(
            message="Vitamin C Serum is available.", merchant_id=merchant_id,
            events=[AgentEvent(type="tool_call", tool="catalog_search", status="completed")],
            products=[{"merchant_id": merchant_id, "sku": "SKIN001", "name": "Vitamin C Serum"}],
        )

    monkeypatch.setattr("app.main.run_agent", fake_agent)
    response = client.post("/agent/chat", json={
        "merchant_id": "glowcare", "message": "Buy 2",
        "conversation_history": [
            {"role": "user", "content": "Find vitamin C serum"},
            {"role": "assistant", "content": "I found SKIN001"},
        ],
    })
    assert response.status_code == 200
    assert response.json()["merchant_id"] == "glowcare"
    assert captured == {
        "message": "Buy 2", "merchant_id": "glowcare",
        "history": [
            {"role": "user", "content": "Find vitamin C serum"},
            {"role": "assistant", "content": "I found SKIN001"},
        ],
    }


def test_chat_rejects_unknown_merchant_without_running_agent(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Agent must not run")
    monkeypatch.setattr("app.main.run_agent", forbidden)
    response = client.post("/agent/chat", json={
        "merchant_id": "missing", "message": "Shop at TechHub",
        "conversation_history": [],
    })
    assert response.status_code == 404


def test_browser_uses_only_safe_server_endpoints():
    script = client.get("/static/app.js").text
    assert "/agent/chat" in script
    assert "/orders/${encodeURIComponent(orderId)}/confirm" in script
    for forbidden in ("localhost:11434", "ollama", "api.razorpay", "RAZORPAY_KEY"):
        assert forbidden not in script
