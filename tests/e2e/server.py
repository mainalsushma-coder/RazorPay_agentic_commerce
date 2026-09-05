"""Test-only ASGI entrypoint with deterministic external boundaries."""
from __future__ import annotations
import copy
import json
from typing import Any
import app.main as main
from app.data.merchants import seed_merchants
from app.models.chat import AgentChatResponse, AgentEvent
from app.repositories.catalog_repository import catalog_repository
from app.services.audit_service import audit_logs
from app.services.catalog_import_service import catalog_import_service
from app.services.order_service import orders

metrics: dict[str, Any] = {"payment_calls": [], "buyer_order_bodies": [], "confirm_requests": 0, "agent_requests": 0}

def fake_payment(amount_rupees: float, receipt: str) -> dict[str, Any]:
    metrics["payment_calls"].append({"amount_rupees": amount_rupees, "receipt": receipt})
    return {"id": "order_test_bound_001", "amount": round(amount_rupees * 100)}

async def fake_agent(message: str, *, merchant_id: str | None = None, conversation_history: list[Any] | None = None) -> AgentChatResponse:
    """Replace Qwen/MCP orchestration only; products still come from active truth."""
    metrics["agent_requests"] += 1
    query = message.casefold()
    if "snowboard" in query:
        from tests.test_shopify_commerce_source import PRODUCT
        from app.services.shopify_catalog_service import normalize_shopify_product
        product = normalize_shopify_product(PRODUCT, "bound-commerce-test-shopify").model_dump()
        product["image_url"] = None
        # Structured discovery may legitimately have no model prose.
        return AgentChatResponse(message="", products=[product])
    if "vitamin c" in query:
        merchant_id = "glowcare"
        products = catalog_repository.get_catalog(merchant_id) or []
        products = [p for p in products if p.sku == "SKIN001"]
        response = "I found **Vitamin C Serum**. <script>window.__BOUND_XSS__=true</script>"
    elif "keyboard" in query:
        merchant_id = "techhub"
        products = catalog_repository.get_catalog(merchant_id) or []
        products = [p for p in products if p.sku == "TECH001"]
        response = "I found the wireless mechanical keyboard."
    elif "blocked purchase" in query:
        merchant_id = "glowcare"
        order = main.create_guarded_order(
            merchant_id="glowcare", sku="SKIN001", quantity=15,
            payment_order_creator=fake_payment,
        )
        return AgentChatResponse(message="Bound Guardrails blocked the transaction.", merchant_id=merchant_id, order=order, events=[AgentEvent(type="policy", decision="blocked")])
    else:
        merchant_id, products = merchant_id or "", []
        response = f"Deterministic universal reply: {message}"
    structured = [{"merchant_id": merchant_id, **p.model_dump()} for p in products]
    order = None
    events = [AgentEvent(type="tool_call", tool="catalog_search", status="completed")]
    if "buy" in query and products:
        order = main.create_guarded_order(
            merchant_id=merchant_id, sku=products[0].sku, quantity=1,
            payment_order_creator=fake_payment,
        )
        events.extend([
            AgentEvent(type="tool_call", tool="create_order", status="completed"),
            AgentEvent(type="policy", decision=order.get("policy_decision") or order.get("decision")),
        ])
    return AgentChatResponse(message=response, merchant_id=merchant_id, products=structured, order=order, events=events)

main.create_razorpay_order = fake_payment
main.run_agent = fake_agent
app = main.app

@app.middleware("http")
async def observe_browser_intent(request, call_next):
    if request.url.path == "/buyer/orders" and request.method == "POST":
        metrics["buyer_order_bodies"].append(json.loads(await request.body()))
    if request.url.path.endswith("/confirm") and request.method == "POST":
        metrics["confirm_requests"] += 1
    return await call_next(request)

@app.post("/__e2e__/reset", include_in_schema=False)
def reset_e2e_state():
    for merchant, products in seed_merchants:
        catalog_repository.replace_catalog(merchant.merchant_id, [p.model_copy(deep=True) for p in products])
    catalog_import_service._imports.clear()
    orders.clear(); audit_logs.clear(); main._demo_import_id = None; main._confirmation_locks.clear()
    metrics.update(payment_calls=[], buyer_order_bodies=[], confirm_requests=0, agent_requests=0)
    return {"reset": True}

@app.get("/__e2e__/metrics", include_in_schema=False)
def e2e_metrics():
    return copy.deepcopy(metrics)
