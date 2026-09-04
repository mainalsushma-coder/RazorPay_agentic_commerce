"""Local Ollama shopping agent backed exclusively by the storefront MCP server."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from ollama import AsyncClient

from app.models.chat import AgentChatResponse, AgentEvent


MODEL = "qwen3.5:4b"
MAX_TOOL_ROUNDS = 12
SYSTEM_INSTRUCTION = """You are a shopping agent for the Agent Storefront Autopilot.
Multiple merchants are available. Every catalog search and order must be
associated with a merchant. Use list_merchants to discover valid merchant IDs,
never invent merchant IDs, and never mix products between merchants.
Use the available commerce tools to search the selected merchant catalog and
create orders only when explicitly requested by the user.
Never invent SKUs, prices, stock, order IDs, or payment results.
Use catalog_search before purchasing when the SKU is not already known.
Respect all tool results and policy decisions.
If an order requires human confirmation, clearly tell the user that
confirmation is required and do not claim the purchase completed.
Human confirmation is not an available tool, so do not offer to perform or
finalize that confirmation yourself.
If an order is blocked, explain the policy reason.
Never claim payment/order success unless the tool reports success."""


def _server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
    )


def _ollama_tools(mcp_tools: Sequence[Any]) -> list[dict[str, Any]]:
    """Translate tool metadata discovered from MCP into Ollama's tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.input_schema,
            },
        }
        for tool in mcp_tools
    ]


def _tool_result_text(result: Any) -> str:
    """Preserve MCP structured results when present, otherwise serialize content."""
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False, default=str)

    parts: list[Any] = []
    for item in result.content:
        text = getattr(item, "text", None)
        parts.append(text if text is not None else item.model_dump(mode="json"))
    return json.dumps(
        {"is_error": bool(result.isError), "content": parts},
        ensure_ascii=False,
        default=str,
    )


async def run_agent(
    user_message: str,
    *,
    merchant_id: str | None = None,
    conversation_history: list[Any] | None = None,
    ollama_client: AsyncClient | None = None,
) -> AgentChatResponse:
    """Run one user request through Ollama and the stdio MCP server."""
    server = _server_parameters()
    client = ollama_client or AsyncClient()

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            discovered = (await session.list_tools()).tools
            tools = _ollama_tools(discovered)
            schemas = {tool.name: tool.input_schema for tool in discovered}
            instruction = SYSTEM_INSTRUCTION
            if merchant_id is not None:
                instruction += (
                    f"\nThe active merchant for this conversation is '{merchant_id}'. "
                    "Use this exact merchant_id for every commerce tool call and do "
                    "not switch merchants."
                )
            messages: list[Any] = [{"role": "system", "content": instruction}]
            messages.extend(conversation_history or [])
            messages.append({"role": "user", "content": user_message})
            events: list[AgentEvent] = []
            products: list[dict[str, Any]] = []
            order: dict[str, Any] | None = None

            for _ in range(MAX_TOOL_ROUNDS):
                response = await client.chat(
                    model=MODEL,
                    messages=messages,
                    tools=tools,
                    stream=False,
                )
                assistant_message = response.message
                messages.append(assistant_message)
                calls = assistant_message.tool_calls or []
                if not calls:
                    if conversation_history is not None:
                        conversation_history[:] = messages[1:]
                    return AgentChatResponse(
                        message=assistant_message.content or "",
                        merchant_id=merchant_id or "",
                        events=events,
                        products=products,
                        order=order,
                    )

                for call in calls:
                    name = call.function.name
                    arguments = dict(call.function.arguments)

                    schema = schemas.get(name)
                    if schema is None:
                        result_text = json.dumps({"error": "Unknown MCP tool"})
                    elif (
                        merchant_id is not None
                        and name in {"catalog_search", "create_order"}
                        and arguments.get("merchant_id") != merchant_id
                    ):
                        result_text = json.dumps({
                            "error": "merchant_context_mismatch",
                            "message": "Tool call must use the active merchant",
                            "merchant_id": merchant_id,
                        })
                    else:
                        allowed = set(schema.get("properties", {}))
                        unexpected = sorted(set(arguments) - allowed)
                        if unexpected:
                            result_text = json.dumps(
                                {"error": f"Unsupported tool arguments: {unexpected}"}
                            )
                        else:
                            result = await session.call_tool(name, arguments=arguments)
                            result_text = _tool_result_text(result)

                    try:
                        observed = json.loads(result_text)
                    except (TypeError, json.JSONDecodeError):
                        observed = None
                    events.append(AgentEvent(
                        type="tool_call", tool=name,
                        status="rejected" if isinstance(observed, dict) and observed.get("error") else "completed",
                    ))
                    payload = observed.get("result", observed) if isinstance(observed, dict) else observed
                    if name == "catalog_search" and isinstance(payload, list):
                        products = [item for item in payload if isinstance(item, dict) and item.get("merchant_id") == merchant_id]
                    if name == "create_order" and isinstance(payload, dict):
                        order = payload
                        decision = payload.get("policy_decision") or payload.get("decision")
                        if decision:
                            events.append(AgentEvent(type="policy", decision=str(decision)))

                    messages.append(
                        {"role": "tool", "tool_name": name, "content": result_text}
                    )

    raise RuntimeError("The model exceeded the maximum number of tool rounds")


def _select_merchant(
    merchants: list[dict[str, Any]],
    *,
    input_fn: Any = input,
    output_fn: Any = print,
) -> dict[str, Any]:
    ready_merchants = [merchant for merchant in merchants if merchant["agent_ready"]]
    if not ready_merchants:
        raise RuntimeError("No agent-ready merchants are available")

    output_fn("Available stores:")
    for index, merchant in enumerate(ready_merchants, start=1):
        output_fn(f"{index}. {merchant['name']} — {merchant['category']}")

    while True:
        choice = input_fn("Select store: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(ready_merchants):
            selected = ready_merchants[int(choice) - 1]
            output_fn(f"Selected: {selected['name']}")
            return selected
        output_fn("Please enter a valid store number.")


async def _discover_merchants() -> list[dict[str, Any]]:
    async with stdio_client(_server_parameters()) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("list_merchants", arguments={})
            structured = getattr(result, "structured_content", None)
            if isinstance(structured, dict):
                value = structured.get("result", structured.get("merchants"))
                if isinstance(value, list):
                    return value
            if isinstance(structured, list):
                return structured
            for item in result.content:
                text = getattr(item, "text", None)
                if text:
                    decoded = json.loads(text)
                    if isinstance(decoded, list):
                        return decoded
            raise RuntimeError("MCP merchant discovery returned an invalid response")


async def _cli() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        selected = _select_merchant(await _discover_merchants())
        history: list[Any] = []
        while True:
            request = input("You: ").strip()
            if not request or request.casefold() in {"exit", "quit"}:
                return
            answer = await run_agent(
                request,
                merchant_id=selected["merchant_id"],
                conversation_history=history,
            )
            print(f"Agent: {answer.message}")
    except (EOFError, KeyboardInterrupt):
        print()


if __name__ == "__main__":
    asyncio.run(_cli())
