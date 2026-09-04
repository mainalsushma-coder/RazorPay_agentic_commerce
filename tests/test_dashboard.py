from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_dashboard_loads_and_root_behavior_is_preserved():
    dashboard = client.get("/dashboard")
    root = client.get("/")

    assert dashboard.status_code == 200
    assert "Agent Storefront Autopilot" in dashboard.text
    assert "AI commerce with guarded checkout" in dashboard.text
    assert root.status_code == 200
    assert root.json() == {
        "message": "Agent Storefront Autopilot API is running"
    }


def test_dashboard_assets_are_served():
    styles = client.get("/static/styles.css")
    script = client.get("/static/app.js")

    assert styles.status_code == 200
    assert ".score-grid" in styles.text
    assert script.status_code == 200
    for endpoint in (
        "/products",
        "/merchant/readiness",
        "/merchant/readiness/repair-preview",
        "/audit",
    ):
        assert endpoint in script.text
