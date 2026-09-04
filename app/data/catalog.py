from app.models.product import Product


catalog = [
    Product(
        sku="SKIN001",
        name="Vitamin C Serum",
        category="Skincare",
        description="10% Vitamin C brightening serum",
        price=699.0,
        stock=15,
        attributes={
            "size": "30ml",
            "skin_type": "all"
        }
    ),

    Product(
        sku="SKIN002",
        name="Gentle Face Wash",
        category="Skincare",
        description="Daily gentle cleanser",
        price=399.0,
        stock=25,
        attributes={
            "size": "100ml",
            "skin_type": "sensitive"
        }
    ),

    Product(
        sku="SKIN003",
        name="Hydrating Moisturizer",
        category="Skincare",
        description="Lightweight daily moisturizer",
        price=599.0,
        stock=8,
        attributes={
            "size": "50g"
        }
    ),
]
