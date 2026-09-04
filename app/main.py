from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.data.catalog import catalog
from app.data.raw_catalog import raw_catalog
from app.models.order import OrderRequest
from app.models.readiness import MerchantResolutionRequest
from app.services.audit_service import get_audit_logs, log_policy_decision
from app.services.catalog_repair_service import repair_catalog
from app.services.catalog_resolution_service import (
    CatalogResolutionError,
    apply_merchant_resolutions,
)
from app.services.order_service import (
    OrderServiceError,
    create_order as create_guarded_order,
    orders,
)
from app.services.policy_engine import MAX_SPEND_LIMIT
from app.services.readiness_service import scan_catalog_readiness
from app.services.razorpay_service import create_razorpay_order


app = FastAPI(
    title="Agent Storefront Autopilot",
    version="0.1.0"
)

@app.get("/")
def root():
    return {
        "message": "Agent Storefront Autopilot API is running"
    }


@app.get("/merchant/readiness")
def merchant_readiness():
    return scan_catalog_readiness(raw_catalog)


@app.get("/merchant/readiness/repair-preview")
def merchant_readiness_repair_preview():
    before = scan_catalog_readiness(raw_catalog)
    repair_result = repair_catalog(raw_catalog)
    repaired_catalog = repair_result["catalog"]
    after = scan_catalog_readiness(repaired_catalog)
    return {
        "before": before,
        "after": after,
        "repairs": repair_result["repairs"],
        "unresolved_issues": repair_result["unresolved_issues"],
        "repaired_catalog": repaired_catalog,
    }


@app.post("/merchant/readiness/resolve-preview")
def merchant_readiness_resolve_preview(request: MerchantResolutionRequest):
    before = scan_catalog_readiness(raw_catalog)
    repair_result = repair_catalog(raw_catalog)
    repaired_catalog = repair_result["catalog"]
    after_autopilot = scan_catalog_readiness(repaired_catalog)

    try:
        resolution_result = apply_merchant_resolutions(
            repaired_catalog,
            repair_result["unresolved_issues"],
            [resolution.model_dump() for resolution in request.resolutions],
        )
    except CatalogResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved_catalog = resolution_result["catalog"]
    final = scan_catalog_readiness(resolved_catalog)
    return {
        "before": before,
        "after_autopilot": after_autopilot,
        "final": final,
        "repairs": repair_result["repairs"],
        "merchant_resolutions": resolution_result["merchant_resolutions"],
        "remaining_unresolved_issues": resolution_result[
            "remaining_unresolved_issues"
        ],
        "resolved_catalog": resolved_catalog,
    }


@app.get("/products")
def get_products():
    return catalog


@app.get("/products/search")
def search_products(q: str):
    q = q.lower()

    results = [
        product
        for product in catalog
        if q in product.name.lower()
        or q in product.category.lower()
        or q in product.description.lower()
    ]

    return results


@app.get("/inventory/{sku}")
def check_inventory(sku: str):
    for product in catalog:
        if product.sku == sku:

            stock = (
                int(product.stock)
                if isinstance(product.stock, str)
                else product.stock
            )

            return {
                "sku": product.sku,
                "name": product.name,
                "stock": stock,
                "available": stock > 0
            }

    raise HTTPException(
        status_code=404,
        detail="Product not found"
    )


@app.post("/orders")
def create_order(order_req: OrderRequest):
    try:
        result = create_guarded_order(
            sku=order_req.sku,
            quantity=order_req.quantity,
            payment_order_creator=create_razorpay_order,
        )
    except OrderServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc

    if result.get("decision") == "blocked":
        return JSONResponse(
            status_code=403,
            content=result,
        )
    return result


@app.get("/audit")
def audit():
    return get_audit_logs()


@app.get("/orders/{order_id}")
def get_order(order_id: str):

    if order_id in orders:
        return orders[order_id]

    raise HTTPException(
        status_code=404,
        detail="Order not found"
    )


@app.post("/orders/{order_id}/confirm")
def confirm_order(order_id: str):
    if order_id not in orders:
        raise HTTPException(
            status_code=404,
            detail="Order not found"
        )

    order = orders[order_id]
    if order["status"] != "requires_confirmation":
        raise HTTPException(
            status_code=400,
            detail="Order does not require confirmation"
        )

    product = None
    for p in catalog:
        if p.sku == order["sku"]:
            product = p
            break

    if product is None:
        raise HTTPException(
            status_code=400,
            detail="Product not found"
        )

    quantity = order["quantity"]
    if quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be greater than zero"
        )

    stock = int(product.stock)
    if stock < quantity:
        raise HTTPException(
            status_code=400,
            detail="Insufficient stock"
        )

    unit_price = float(product.price)
    total = unit_price * quantity
    if total > MAX_SPEND_LIMIT:
        raise HTTPException(
            status_code=403,
            detail="Order exceeds maximum spend limit"
        )

    razorpay_order = create_razorpay_order(
        amount_rupees=total,
        receipt=order_id,
    )

    order.update({
        "razorpay_order_id": razorpay_order["id"],
        "product_name": product.name,
        "unit_price": unit_price,
        "total": total,
        "currency": product.currency,
        "status": "created",
    })

    log_policy_decision(
        sku=product.sku,
        quantity=quantity,
        total=total,
        decision="human_confirmed",
        reason="Human confirmed order above automatic approval limit",
        order_id=order_id,
        razorpay_order_id=razorpay_order["id"],
    )

    return order
