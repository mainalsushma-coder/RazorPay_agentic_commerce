import asyncio
import sys

import pytest

from app import agent
from app.agent import MODEL, SYSTEM_INSTRUCTION, _ollama_tools, _select_merchant


@pytest.mark.parametrize("entrypoint", ["chat", "discovery"])
def test_mcp_child_inherits_parent_environment(monkeypatch, entrypoint):
    import mcp.client.stdio as stdio

    # Replace the entire environment so failures cannot display real credentials.
    monkeypatch.setattr(agent.os, "environ", {
        "RAZORPAY_KEY_ID": "test_value",
        "BOUND_TEST_ENV": "test_parent_value",
    })

    class SpawnIntercepted(Exception):
        pass

    async def intercept_spawn(*, command, args, env, **kwargs):
        assert command == sys.executable
        assert args == ["-m", "app.mcp_server"]
        assert env["RAZORPAY_KEY_ID"] == "test_value"
        assert env["BOUND_TEST_ENV"] == "test_parent_value"
        raise SpawnIntercepted

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", intercept_spawn)
    request = (
        agent.run_agent("test", ollama_client=object())
        if entrypoint == "chat" else agent._discover_merchants()
    )
    with pytest.raises(SpawnIntercepted):
        asyncio.run(request)


def test_agent_configuration_remains_dynamic_and_merchant_aware():
    class Tool:
        name = "list_merchants"
        description = "List merchants"
        input_schema = {"type": "object", "properties": {}}

    assert MODEL == "qwen3.5:4b"
    assert [tool["function"]["name"] for tool in _ollama_tools([Tool()])] == [
        "list_merchants"
    ]
    for requirement in ("Multiple merchants", "never invent merchant IDs", "never mix"):
        assert requirement in SYSTEM_INSTRUCTION


def test_cli_merchant_selection_uses_ready_public_metadata():
    output = []
    merchants = [
        {
            "merchant_id": "glowcare", "name": "GlowCare",
            "category": "Skincare", "description": "Skin", "agent_ready": True,
        },
        {
            "merchant_id": "techhub", "name": "TechHub",
            "category": "Electronics", "description": "Tech", "agent_ready": True,
        },
    ]

    selected = _select_merchant(
        merchants, input_fn=lambda prompt: "2", output_fn=output.append
    )

    assert selected["merchant_id"] == "techhub"
    assert output == [
        "Available stores:",
        "1. GlowCare — Skincare",
        "2. TechHub — Electronics",
        "Selected: TechHub",
    ]
