import uuid
from fastapi import FastAPI, HTTPException

from app.data.catalog import catalog
from app.models.order import OrderRequest


app = FastAPI(
    title="Agent Storefront Autopilot",
    version="0.1.0"
)

orders = {}


@app.get("/")
def root():
    return {
        "message": "Agent Storefront Autopilot API is running"
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
            return {
                "sku": product.sku,
                "name": product.name,
                "stock": product.stock,
                "available": int(product.stock) > 0 if isinstance(product.stock, str) else product.stock > 0
            }

    raise HTTPException(
        status_code=404,
        detail="Product not found"
    )


@app.post("/orders")
def create_order(order_req: OrderRequest):
    if order_req.quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be greater than zero"
        )

    product = None
    for p in catalog:
        if p.sku == order_req.sku:
            product = p
            break

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    stock = int(product.stock) if isinstance(product.stock, str) else product.stock
    if stock < order_req.quantity:
        raise HTTPException(
            status_code=400,
            detail="Insufficient stock"
        )

    order_id = str(uuid.uuid4())
    unit_price = float(product.price)
    total = unit_price * order_req.quantity

    order = {
        "order_id": order_id,
        "sku": product.sku,
        "product_name": product.name,
        "quantity": order_req.quantity,
        "unit_price": unit_price,
        "total": total,
        "currency": product.currency,
        "status": "created"
    }

    orders[order_id] = order
    return order


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    if order_id in orders:
        return orders[order_id]

    raise HTTPException(
        status_code=404,
        detail="Order not found"
    )