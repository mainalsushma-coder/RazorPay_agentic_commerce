from copy import deepcopy

from fastapi.testclient import TestClient

from app.data.raw_catalog import raw_catalog
from app.main import app


client = TestClient(app)


def test_merchant_portal_and_assets_are_served():
    page = client.get("/merchant-portal")
    script = client.get("/static/merchant-portal.js")
    styles = client.get("/static/merchant-portal.css")

    assert page.status_code == 200
    assert "Merchant Portal" in page.text
    assert "/static/merchant-portal.js" in page.text
    assert script.status_code == 200
    assert styles.status_code == 200


def test_portal_uses_authoritative_apis_and_dynamic_resolution_fields():
    script = client.get("/static/merchant-portal.js").text

    for endpoint in (
        "/merchants",
        "/merchant/readiness",
        "/merchant/readiness/repair-preview",
        "/merchant/readiness/resolve-preview",
        "/audit",
    ):
        assert endpoint in script
    assert "data-field" in script
    assert "unresolved_issues.map(input)" in script
    assert "fetch(\"/merchant/readiness/resolve-preview\"" not in script
    for forbidden in ("razorpay.com", "ollama", "/mcp"):
        assert forbidden not in script.lower()


def test_portal_lifecycle_apis_preserve_raw_catalog():
    original = deepcopy(raw_catalog)
    preview = client.get("/merchant/readiness/repair-preview").json()
    assert preview["before"]["readiness_score"] == 71.4
    assert preview["after"]["readiness_score"] == 90.5
    assert len(preview["repairs"]) == 4
    assert {(i["sku"], i["field"]) for i in preview["unresolved_issues"]} == {
        ("SKIN002", "description"),
        ("SKIN003", "price"),
    }

    final = client.post(
        "/merchant/readiness/resolve-preview",
        json={"resolutions": [
            {"sku": "SKIN002", "field": "description", "value": "Hydrating daily skincare serum"},
            {"sku": "SKIN003", "field": "price", "value": 1299},
        ]},
    ).json()
    assert final["final"]["readiness_score"] == 100.0
    assert final["remaining_unresolved_issues"] == []
    assert raw_catalog == original
