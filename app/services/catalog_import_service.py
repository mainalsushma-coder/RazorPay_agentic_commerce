"""Shared CSV/JSON staging pipeline for merchant catalog onboarding."""

import copy
import csv
import io
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.models.product import Product
from app.repositories.catalog_repository import CatalogRepository, CatalogRepositoryError
from app.services.catalog_repair_service import repair_catalog
from app.services.catalog_resolution_service import CatalogResolutionError, apply_merchant_resolutions
from app.services.readiness_service import scan_catalog_readiness


class CatalogImportError(ValueError):
    pass


@dataclass
class StagedCatalog:
    merchant_id: str
    import_id: str
    catalog: list[dict[str, Any]]
    repairs: list[dict[str, Any]] = field(default_factory=list)
    merchant_resolutions: list[dict[str, Any]] = field(default_factory=list)
    activated: bool = False


class CatalogImportService:
    def __init__(self) -> None:
        self._imports: dict[tuple[str, str], StagedCatalog] = {}

    def parse_csv(self, content: bytes) -> list[dict[str, Any]]:
        try:
            text = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames or "sku" not in reader.fieldnames:
                raise CatalogImportError("CSV must include a sku column")
            rows = []
            for number, row in enumerate(reader, start=2):
                if not any(str(v or "").strip() for v in row.values()):
                    continue
                record = {str(k).strip(): v for k, v in row.items() if k is not None}
                if record.get("attributes", "").strip():
                    try:
                        attributes = json.loads(record["attributes"])
                    except json.JSONDecodeError as exc:
                        raise CatalogImportError(f"Row {number} attributes must be valid JSON") from exc
                    if not isinstance(attributes, dict):
                        raise CatalogImportError(f"Row {number} attributes must be a JSON object")
                    record["attributes"] = attributes
                else:
                    record["attributes"] = {}
                rows.append(record)
        except UnicodeDecodeError as exc:
            raise CatalogImportError("CSV must be UTF-8 encoded") from exc
        if not rows:
            raise CatalogImportError("Catalog contains no usable rows")
        return rows

    def parse_json(self, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict) and "products" in value:
            value = value["products"]
        if not isinstance(value, list) or not value:
            raise CatalogImportError("JSON catalog must be a non-empty list of products")
        if not all(isinstance(item, dict) for item in value):
            raise CatalogImportError("Every JSON product must be an object")
        return copy.deepcopy(value)

    def stage(self, merchant_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        skus = [str(record.get("sku") or "").strip() for record in records]
        if any(not sku for sku in skus):
            raise CatalogImportError("Every imported product must have a non-empty SKU")
        if len(skus) != len(set(skus)):
            raise CatalogImportError("Duplicate SKU within merchant catalog")
        import_id = str(uuid.uuid4())
        staged = StagedCatalog(merchant_id, import_id, copy.deepcopy(records))
        self._imports[(merchant_id, import_id)] = staged
        return self.summary(staged)

    def get(self, merchant_id: str, import_id: str) -> StagedCatalog:
        staged = self._imports.get((merchant_id, import_id))
        if staged is None:
            raise CatalogImportError("Catalog import not found")
        return staged

    def summary(self, staged: StagedCatalog) -> dict[str, Any]:
        readiness = scan_catalog_readiness(staged.catalog)
        return {
            "merchant_id": staged.merchant_id,
            "import_id": staged.import_id,
            "products_detected": len(staged.catalog),
            "readiness": readiness,
            "fatal_errors": [],
            "issues": readiness["issues"],
            "activated": staged.activated,
        }

    def repair(self, merchant_id: str, import_id: str) -> dict[str, Any]:
        staged = self.get(merchant_id, import_id)
        before = scan_catalog_readiness(staged.catalog)
        result = repair_catalog(staged.catalog)
        staged.catalog = result["catalog"]
        staged.repairs.extend(result["repairs"])
        return {"before": before, "after": scan_catalog_readiness(staged.catalog), **result}

    def resolve(self, merchant_id: str, import_id: str, resolutions: list[dict[str, Any]]) -> dict[str, Any]:
        staged = self.get(merchant_id, import_id)
        unresolved = repair_catalog(staged.catalog)["unresolved_issues"]
        try:
            result = apply_merchant_resolutions(staged.catalog, unresolved, resolutions)
        except CatalogResolutionError:
            raise
        staged.catalog = result["catalog"]
        staged.merchant_resolutions.extend(result["merchant_resolutions"])
        return {**result, "final": scan_catalog_readiness(staged.catalog)}

    def activate(self, merchant_id: str, import_id: str, repository: CatalogRepository) -> dict[str, Any]:
        staged = self.get(merchant_id, import_id)
        report = scan_catalog_readiness(staged.catalog)
        if report["readiness_score"] != 100 or report["issue_count"]:
            raise CatalogImportError("Catalog must reach 100% readiness before activation")
        skus = [str(item.get("sku", "")).strip() for item in staged.catalog]
        if len(skus) != len(set(skus)):
            raise CatalogImportError("Duplicate SKU within merchant catalog")
        try:
            products = [Product.model_validate(item) for item in staged.catalog]
            repository.replace_catalog(merchant_id, products)
        except ValidationError as exc:
            raise CatalogImportError(f"Catalog failed authoritative validation: {exc.errors()[0]['msg']}") from exc
        except CatalogRepositoryError as exc:
            raise CatalogImportError(str(exc)) from exc
        staged.activated = True
        return {"merchant_id": merchant_id, "import_id": import_id, "activated": True, "products_activated": len(products)}


catalog_import_service = CatalogImportService()
