from app.data.catalog import catalog as glowcare_catalog
from app.models.merchant import Merchant
from app.models.product import Product


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


glowcare_merchant = Merchant(
            merchant_id="glowcare",
            name="GlowCare",
            description="Everyday skincare for simple, effective routines",
            category="Skincare",
            agent_ready=True,
        )
techhub_merchant = Merchant(
            merchant_id="techhub",
            name="TechHub",
            description="Practical electronics and desk accessories",
            category="Electronics",
            agent_ready=True,
        )

seed_merchants = [
    (glowcare_merchant, glowcare_catalog),
    (techhub_merchant, techhub_catalog),
]

# External merchants are deliberately not seeded into CatalogRepository. Their
# product truth remains at the source and is fetched only through its official
# commerce interface.
external_merchants = [
    Merchant(
        merchant_id="bound-commerce-test-shopify",
        name="BOUND Commerce Test",
        description="Live development-store catalog connected through Shopify",
        category="Sporting Goods",
        agent_ready=True,
        source="shopify",
        source_config={"store_domain": "bound-commerce-test.myshopify.com"},
    )
]

# Compatibility view for older callers/tests. New application code uses the repository.
merchant_registry = {
    merchant.merchant_id: {"merchant": merchant, "catalog": products}
    for merchant, products in seed_merchants
}


def get_merchant_catalog(merchant_id: str) -> list[Product] | None:
    from app.repositories.catalog_repository import catalog_repository
    return catalog_repository.get_catalog(merchant_id)
