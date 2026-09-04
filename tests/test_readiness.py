from copy import deepcopy

from fastapi.testclient import TestClient

from app.data.raw_catalog import raw_catalog
from app.main import app
from app.services.catalog_repair_service import repair_catalog
from app.services.readiness_service import scan_catalog_readiness


client = TestClient(app)


def test_raw_catalog_readiness_report():
    report = scan_catalog_readiness(raw_catalog)

    assert report["readiness_score"] == 71.4
    assert report["readiness_score"] < 100
    assert report["total_products"] == 3
    assert report["ready_products"] == 0
    assert report["issue_count"] == 6

    issues = {
        (issue["sku"], issue["field"], issue["issue_type"])
        for issue in report["issues"]
    }
    assert ("SKIN001", "currency", "missing_currency") in issues
    assert ("SKIN002", "description", "missing_required_field") in issues
    assert ("SKIN001", "price", "non_normalized_price") in issues
    assert ("SKIN002", "price", "non_normalized_price") in issues
    assert ("SKIN002", "stock", "non_integer_stock") in issues
    assert ("SKIN003", "price", "invalid_price") in issues


def test_readiness_endpoint_returns_raw_catalog_scan():
    response = client.get("/merchant/readiness")

    assert response.status_code == 200
    assert response.json() == scan_catalog_readiness(raw_catalog)


def test_repair_catalog_safely_repairs_a_deep_copy():
    original = deepcopy(raw_catalog)

    result = repair_catalog(raw_catalog)
    repaired = result["catalog"]

    assert raw_catalog == original
    assert repaired is not raw_catalog
    assert repaired[0]["price"] == 699.0
    assert repaired[0]["currency"] == "INR"
    assert repaired[1]["price"] == 899.0
    assert repaired[1]["stock"] == 8
    assert isinstance(repaired[1]["stock"], int)
    assert repaired[2]["price"] == "contact seller"
    assert "description" not in repaired[1]

    unresolved = {
        (issue["sku"], issue["field"])
        for issue in result["unresolved_issues"]
    }
    assert unresolved == {
        ("SKIN002", "description"),
        ("SKIN003", "price"),
    }


def test_currency_is_only_inferred_from_explicit_price_evidence():
    result = repair_catalog([
        {"sku": "NO-EVIDENCE", "price": "699"},
        {"sku": "RUPEE", "price": "\u20b9699"},
        {"sku": "CODE", "price": "899 INR"},
    ])

    assert "currency" not in result["catalog"][0]
    assert result["catalog"][1]["currency"] == "INR"
    assert result["catalog"][2]["currency"] == "INR"


def test_repair_preview_improves_readiness_and_preserves_raw_catalog():
    original = deepcopy(raw_catalog)

    response = client.get("/merchant/readiness/repair-preview")

    assert response.status_code == 200
    preview = response.json()
    assert preview["before"]["readiness_score"] == 71.4
    assert preview["after"]["readiness_score"] == 90.5
    assert preview["after"]["readiness_score"] > 71.4
    assert len(preview["repairs"]) == 4
    assert len(preview["unresolved_issues"]) == 2
    assert raw_catalog == original


def test_resolve_preview_completes_readiness_lifecycle():
    original = deepcopy(raw_catalog)
    resolutions = [
        {
            "sku": "SKIN002",
            "field": "description",
            "value": "Hydrating daily skincare serum",
        },
        {"sku": "SKIN003", "field": "price", "value": 1299},
    ]

    response = client.post(
        "/merchant/readiness/resolve-preview",
        json={"resolutions": resolutions},
    )

    assert response.status_code == 200
    preview = response.json()
    assert preview["before"]["readiness_score"] == 71.4
    assert preview["after_autopilot"]["readiness_score"] == 90.5
    assert preview["final"]["readiness_score"] == 100.0
    assert preview["merchant_resolutions"] == resolutions
    assert preview["remaining_unresolved_issues"] == []
    assert preview["resolved_catalog"][1]["description"] == resolutions[0]["value"]
    assert preview["resolved_catalog"][2]["price"] == 1299
    assert raw_catalog == original


def test_invalid_merchant_resolutions_are_rejected_safely():
    invalid_resolutions = [
        {"sku": "UNKNOWN", "field": "description", "value": "Valid text"},
        {"sku": "SKIN001", "field": "description", "value": "Valid text"},
        {"sku": "SKIN003", "field": "price", "value": "not a price"},
        {"sku": "SKIN002", "field": "stock", "value": "eight"},
        {"sku": "SKIN002", "field": "description", "value": "   "},
        {"sku": "SKIN002", "field": "attributes", "value": "anything"},
    ]

    original = deepcopy(raw_catalog)
    for resolution in invalid_resolutions:
        response = client.post(
            "/merchant/readiness/resolve-preview",
            json={"resolutions": [resolution]},
        )
        assert response.status_code == 400

    assert raw_catalog == original
