import base64

import pytest
from mcp.types import CallToolResult, TextContent

from app.services import order_service
from app.services.audit_service import audit_logs
from app.services.payment_executor import (
    MCPAmbiguousFailure,
    MCPRequestRejected,
    MCPTransportUnavailable,
    RAZORPAY_CREATE_ORDER_TOOL,
    RazorpayMCPExecutor,
    RazorpayPaymentExecutor,
    RazorpaySDKExecutor,
)


def test_mcp_is_hard_bound_to_create_order_and_minimal_authoritative_payload():
    calls = []

    def call(tool, arguments, headers):
        calls.append((tool, arguments, headers))
        return {
            "id": "order_mcp_1", "amount": arguments["amount"],
            "currency": arguments["currency"], "status": "created",
            "receipt": arguments["receipt"],
        }

    executor = RazorpayMCPExecutor(
        key_id="rzp_test_public", key_secret="private-secret", tool_caller=call
    )
    result = executor.create_order(amount_rupees=699, currency="INR", receipt="bound-1")

    assert calls[0][0] == RAZORPAY_CREATE_ORDER_TOOL == "create_order"
    assert calls[0][1] == {"amount": 69900, "currency": "INR", "receipt": "bound-1"}
    assert result == {
        "id": "order_mcp_1", "amount": 69900, "currency": "INR",
        "status": "created", "receipt": "bound-1",
    }
    authorization = calls[0][2]["Authorization"]
    assert authorization == "Basic " + base64.b64encode(
        b"rzp_test_public:private-secret"
    ).decode("ascii")


def test_executor_rejects_every_other_tool_and_unknown_fields():
    executor = RazorpayMCPExecutor(
        key_id="rzp_test_public", key_secret="secret", tool_caller=lambda *_: {}
    )
    with pytest.raises(MCPRequestRejected):
        executor.call_tool("capture_payment", {})
    with pytest.raises(MCPRequestRejected):
        executor.call_tool("create_order", {
            "amount": 69900, "currency": "INR", "receipt": "x", "notes": {},
        })


def test_only_pre_send_transport_failure_falls_back_to_sdk():
    sdk_calls = []

    class Unavailable:
        def create_order(self, **_):
            raise MCPTransportUnavailable("unavailable")

    executor = RazorpayPaymentExecutor(
        primary=Unavailable(),
        fallback=RazorpaySDKExecutor(
            lambda **kwargs: sdk_calls.append(kwargs) or {"id": "order_sdk_1"}
        ),
    )
    result = executor.create_order(amount_rupees=699, currency="INR", receipt="bound-1")
    assert result["payment_executor"] == "razorpay_sdk"
    assert sdk_calls == [{"amount_rupees": 699, "receipt": "bound-1"}]


def test_real_call_tool_result_shape_is_normalized_without_sdk_fallback(monkeypatch):
    sdk_calls = []
    mcp_result = CallToolResult(
        content=[],
        structuredContent={"result": {
            "id": "order_mcp_real_shape", "amount": 69900,
            "currency": "INR", "status": "created", "receipt": "bound-1",
        }},
    )
    primary = RazorpayMCPExecutor(key_id="rzp_test_public", key_secret="secret")
    monkeypatch.setattr(
        primary, "_call_remote",
        lambda *_: primary._parse_call_tool_result(mcp_result),
    )
    executor = RazorpayPaymentExecutor(
        primary=primary,
        fallback=RazorpaySDKExecutor(lambda **kwargs: sdk_calls.append(kwargs)),
    )

    result = executor.create_order(amount_rupees=699, currency="INR", receipt="bound-1")

    assert not hasattr(mcp_result, "isError")
    assert mcp_result.is_error is False
    assert result == {
        "id": "order_mcp_real_shape", "amount": 69900, "currency": "INR",
        "status": "created", "receipt": "bound-1",
        "payment_executor": "razorpay_mcp",
    }
    assert sdk_calls == []


def test_real_call_tool_result_text_json_is_supported():
    result = CallToolResult(content=[TextContent(
        type="text",
        text='{"id":"order_text_1","amount":69900,"currency":"INR",'
             '"status":"created","receipt":"bound-1"}',
    )])

    assert RazorpayMCPExecutor._parse_call_tool_result(result)["id"] == "order_text_1"


def test_real_call_tool_result_error_representation_is_rejected():
    result = CallToolResult(
        content=[TextContent(type="text", text='{"error":"bad request"}')],
        isError=True,
    )

    assert result.is_error is True
    assert not hasattr(result, "isError")
    with pytest.raises(MCPRequestRejected, match="rejected"):
        RazorpayMCPExecutor._parse_call_tool_result(result)


@pytest.mark.parametrize("failure", [MCPRequestRejected("invalid"), MCPAmbiguousFailure("unknown")])
def test_rejected_or_ambiguous_mcp_failure_never_retries_sdk(failure):
    class Failed:
        def create_order(self, **_):
            raise failure

    executor = RazorpayPaymentExecutor(
        primary=Failed(),
        fallback=RazorpaySDKExecutor(lambda **_: pytest.fail("unsafe SDK retry")),
    )
    with pytest.raises(type(failure), match=str(failure)):
        executor.create_order(amount_rupees=699, currency="INR", receipt="bound-1")


def test_live_credentials_are_refused_without_exposing_them():
    secret = "never-show-this"
    executor = RazorpayMCPExecutor(key_id="rzp_live_public", key_secret=secret)
    with pytest.raises(MCPRequestRejected) as caught:
        executor.create_order(amount_rupees=699, currency="INR", receipt="bound-1")
    assert secret not in str(caught.value)


def test_approved_native_order_passes_only_authoritative_values_to_executor():
    calls = []

    class RecordingExecutor:
        def create_order(self, **kwargs):
            calls.append(kwargs)
            return {
                "id": "order_mcp_authoritative", "amount": 69900,
                "currency": "INR", "status": "created", "receipt": kwargs["receipt"],
                "payment_executor": "razorpay_mcp",
            }

    audit_logs.clear()
    order_service.orders.clear()
    result = order_service.create_order(
        "SKIN001", 1, merchant_id="glowcare", payment_executor=RecordingExecutor()
    )

    assert calls == [{
        "amount_rupees": 699.0, "currency": "INR", "receipt": result["order_id"],
    }]
    assert result["payment_executor"] == "razorpay_mcp"
    assert audit_logs[-1]["payment_executor"] == "razorpay_mcp"
