import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.agent as agent
from app.main import app


client = TestClient(app)


class AsyncContext:
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self.value
    async def __aexit__(self, *args): return False


class Session:
    def __init__(self):
        self.results = [
            [{"merchant_id": "glowcare", "sku": "SKIN001", "name": "Vitamin C Serum", "price": 699, "stock": 15}],
            [{"merchant_id": "techhub", "sku": "TECH001", "name": "Wireless Mechanical Keyboard", "price": 3499, "stock": 12}],
        ]
        self.tools = [SimpleNamespace(name="catalog_search", description="Search", input_schema={"type":"object","properties":{"merchant_id":{},"query":{}}})]
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    async def initialize(self): return None
    async def list_tools(self): return SimpleNamespace(tools=self.tools)
    async def call_tool(self, name, arguments):
        return SimpleNamespace(structured_content={"result": self.results.pop(0)}, content=[], isError=False)


class Ollama:
    def __init__(self): self.responses = [
        SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[SimpleNamespace(function=SimpleNamespace(name="catalog_search", arguments={"merchant_id":"glowcare","query":"wireless"}))])),
        SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[SimpleNamespace(function=SimpleNamespace(name="catalog_search", arguments={"merchant_id":"techhub","query":"wireless"}))])),
        SimpleNamespace(message=SimpleNamespace(content="Compared active merchant catalogs.", tool_calls=[])),
    ]
    async def chat(self, **kwargs): return self.responses.pop(0)


def test_buyer_goal_does_not_require_merchant_preselection(monkeypatch):
    captured = {}
    async def fake(message, *, merchant_id, conversation_history):
        captured.update(merchant_id=merchant_id, message=message)
        return {"message":"done", "merchant_id":"", "events":[], "products":[], "order":None}
    monkeypatch.setattr("app.main.run_agent", fake)
    response = client.post("/agent/chat", json={"message":"Find the best keyboard", "conversation_history":[]})
    assert response.status_code == 200
    assert captured == {"merchant_id": None, "message": "Find the best keyboard"}


def test_universal_agent_accumulates_authoritatively_scoped_candidates(monkeypatch):
    session = Session()
    monkeypatch.setattr(agent, "stdio_client", lambda server: AsyncContext((object(), object())))
    monkeypatch.setattr(agent, "ClientSession", lambda read, write: session)
    result = asyncio.run(agent.run_agent("Compare wireless products", ollama_client=Ollama()))
    assert [(p["merchant_id"], p["sku"]) for p in result.products] == [
        ("glowcare", "SKIN001"), ("techhub", "TECH001")
    ]


def test_buyer_and_merchant_navigation_are_separate():
    buyer = client.get("/dashboard").text
    merchant = client.get("/merchant-portal").text
    assert "merchant-portal" not in buyer.casefold()
    assert "catalog upload" not in buyer.casefold()
    assert 'href="/dashboard"' not in merchant
    assert "Purchase authority" not in merchant


def test_runtime_activity_contains_only_backend_order_state():
    response = client.get("/buyer/activity")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_empty_previous_reply_reproduces_backend_validation_failure(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Validation fails before orchestration")
    monkeypatch.setattr("app.main.run_agent", forbidden)
    response = client.post("/agent/chat", json={"message": "Buy Vitamin C serum", "conversation_history": [
        {"role": "user", "content": "Find a snowboard"}, {"role": "assistant", "content": ""},
    ]})
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"] == ["body", "conversation_history", 1, "content"]
    assert error["type"] == "string_too_short"


def test_global_agent_ignores_prior_source_conversation(monkeypatch):
    session = Session()
    monkeypatch.setattr(agent, "stdio_client", lambda server: AsyncContext((object(), object())))
    monkeypatch.setattr(agent, "ClientSession", lambda read, write: session)
    class InspectModel:
        async def chat(self, **kwargs):
            assert len(kwargs["messages"]) == 2
            assert kwargs["messages"][-1]["content"] == "Buy Vitamin C serum"
            assert "discover connected merchants again" in kwargs["messages"][0]["content"]
            return SimpleNamespace(message=SimpleNamespace(content="Ready", tool_calls=[]))
    asyncio.run(agent.run_agent("Buy Vitamin C serum", conversation_history=[
        {"role": "assistant", "content": "Selected Shopify snowboard"},
    ], ollama_client=InspectModel()))


def test_tool_result_text_supports_real_mcp_call_tool_result():
    import json
    from types import SimpleNamespace
    from mcp.types import CallToolResult, TextContent

    real_result = CallToolResult(
        content=[TextContent(type="text", text="Catalog error")], is_error=True
    )
    parsed_real = json.loads(agent._tool_result_text(real_result))
    assert parsed_real["is_error"] is True
    assert parsed_real["content"] == ["Catalog error"]

    mock_result = SimpleNamespace(content=[SimpleNamespace(text="Mock error")], isError=True)
    parsed_mock = json.loads(agent._tool_result_text(mock_result))
    assert parsed_mock["is_error"] is True
    assert parsed_mock["content"] == ["Mock error"]
