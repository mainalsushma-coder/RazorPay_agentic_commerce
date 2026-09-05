from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_dashboard_loads():
    dashboard = client.get("/dashboard")

    assert dashboard.status_code == 200
    assert "BOUND" in dashboard.text
    assert "What should Bound shop for you?" in dashboard.text
    assert "Merchant Portal" not in dashboard.text


def test_dashboard_assets_are_served():
    styles = client.get("/static/styles.css")
    script = client.get("/static/app.js")

    assert styles.status_code == 200
    assert ".intent-hero" in styles.text
    assert ".stores-grid" in styles.text
    assert ".product-card" in styles.text
    assert ".order-card" in styles.text
    assert script.status_code == 200
    for endpoint in ("/merchants", "/buyer/mandate", "/buyer/activity"):
        assert endpoint in script.text
    assert "createProductCard" in script.text
    assert "createStatusCard" in script.text
