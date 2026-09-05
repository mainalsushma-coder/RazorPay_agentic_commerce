import asyncio
import json
import traceback
from types import SimpleNamespace

import httpx
import pytest

from app import agent, llm_provider as provider
from test_agent_security import FakeOllama, FakeSession, assistant, install_fake_mcp


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MAX_TOKENS", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_MODEL", "qwen/test-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-test-secret")


@pytest.mark.parametrize("selection", [None, "ollama"])
def test_ollama_selection_preserves_native_client(monkeypatch, selection):
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "invalid")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    if selection:
        monkeypatch.setenv("LLM_PROVIDER", selection)
    sentinel = object()
    monkeypatch.setattr(provider, "AsyncClient", lambda: sentinel)
    assert provider.create_chat_client() is sentinel
    assert agent.MODEL == "qwen3.5:4b"


def test_openrouter_env(configured):
    client = provider.create_chat_client()
    assert isinstance(client, provider.OpenRouterClient)
    assert client.model == "qwen/test-model"
    assert client.max_tokens == 2048
    assert client._api_key == "private-test-secret"
    assert "private-test-secret" not in repr(client)


def test_default_ollama_agent_request_is_unchanged(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    install_fake_mcp(monkeypatch, FakeSession())
    client = FakeOllama([assistant(content="Local answer")])
    monkeypatch.setattr(provider, "AsyncClient", lambda: client)
    result = asyncio.run(agent.run_agent("Hello"))
    assert result.message == "Local answer"
    request = client.requests[0]
    assert request["model"] == "qwen3.5:4b"
    assert request["stream"] is False
    assert request["messages"][:2] == [
        {"role": "system", "content": agent.SYSTEM_INSTRUCTION},
        {"role": "user", "content": "Hello"},
    ]
    assert request["tools"][0]["function"]["name"] == "catalog_search"


@pytest.mark.parametrize("name", ["OPENROUTER_MODEL", "OPENROUTER_API_KEY"])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_configuration(configured, monkeypatch, name, value):
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(provider.InferenceConfigurationError, match=name) as error:
        provider.create_chat_client()
    assert "private-test-secret" not in str(error.value)


def test_unknown_provider_is_safe(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "private-test-secret")
    with pytest.raises(provider.InferenceConfigurationError) as error:
        provider.create_chat_client()
    assert "private-test-secret" not in str(error.value)


def mock_http(monkeypatch, handler):
    native = httpx.AsyncClient
    def factory(**kwargs):
        assert kwargs == {"timeout": 60.0}
        return native(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(provider.httpx, "AsyncClient", factory)


@pytest.mark.parametrize("limit, expected", [(None, 2048), ("1024", 1024)])
def test_openrouter_agent_tool_roundtrip(configured, monkeypatch, limit, expected):
    if limit is not None:
        monkeypatch.setenv("OPENROUTER_MAX_TOKENS", limit)
    session = FakeSession(SimpleNamespace(structured_content={"result": []}, content=[]))
    install_fake_mcp(monkeypatch, session)
    requests = []
    calls = [{"id": f"call-{i}", "type": "function", "function": {
        "name": "catalog_search", "arguments": json.dumps({"merchant_id": "glowcare", "query": str(i)})
    }} for i in range(2)]
    wire = {"role": "assistant", "content": None, "tool_calls": calls,
            "reasoning_details": [{"type": "reasoning.text", "text": "Search"}]}
    def handler(request):
        assert request.headers["authorization"] == "Bearer private-test-secret"
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "qwen/test-model"
        assert body["max_tokens"] == expected
        assert body["tools"][0]["function"]["name"] == "catalog_search"
        assert body["stream"] is False
        return httpx.Response(200, json={"choices": [{"message": wire if len(requests) == 1 else {
            "role": "assistant", "content": "Done"}}]})
    mock_http(monkeypatch, handler)
    result = asyncio.run(agent.run_agent("Search", merchant_id="glowcare"))
    assert result.message == "Done"
    assert len(session.calls) == 2
    assert requests[1]["messages"][2] == wire
    assert [m["tool_call_id"] for m in requests[1]["messages"] if m["role"] == "tool"] == ["call-0", "call-1"]
    assert all("tool_name" not in m for m in requests[1]["messages"])


@pytest.mark.parametrize("value", ["", "  ", "0", "-1", "1.5", "private-test-secret"])
def test_invalid_max_tokens_fails_safely_before_mcp(configured, monkeypatch, caplog, value):
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", value)
    monkeypatch.setattr(agent, "stdio_client", lambda *_: pytest.fail("MCP opened"))
    with pytest.raises(provider.InferenceConfigurationError) as error:
        asyncio.run(agent.run_agent("Hello"))
    assert str(error.value) == "OPENROUTER_MAX_TOKENS must be a positive integer."
    assert "private-test-secret" not in "".join(traceback.format_exception(error.value))
    assert "private-test-secret" not in caplog.text


@pytest.mark.parametrize("failure", ["http", "timeout", "json", "arguments", "error"])
def test_failures_are_safe_without_fallback(configured, monkeypatch, caplog, failure):
    secret = "private-test-secret"
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout(secret)
        if failure == "http":
            return httpx.Response(401, text=secret)
        if failure == "json":
            return httpx.Response(200, text=secret)
        if failure == "error":
            return httpx.Response(200, json={"error": secret})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "tool_calls": [{
            "id": "bad", "type": "function", "function": {"name": "search", "arguments": secret}
        }]}}]})
    mock_http(monkeypatch, handler)
    monkeypatch.setattr(provider, "AsyncClient", lambda: pytest.fail("Ollama fallback"))
    with pytest.raises(provider.InferenceError) as error:
        asyncio.run(provider.create_chat_client().chat(model=agent.MODEL, messages=[], tools=[]))
    assert secret not in "".join(traceback.format_exception(error.value))
    assert secret not in caplog.text


def test_invalid_config_fails_before_mcp(configured, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    monkeypatch.setattr(agent, "stdio_client", lambda *_: pytest.fail("MCP opened"))
    with pytest.raises(provider.InferenceConfigurationError):
        asyncio.run(agent.run_agent("Search"))


def test_provider_diagnostic_logs_only_safe_error_fields(configured, monkeypatch, caplog):
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "payment-secret")
    def handler(request):
        return httpx.Response(402, json={"error": {
            "message": "Insufficient credits private-test-secret payment-secret",
            "metadata": {"request": "must-not-be-logged"},
        }})
    mock_http(monkeypatch, handler)
    with pytest.raises(provider.InferenceError):
        asyncio.run(provider.create_chat_client().chat(model="unused", messages=[], tools=[]))
    assert "status=402 provider=openrouter model=qwen/test-model error_type=HTTPStatusError" in caplog.text
    assert "Insufficient credits [REDACTED] [REDACTED]" in caplog.text
    assert all(secret not in caplog.text for secret in (
        "private-test-secret", "payment-secret", "must-not-be-logged",
    ))
