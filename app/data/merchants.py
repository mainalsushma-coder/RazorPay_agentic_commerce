from typing import TypedDict

from app.data.catalog import catalog as glowcare_catalog
from app.models.merchant import Merchant
from app.models.product import Product


class MerchantRegistryEntry(TypedDict):
    merchant: Merchant
    catalog: list[Product]


techhub_catalog = [
    Product(
        sku="TECH001",
        name="Wireless Mechanical Keyboard",
        category="Electronics",
        description="Compact wireless mechanical keyboard",
        price=3499.0,
        stock=12,
        attributes={
            "connectivity": "Bluetooth/2.4GHz",
            "layout": "75%",
        },
    ),
    Product(
        sku="TECH002",
        name="Wireless Mouse",
        category="Electronics",
        description="Comfortable wireless mouse for everyday use",
        price=1299.0,
        stock=20,
        attributes={
            "connectivity": "Bluetooth",
            "dpi": 1600,
        },
    ),
    Product(
        sku="TECH003",
        name="USB-C Hub",
        category="Electronics",
        description="Multi-port USB-C hub for laptops and tablets",
        price=1999.0,
        stock=10,
        attributes={
            "ports": ["HDMI", "USB-A", "USB-C"],
            "power_delivery": "100W",
        },
    ),
]


merchant_registry: dict[str, MerchantRegistryEntry] = {
    "glowcare": {
        "merchant": Merchant(
            merchant_id="glowcare",
            name="GlowCare",
            description="Everyday skincare for simple, effective routines",
            category="Skincare",
            agent_ready=True,
        ),
        "catalog": glowcare_catalog,
    },
    "techhub": {
        "merchant": Merchant(
            merchant_id="techhub",
            name="TechHub",
            description="Practical electronics and desk accessories",
            category="Electronics",
            agent_ready=True,
        ),
        "catalog": techhub_catalog,
    },
}


def get_merchant_catalog(merchant_id: str) -> list[Product] | None:
    entry = merchant_registry.get(merchant_id)
    return entry["catalog"] if entry is not None else None
