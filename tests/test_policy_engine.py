from dataclasses import dataclass

from app.services.policy_engine import PolicyDecision, evaluate_order_policy


@dataclass
class CatalogProduct:
    sku: str = "SKU-001"
    price: float = 500.0
    stock: int = 30


def evaluate(product: CatalogProduct, quantity: int, unit_price: float | None = None):
    return evaluate_order_policy(
        sku=product.sku,
        quantity=quantity,
        unit_price=product.price if unit_price is None else unit_price,
        catalog_product=product,
    )


def test_normal_purchase_is_approved():
    result = evaluate(CatalogProduct(), quantity=4)

    assert result == {
        "decision": PolicyDecision.APPROVED,
        "reason": "Order satisfies automatic purchase policy",
        "calculated_total": 2000.0,
    }


def test_purchase_over_auto_approve_limit_requires_confirmation():
    result = evaluate(CatalogProduct(), quantity=5)

    assert result == {
        "decision": PolicyDecision.REQUIRES_CONFIRMATION,
        "reason": "Human confirmation required",
        "calculated_total": 2500.0,
    }


def test_purchase_over_maximum_spend_limit_is_blocked():
    product = CatalogProduct(price=5500.0)

    result = evaluate(product, quantity=2)

    assert result == {
        "decision": PolicyDecision.BLOCKED,
        "reason": "Order exceeds maximum spend limit",
        "calculated_total": 11000.0,
    }


def test_invalid_quantity_is_blocked():
    result = evaluate(CatalogProduct(), quantity=0)

    assert result["decision"] == PolicyDecision.BLOCKED
    assert result["reason"] == "Quantity must be greater than 0"


def test_price_mismatch_is_blocked():
    result = evaluate(CatalogProduct(), quantity=1, unit_price=499.0)

    assert result["decision"] == PolicyDecision.BLOCKED
    assert result["reason"] == "Price validation failed"


def test_insufficient_stock_is_blocked():
    result = evaluate(CatalogProduct(stock=1), quantity=2)

    assert result["decision"] == PolicyDecision.BLOCKED
    assert result["reason"] == "Insufficient stock"
