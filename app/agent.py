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


MODEL = "qwen3.5:4b"
MAX_TOOL_ROUNDS = 12
SYSTEM_INSTRUCTION = """You are a shopping agent for the Agent Storefront Autopilot.
Use the available commerce tools to search the merchant catalog and
create orders when explicitly requested by the user.
Never invent SKUs, prices, stock, order IDs, or payment results.
Use catalog_search before purchasing when the SKU is not already known.
Respect all tool results and policy decisions.
If an order requires human confirmation, clearly tell the user that
confirmation is required and do not claim the purchase completed.
Human confirmation is not an available tool, so do not offer to perform or
finalize that confirmation yourself.
If an order is blocked, explain the policy reason.
Never claim payment/order success unless the tool reports success."""


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


async def run_agent(user_message: str, *, ollama_client: AsyncClient | None = None) -> str:
    """Run one user request through Ollama and the stdio MCP server."""
    server = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "app.mcp_server"],
    )
    client = ollama_client or AsyncClient()

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            discovered = (await session.list_tools()).tools
            tools = _ollama_tools(discovered)
            schemas = {tool.name: tool.input_schema for tool in discovered}
            messages: list[Any] = [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": user_message},
            ]

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
                    return assistant_message.content or ""

                for call in calls:
                    name = call.function.name
                    arguments = dict(call.function.arguments)
                    print(f"[tool] {name}")

                    schema = schemas.get(name)
                    if schema is None:
                        result_text = json.dumps({"error": "Unknown MCP tool"})
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

                    messages.append(
                        {"role": "tool", "tool_name": name, "content": result_text}
                    )

    raise RuntimeError("The model exceeded the maximum number of tool rounds")


async def _cli() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        request = input("You: ").strip()
        if not request:
            return
        answer = await run_agent(request)
        print(f"Agent: {answer}")
    except (EOFError, KeyboardInterrupt):
        print()


if __name__ == "__main__":
    asyncio.run(_cli())
