"""Authoritative active-catalog boundary.

The prototype uses memory; a PostgreSQL implementation can replace this object
without changing buyers, MCP, policy, or order code.
"""

from typing import Protocol

from app.models.merchant import Merchant
from app.models.product import Product


class CatalogRepository(Protocol):
    def list_merchants(self) -> list[Merchant]: ...
    def get_merchant(self, merchant_id: str) -> Merchant | None: ...
    def create_merchant(self, merchant: Merchant) -> Merchant: ...
    def get_catalog(self, merchant_id: str) -> list[Product] | None: ...
    def find_product(self, merchant_id: str, sku: str) -> Product | None: ...
    def search_products(self, merchant_id: str, query: str) -> list[Product] | None: ...
    def replace_catalog(self, merchant_id: str, products: list[Product]) -> None: ...


class CatalogRepositoryError(ValueError):
    pass


class InMemoryCatalogRepository:
    def __init__(self, merchants: list[tuple[Merchant, list[Product]]]):
        self._merchants = {m.merchant_id: m.model_copy(deep=True) for m, _ in merchants}
        self._catalogs = {m.merchant_id: [p.model_copy(deep=True) for p in products] for m, products in merchants}

    def list_merchants(self) -> list[Merchant]:
        return [m.model_copy(deep=True) for m in self._merchants.values()]

    def get_merchant(self, merchant_id: str) -> Merchant | None:
        merchant = self._merchants.get(merchant_id)
        return merchant.model_copy(deep=True) if merchant else None

    def create_merchant(self, merchant: Merchant) -> Merchant:
        if merchant.merchant_id in self._merchants:
            raise CatalogRepositoryError("Merchant already exists")
        self._merchants[merchant.merchant_id] = merchant.model_copy(deep=True)
        self._catalogs[merchant.merchant_id] = []
        return merchant.model_copy(deep=True)

    def get_catalog(self, merchant_id: str) -> list[Product] | None:
        catalog = self._catalogs.get(merchant_id)
        return [p.model_copy(deep=True) for p in catalog] if catalog is not None else None

    def find_product(self, merchant_id: str, sku: str) -> Product | None:
        product = next((p for p in self._catalogs.get(merchant_id, []) if p.sku == sku), None)
        return product.model_copy(deep=True) if product else None

    def search_products(self, merchant_id: str, query: str) -> list[Product] | None:
        catalog = self._catalogs.get(merchant_id)
        if catalog is None:
            return None
        q = query.casefold()
        return [p.model_copy(deep=True) for p in catalog if any(q in str(v).casefold() for v in (
            p.sku, p.name, p.category, p.description,
            *p.attributes.keys(), *p.attributes.values(),
        ))]

    def replace_catalog(self, merchant_id: str, products: list[Product]) -> None:
        self._require_catalog(merchant_id)
        skus = [p.sku for p in products]
        if len(skus) != len(set(skus)):
            raise CatalogRepositoryError("Duplicate SKU within merchant catalog")
        self._catalogs[merchant_id] = [p.model_copy(deep=True) for p in products]

    def _require_catalog(self, merchant_id: str) -> list[Product]:
        if merchant_id not in self._catalogs:
            raise CatalogRepositoryError("Merchant not found")
        return self._catalogs[merchant_id]


# Imported after class definitions so seed modules remain simple data only.
from app.data.merchants import seed_merchants  # noqa: E402

catalog_repository: CatalogRepository = InMemoryCatalogRepository(seed_merchants)
