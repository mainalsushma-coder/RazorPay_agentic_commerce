import json

from fastapi.testclient import TestClient

import app.services.order_service as order_service
from app.main import app
from app.mcp_server import catalog_search, mcp
from app.repositories.catalog_repository import catalog_repository


client = TestClient(app)


def _clean_records(sku="NEW001", price=499, stock=7):
    return [{
        "sku": sku, "name": "Imported Product", "category": "General",
        "description": "Merchant supplied description", "price": price,
        "currency": "INR", "stock": stock, "attributes": {"color": "Blue"},
    }]


def test_json_import_is_staged_then_activates_into_all_active_consumers(monkeypatch):
    original = catalog_repository.get_catalog("techhub")
    try:
        preview = client.post("/merchants/techhub/catalog/import", json=_clean_records()).json()
        import_id = preview["import_id"]
        assert preview["readiness"]["readiness_score"] == 100
        assert catalog_search("techhub", "Imported Product") == []
        assert client.post("/orders", json={"merchant_id": "techhub", "sku": "NEW001", "quantity": 1}).status_code == 404

        activated = client.post(f"/merchants/techhub/catalog/imports/{import_id}/activate")
        assert activated.status_code == 200
        assert [p["sku"] for p in client.get("/merchants/techhub/products").json()] == ["NEW001"]
        assert [p["sku"] for p in catalog_search("techhub", "Imported Product")] == ["NEW001"]
        monkeypatch.setattr(order_service, "create_razorpay_order", lambda **kw: {"id": "order_imported"})
        order = order_service.create_order("NEW001", 1, merchant_id="techhub")
        assert order["unit_price"] == 499.0
    finally:
        catalog_repository.replace_catalog("techhub", original)


def test_messy_csv_uses_readiness_repair_resolution_and_activation():
    csv_data = 'sku,name,category,description,price,currency,stock,attributes\nMESSY1,Messy,General,,"899 INR",INR,"8","{}"\n'
    preview = client.post("/merchants/glowcare/catalog/import", files={"file": ("catalog.csv", csv_data, "text/csv")})
    assert preview.status_code == 201
    body = preview.json()
    assert body["readiness"]["readiness_score"] < 100
    repaired = client.post(f'/merchants/glowcare/catalog/imports/{body["import_id"]}/repair-preview').json()
    assert repaired["after"]["readiness_score"] > body["readiness"]["readiness_score"]
    assert {(i["sku"], i["field"]) for i in repaired["unresolved_issues"]} == {("MESSY1", "description")}
    assert client.post(f'/merchants/glowcare/catalog/imports/{body["import_id"]}/activate').status_code == 409
    resolved = client.post(f'/merchants/glowcare/catalog/imports/{body["import_id"]}/resolve', json={"resolutions": [{"sku": "MESSY1", "field": "description", "value": "Resolved by merchant"}]})
    assert resolved.json()["final"]["readiness_score"] == 100


def test_csv_attributes_and_shared_pipeline():
    csv_data = 'sku,name,category,description,price,currency,stock,attributes\nCSV1,Mouse,Electronics,Wireless mouse,1299,INR,4,"{""dpi"":1600}"\n'
    imported = client.post("/merchants/techhub/catalog/import", files={"file": ("clean.csv", csv_data, "text/csv")})
    assert imported.status_code == 201
    repaired = client.post(f'/merchants/techhub/catalog/imports/{imported.json()["import_id"]}/repair-preview').json()
    assert repaired["after"]["readiness_score"] == 100
    assert repaired["catalog"][0]["attributes"] == {"dpi": 1600}


def test_malformed_and_duplicate_imports_are_controlled_4xx():
    malformed = client.post("/merchants/glowcare/catalog/import", files={"file": ("bad.csv", "name,price\nThing,2", "text/csv")})
    duplicate = client.post("/merchants/glowcare/catalog/import", json=_clean_records("DUP") + _clean_records("DUP"))
    empty_json = client.post("/merchants/glowcare/catalog/import", content=json.dumps([]), headers={"content-type": "application/json"})
    assert malformed.status_code == duplicate.status_code == empty_json.status_code == 400


def test_negative_authoritative_values_cannot_activate():
    imported = client.post("/merchants/glowcare/catalog/import", json=_clean_records("NEG", price=-1)).json()
    assert imported["readiness"]["readiness_score"] < 100
    assert client.post(f'/merchants/glowcare/catalog/imports/{imported["import_id"]}/activate').status_code == 409


def test_product_management_validation_and_duplicate_sku():
    assert client.post("/merchants/glowcare/products", json=_clean_records("X", price=-1)[0]).status_code == 422
    existing = catalog_repository.get_catalog("glowcare")[0].model_dump()
    assert client.post("/merchants/glowcare/products", json=existing).status_code == 409


def test_mcp_tool_surface_has_no_catalog_mutation_tool():
    import asyncio
    assert {t.name for t in asyncio.run(mcp.list_tools())} == {"list_merchants", "catalog_search", "create_order"}
