from playwright.sync_api import expect


def test_my_orders_repeat_details_and_navigation(app_page, base_url):
    p = app_page
    p.goto(base_url + "/dashboard")
    p.get_by_role("link", name="My orders", exact=True).click()
    expect(p.get_by_role("heading", name="My orders", exact=True)).to_be_visible()
    expect(p.get_by_text("No orders yet.", exact=False)).to_be_visible()
    for _ in range(4):
        response = p.request.post(base_url + "/buyer/orders", data={"merchant_id": "glowcare", "sku": "SKIN001", "quantity": 1})
        assert response.ok
    p.get_by_role("button", name="Refresh", exact=True).click()
    expect(p.locator(".history-order")).to_have_count(4)
    row = p.locator(".history-order").first
    expect(row).to_contain_text("GlowCare")
    expect(row).to_contain_text("699.00")
    expect(row).to_contain_text("Order created")
    assert "Paid" not in row.inner_text() and "Completed" not in row.inner_text() and "Purchased" not in row.inner_text()
    row.get_by_role("button", name="View details").click()
    dialog = p.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("order_test_bound_001")
    expect(dialog).to_contain_text("Autonomous")
    expect(dialog).to_contain_text("SKIN001")
    p.screenshot(path="artifacts/my-orders-details.png")
    p.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    p.get_by_role("link", name="Shopping workspace", exact=True).click()
    expect(p.locator("#activity .activity-row")).to_have_count(3)
    p.get_by_role("link", name="View all orders", exact=False).click()
    p.screenshot(path="artifacts/my-orders-desktop.png", full_page=True)
    p.set_viewport_size({"width":390,"height":844})
    expect(p.locator(".history-order")).to_have_count(4)
    assert p.evaluate("document.documentElement.scrollWidth <= innerWidth")
    p.screenshot(path="artifacts/my-orders-mobile.png", full_page=True)
    p.get_by_role("link", name="Purchase authority", exact=True).click()
    p.get_by_role("link", name="My orders", exact=True).click()
    expect(p.get_by_role("heading", name="My orders", exact=True)).to_be_visible()


def test_confirmation_blocked_and_shopify_history(app_page, base_url):
    p = app_page
    for merchant, sku, quantity in [("techhub", "TECH001", 1), ("glowcare", "SKIN001", 15), ("bound-commerce-test-shopify", "SNOW-001", 1)]:
        p.request.post(base_url + "/buyer/orders", data={"merchant_id": merchant, "sku": sku, "quantity": quantity})
    p.goto(base_url + "/orders")
    expect(p.locator(".history-order")).to_have_count(1)
    expect(p.locator(".history-order")).to_contain_text("Confirmation required")
    expect(p.locator(".history-order")).to_contain_text("TechHub")
    expect(p.locator("#blocked-section")).to_be_visible()
    p.get_by_role("button", name="View details").click()
    expect(p.get_by_role("dialog")).to_contain_text("Not created")
