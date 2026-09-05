import asyncio
import base64
import json
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Protocol

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult


RAZORPAY_MCP_URL = "https://mcp.razorpay.com/mcp"
RAZORPAY_CREATE_ORDER_TOOL = "create_order"
_ALLOWED_ARGUMENTS = frozenset({"amount", "currency", "receipt"})


class PaymentExecutionError(RuntimeError):
    """A safe, non-secret-bearing payment execution failure."""


class MCPTransportUnavailable(PaymentExecutionError):
    """The request was not sent, so an SDK retry cannot duplicate an order."""


class MCPAmbiguousFailure(PaymentExecutionError):
    """The request may have reached Razorpay; retrying could duplicate an order."""


class MCPRequestRejected(PaymentExecutionError):
    """Razorpay/MCP rejected the request; another transport must not retry it."""


class PaymentExecutor(Protocol):
    def create_order(self, *, amount_rupees: float, currency: str, receipt: str) -> dict[str, Any]: ...


def rupees_to_minor_units(amount_rupees: float) -> int:
    amount = Decimal(str(amount_rupees))
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _normalize_order(raw: dict[str, Any]) -> dict[str, Any]:
    order_id = raw.get("id")
    if not isinstance(order_id, str) or not order_id.startswith("order_"):
        raise MCPAmbiguousFailure("Razorpay MCP returned an invalid order response")
    return {
        "id": order_id,
        "amount": raw.get("amount"),
        "currency": raw.get("currency"),
        "status": raw.get("status"),
        "receipt": raw.get("receipt"),
    }


@dataclass
class RazorpaySDKExecutor:
    creator: Callable[..., dict[str, Any]]

    def create_order(self, *, amount_rupees: float, currency: str, receipt: str) -> dict[str, Any]:
        if currency != "INR":
            raise PaymentExecutionError("Native Razorpay orders require INR")
        raw = self.creator(amount_rupees=amount_rupees, receipt=receipt)
        return {
            "id": raw["id"],
            "amount": raw.get("amount", rupees_to_minor_units(amount_rupees)),
            "currency": raw.get("currency", currency),
            "status": raw.get("status", "created"),
            "receipt": raw.get("receipt", receipt),
        }


class RazorpayMCPExecutor:
    def __init__(
        self,
        *,
        key_id: str | None = None,
        key_secret: str | None = None,
        url: str = RAZORPAY_MCP_URL,
        tool_caller: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
    ) -> None:
        self._key_id = key_id
        self._key_secret = key_secret
        self._url = url
        self._tool_caller = tool_caller

    def _credentials(self) -> tuple[str, str]:
        key_id = self._key_id or os.getenv("RAZORPAY_KEY_ID")
        secret = self._key_secret or os.getenv("RAZORPAY_KEY_SECRET")
        if not key_id or not secret:
            raise MCPTransportUnavailable("Razorpay MCP credentials are not configured")
        if not key_id.startswith("rzp_test_"):
            raise MCPRequestRejected("Razorpay MCP requires Test Mode credentials")
        return key_id, secret

    def _headers(self) -> dict[str, str]:
        key_id, secret = self._credentials()
        token = base64.b64encode(f"{key_id}:{secret}".encode()).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def create_order(self, *, amount_rupees: float, currency: str, receipt: str) -> dict[str, Any]:
        arguments = {
            "amount": rupees_to_minor_units(amount_rupees),
            "currency": currency,
            "receipt": receipt,
        }
        if set(arguments) != _ALLOWED_ARGUMENTS:
            raise MCPRequestRejected("Unsafe Razorpay MCP order fields")
        caller = self._tool_caller or self._call_remote
        raw = caller(RAZORPAY_CREATE_ORDER_TOOL, arguments, self._headers())
        return _normalize_order(raw)

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Narrow testable boundary that rejects every tool except create_order."""
        if tool != RAZORPAY_CREATE_ORDER_TOOL:
            raise MCPRequestRejected("Razorpay MCP tool is not allowed")
        if set(arguments) != _ALLOWED_ARGUMENTS:
            raise MCPRequestRejected("Unsafe Razorpay MCP order fields")
        caller = self._tool_caller or self._call_remote
        return caller(tool, arguments, self._headers())

    def _call_remote(self, tool: str, arguments: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        try:
            return asyncio.run(self._call_remote_async(tool, arguments, headers))
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise MCPTransportUnavailable("Razorpay MCP is unavailable") from exc
        except (httpx.ReadTimeout, httpx.WriteError, httpx.ReadError) as exc:
            raise MCPAmbiguousFailure("Razorpay MCP result is uncertain") from exc
        except (MCPTransportUnavailable, MCPAmbiguousFailure, MCPRequestRejected):
            raise
        except Exception as exc:
            raise MCPAmbiguousFailure("Razorpay MCP request failed safely") from exc

    async def _call_remote_async(
        self, tool: str, arguments: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(headers=headers, timeout=15.0) as http_client:
            async with streamable_http_client(self._url, http_client=http_client) as streams:
                read_stream, write_stream, *_ = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments)
        return self._parse_call_tool_result(result)

    @staticmethod
    def _parse_call_tool_result(result: CallToolResult) -> dict[str, Any]:
        """Decode the installed Python MCP SDK model without relying on JSON aliases."""
        if result.is_error:
            raise MCPRequestRejected("Razorpay rejected the order request")

        structured = result.structured_content
        if isinstance(structured, dict):
            return RazorpayMCPExecutor._unwrap_order_payload(structured)
        for item in result.content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return RazorpayMCPExecutor._unwrap_order_payload(parsed)
        raise MCPAmbiguousFailure("Razorpay MCP returned an invalid order response")

    @staticmethod
    def _unwrap_order_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Accept a direct order or the MCP server's documented result envelope."""
        candidate = payload.get("result", payload)
        if isinstance(candidate, dict):
            return candidate
        raise MCPAmbiguousFailure("Razorpay MCP returned an invalid order response")


@dataclass
class RazorpayPaymentExecutor:
    primary: PaymentExecutor
    fallback: PaymentExecutor

    def create_order(self, *, amount_rupees: float, currency: str, receipt: str) -> dict[str, Any]:
        try:
            result = self.primary.create_order(
                amount_rupees=amount_rupees, currency=currency, receipt=receipt
            )
            return {**result, "payment_executor": "razorpay_mcp"}
        except MCPTransportUnavailable:
            result = self.fallback.create_order(
                amount_rupees=amount_rupees, currency=currency, receipt=receipt
            )
            return {**result, "payment_executor": "razorpay_sdk", "payment_executor_fallback": True}


def build_payment_executor(sdk_creator: Callable[..., dict[str, Any]]) -> RazorpayPaymentExecutor:
    return RazorpayPaymentExecutor(
        primary=RazorpayMCPExecutor(),
        fallback=RazorpaySDKExecutor(sdk_creator),
    )
