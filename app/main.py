from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.data.catalog import catalog
from app.data.raw_catalog import raw_catalog
from app.models.order import DeterministicOrderRequest, OrderRequest
from app.models.product import Product
from app.models.merchant import Merchant
from app.models.chat import AgentChatRequest, AgentChatResponse
from app.agent import run_agent
from app.models.readiness import MerchantResolutionRequest
from app.services.audit_service import get_audit_logs, log_audit_event, log_policy_decision
from app.services.catalog_resolution_service import CatalogResolutionError
from app.services.order_service import (
    OrderServiceError,
    create_order as create_guarded_order,
    orders,
)
from app.services.policy_engine import AUTO_APPROVE_LIMIT, MAX_SPEND_LIMIT
from app.services.readiness_service import scan_catalog_readiness
from app.services.razorpay_service import create_razorpay_order
from app.services.payment_executor import build_payment_executor
from app.repositories.catalog_repository import CatalogRepositoryError, catalog_repository
from app.services.catalog_import_service import CatalogImportError, catalog_import_service
from app.services.commerce_catalog_service import get_commerce_merchant, list_commerce_merchants


app = FastAPI(
    title="Agent Storefront Autopilot",
    version="0.1.0"
)

_DEFAULT_SDK_CREATOR = create_razorpay_order

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_demo_import_id: str | None = None
_confirmation_locks: dict[str, Lock] = {}
_confirmation_locks_guard = Lock()


def _new_demo_import() -> str:
    global _demo_import_id
    _demo_import_id = catalog_import_service.stage("glowcare", raw_catalog)["import_id"]
    return _demo_import_id


def _demo_import() -> str:
    return _demo_import_id or _new_demo_import()


def _order_lock(order_id: str) -> Lock:
    with _confirmation_locks_guard:
        return _confirmation_locks.setdefault(order_id, Lock())


@app.post("/agent/chat", response_model=AgentChatResponse)
async def agent_chat(request: AgentChatRequest):
    if (
        request.merchant_id is not None
        and get_commerce_merchant(request.merchant_id) is None
    ):
        raise HTTPException(status_code=404, detail="Merchant not found")
    try:
        return await run_agent(
            request.message,
            merchant_id=request.merchant_id,
            conversation_history=[item.model_dump() for item in request.conversation_history],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The shopping agent is temporarily unavailable",
        ) from exc

@app.get("/")
def root():
    return {
        "message": "Agent Storefront Autopilot API is running"
    }


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
def login():
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/buyer-login", include_in_schema=False)
def buyer_login():
    return FileResponse(STATIC_DIR / "buyer-login.html")


@app.get("/merchant-login", include_in_schema=False)
def merchant_login():
    return FileResponse(STATIC_DIR / "merchant-login.html")


@app.get("/profile", include_in_schema=False)
def buyer_profile():
    return FileResponse(STATIC_DIR / "profile.html")


@app.get("/buyer/mandate")
def buyer_mandate():
    """Read-only metadata for the demo buyer's authoritative purchase policy."""
    return {
        "label": "Current demo mandate",
        "currency": "INR",
        "automatic_purchase_limit": AUTO_APPROVE_LIMIT,
        "maximum_transaction": MAX_SPEND_LIMIT,
        "above_automatic_limit": "requires_confirmation",
        "above_maximum_transaction": "blocked",
    }


@app.get("/orders", include_in_schema=False)
def buyer_orders_page():
    return FileResponse(STATIC_DIR / "orders.html")


@app.get("/buyer/order-history")
def buyer_order_history():
    from app.services.order_history_service import order_history
    return order_history()


@app.get("/buyer/activity")
def buyer_activity():
    """Return only real, current-runtime order activity for the buyer UI."""
    return list(reversed(list(orders.values())))


@app.get("/merchant-portal", include_in_schema=False)
def merchant_portal():
    return FileResponse(STATIC_DIR / "merchant-portal.html")


@app.get("/merchant/readiness")
def merchant_readiness():
    staged = catalog_import_service.get("glowcare", _new_demo_import())
    return catalog_import_service.summary(staged)["readiness"]


@app.get("/merchant/readiness/repair-preview")
def merchant_readiness_repair_preview():
    import_id = _new_demo_import()
    result = catalog_import_service.repair("glowcare", import_id)
    return {**result, "import_id": import_id, "repaired_catalog": result["catalog"]}


@app.post("/merchant/readiness/resolve-preview")
def merchant_readiness_resolve_preview(request: MerchantResolutionRequest):
    try:
        import_id = _demo_import()
        staged = catalog_import_service.get("glowcare", import_id)
        before = scan_catalog_readiness(raw_catalog)
        if not staged.repairs:
            catalog_import_service.repair("glowcare", import_id)
        after_autopilot = scan_catalog_readiness(staged.catalog)
        resolution_result = catalog_import_service.resolve(
            "glowcare", import_id,
            [resolution.model_dump() for resolution in request.resolutions],
        )
    except CatalogResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved_catalog = resolution_result["catalog"]
    final = resolution_result["final"]
    return {
        "before": before,
        "after_autopilot": after_autopilot,
        "final": final,
        "repairs": staged.repairs,
        "merchant_resolutions": resolution_result["merchant_resolutions"],
        "remaining_unresolved_issues": resolution_result[
            "remaining_unresolved_issues"
        ],
        "resolved_catalog": resolved_catalog,
        "import_id": import_id,
    }


@app.post("/merchant/readiness/activate")
def activate_demo_readiness():
    try:
        return catalog_import_service.activate(
            "glowcare", _demo_import(), catalog_repository
        )
    except CatalogImportError as exc:
        _import_error(exc, 409)


@app.get("/products", deprecated=True)
def get_products():
    return catalog_repository.get_catalog("glowcare") or []


@app.get("/merchants")
def get_merchants():
    return list_commerce_merchants()


@app.post("/merchants", status_code=201)
def create_merchant(merchant: Merchant):
    try:
        return catalog_repository.create_merchant(merchant)
    except CatalogRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/merchants/{merchant_id}/products")
def get_merchant_products(merchant_id: str):
    merchant_catalog = catalog_repository.get_catalog(merchant_id)
    if merchant_catalog is None:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return merchant_catalog


@app.get("/merchants/{merchant_id}/products/search")
def search_merchant_products(merchant_id: str, q: str):
    merchant_catalog = catalog_repository.search_products(merchant_id, q)
    if merchant_catalog is None:
        raise HTTPException(status_code=404, detail="Merchant not found")

    return merchant_catalog


@app.post("/merchants/{merchant_id}/products", status_code=202)
def add_merchant_product(merchant_id: str, product: Product):
    active = catalog_repository.get_catalog(merchant_id)
    if active is None:
        raise HTTPException(status_code=404, detail="Merchant not found")
    if any(item.sku == product.sku for item in active):
        raise HTTPException(status_code=409, detail="Duplicate SKU within merchant catalog")
    return catalog_import_service.stage(
        merchant_id, [p.model_dump() for p in active] + [product.model_dump()]
    )


@app.put("/merchants/{merchant_id}/products/{sku}")
def update_merchant_product(merchant_id: str, sku: str, product: Product):
    active = catalog_repository.get_catalog(merchant_id)
    if active is None:
        raise HTTPException(status_code=404, detail="Merchant not found")
    index = next((i for i, item in enumerate(active) if item.sku == sku), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.sku != sku and any(item.sku == product.sku for item in active):
        raise HTTPException(status_code=409, detail="Duplicate SKU within merchant catalog")
    records = [p.model_dump() for p in active]
    records[index] = product.model_dump()
    return catalog_import_service.stage(merchant_id, records)


def _import_error(exc: Exception, status_code: int = 400):
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.post("/merchants/{merchant_id}/catalog/import", status_code=201)
async def import_merchant_catalog(merchant_id: str, request: Request):
    if catalog_repository.get_merchant(merchant_id) is None:
        raise HTTPException(status_code=404, detail="Merchant not found")
    try:
        content_type = request.headers.get("content-type", "").lower()
        if "multipart/form-data" in content_type:
            form = await request.form()
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read"):
                raise CatalogImportError("A catalog file is required")
            content = await upload.read()
            filename = str(getattr(upload, "filename", "")).lower()
            if filename.endswith(".json"):
                try:
                    records = catalog_import_service.parse_json(__import__("json").loads(content.decode("utf-8-sig")))
                except (UnicodeDecodeError, ValueError) as exc:
                    raise CatalogImportError("JSON file is unreadable") from exc
            else:
                records = catalog_import_service.parse_csv(content)
        elif "application/json" in content_type:
            records = catalog_import_service.parse_json(await request.json())
        elif "text/csv" in content_type:
            records = catalog_import_service.parse_csv(await request.body())
        else:
            raise CatalogImportError("Use CSV or JSON catalog content")
        return catalog_import_service.stage(merchant_id, records)
    except CatalogImportError as exc:
        _import_error(exc)


@app.get("/merchants/{merchant_id}/catalog/imports/{import_id}/readiness")
def import_readiness(merchant_id: str, import_id: str):
    try:
        return catalog_import_service.summary(catalog_import_service.get(merchant_id, import_id))
    except CatalogImportError as exc:
        _import_error(exc, 404)


@app.post("/merchants/{merchant_id}/catalog/imports/{import_id}/repair-preview")
def import_repair(merchant_id: str, import_id: str):
    try:
        return catalog_import_service.repair(merchant_id, import_id)
    except CatalogImportError as exc:
        _import_error(exc, 404)


@app.post("/merchants/{merchant_id}/catalog/imports/{import_id}/resolve")
def import_resolve(merchant_id: str, import_id: str, request: MerchantResolutionRequest):
    try:
        return catalog_import_service.resolve(merchant_id, import_id, [r.model_dump() for r in request.resolutions])
    except CatalogImportError as exc:
        _import_error(exc, 404)
    except CatalogResolutionError as exc:
        _import_error(exc)


@app.post("/merchants/{merchant_id}/catalog/imports/{import_id}/activate")
def activate_import(merchant_id: str, import_id: str):
    try:
        return catalog_import_service.activate(merchant_id, import_id, catalog_repository)
    except CatalogImportError as exc:
        _import_error(exc, 409)


@app.get("/products/search", deprecated=True)
def search_products(q: str):
    return catalog_repository.search_products("glowcare", q) or []


@app.get("/inventory/{sku}", deprecated=True)
def check_inventory(sku: str):
    for product in catalog_repository.get_catalog("glowcare") or []:
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
        payment_override = (
            create_razorpay_order
            if create_razorpay_order is not _DEFAULT_SDK_CREATOR
            else None
        )
        result = create_guarded_order(
            merchant_id=order_req.merchant_id,
            sku=order_req.sku,
            quantity=order_req.quantity,
            payment_order_creator=payment_override,
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


@app.post("/buyer/orders")
def deterministic_buyer_order(order_req: DeterministicOrderRequest):
    """Execute an explicit product-card selection without LLM reinterpretation."""
    return create_order(OrderRequest(**order_req.model_dump()))


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
    with _order_lock(order_id):
        return _confirm_order_guarded(order_id)


def _confirm_order_guarded(order_id: str):
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

    product = catalog_repository.find_product(order["merchant_id"], order["sku"])

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

    try:
        unit_price = float(product.price)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Product price is invalid",
        ) from exc

    if unit_price != order["unit_price"]:
        raise HTTPException(
            status_code=409,
            detail="Product price changed; create a new order",
        )

    total = unit_price * quantity
    if total <= 0:
        raise HTTPException(
            status_code=400, detail="Payment amount must be greater than zero"
        )
    if total > MAX_SPEND_LIMIT:
        raise HTTPException(
            status_code=403,
            detail="Order exceeds maximum spend limit"
        )

    if create_razorpay_order is not _DEFAULT_SDK_CREATOR:
        from app.services.payment_executor import RazorpaySDKExecutor
        executor = RazorpaySDKExecutor(create_razorpay_order)
    else:
        executor = build_payment_executor(create_razorpay_order)
    try:
        razorpay_order = executor.create_order(
        amount_rupees=total,
        currency=product.currency,
        receipt=order_id,
        )
    except Exception:
        log_audit_event("payment_execution_failed", order_id=order_id)
        raise
    selected = razorpay_order.get("payment_executor", "razorpay_sdk")

    order.update({
        "razorpay_order_id": razorpay_order["id"],
        "product_name": product.name,
        "unit_price": unit_price,
        "total": total,
        "currency": product.currency,
        "status": "created",
        "payment_executor": selected,
    })

    log_policy_decision(
        sku=product.sku,
        quantity=quantity,
        total=total,
        decision="human_confirmed",
        reason="Human confirmed order above automatic approval limit",
        order_id=order_id,
        razorpay_order_id=razorpay_order["id"],
        payment_executor=selected,
        payment_executor_fallback=razorpay_order.get("payment_executor_fallback", False),
    )

    return order
