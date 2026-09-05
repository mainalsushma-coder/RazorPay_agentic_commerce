import re
from pathlib import Path
from playwright.sync_api import expect

DEMO = Path(__file__).resolve().parents[2] / "demo"

def dispatch(page, text):
    page.get_by_label("Shopping objective").fill(text)
    page.get_by_role("button", name=re.compile("Dispatch Bound")).click()

def metrics(page, base_url): return page.request.get(base_url + "/__e2e__/metrics").json()

def test_separate_entry_paths_and_mobile_smoke(app_page, base_url):
    p=app_page; p.goto(base_url+"/login")
    expect(p.get_by_text("BOUND.", exact=True)).to_be_visible()
    p.get_by_role("link", name=re.compile("Start shopping", re.I)).click(); expect(p).to_have_url(re.compile("/buyer-login$"))
    p.get_by_label("Name").fill("Arjun Sharma"); p.get_by_role("button",name=re.compile("Enter shopping workspace")).click(); expect(p).to_have_url(re.compile("/dashboard$"))
    expect(p.get_by_text("What should Bound shop for you?",exact=True)).to_be_visible(); expect(p.get_by_text("Merchant Portal",exact=True)).to_have_count(0)
    p.goto(base_url+"/login"); p.get_by_role("link",name=re.compile("Open merchant workspace")).click(); expect(p).to_have_url(re.compile("/merchant-login$")); p.get_by_role("button",name=re.compile("Enter merchant console")).click(); expect(p).to_have_url(re.compile("/merchant-portal$"))
    expect(p.get_by_text("Shopping workspace",exact=True)).to_have_count(0)
    p.set_viewport_size({"width":390,"height":844}); p.goto(base_url+"/dashboard"); expect(p.get_by_label("Shopping objective")).to_be_visible()

def test_universal_goal_search_and_safe_structured_product(app_page, base_url):
    p=app_page; urls=[]; p.on("request",lambda r:urls.append(r.url)); p.goto(base_url+"/dashboard")
    expect(p.get_by_text("GlowCare",exact=True)).to_be_visible(); expect(p.get_by_text("TechHub",exact=True)).to_be_visible()
    dispatch(p,"Find vitamin C serum under 1000")
    for text in ("Vitamin C Serum","₹699","SKU SKIN001","In stock","GlowCare"):
        expect(p.get_by_text(text,exact=False).last).to_be_visible()
    assert p.evaluate("window.__BOUND_XSS__") is None
    assert all("11434" not in u and "razorpay" not in u.casefold() for u in urls)
    assert all(u.startswith(base_url) for u in urls)

def test_delegated_autonomous_purchase_is_zero_click(app_page, base_url):
    p=app_page; p.goto(base_url+"/dashboard"); dispatch(p,"Buy me a Vitamin C serum under ₹1,000.")
    for text in ("Order created / Awaiting payment","Vitamin C Serum","₹699","Active merchant catalog searched","Price and inventory verified","Within purchase mandate","Razorpay order created / Awaiting payment"):
        expect(p.get_by_text(text,exact=False).last).to_be_visible()
    expect(p.get_by_role("button",name="Buy again")).to_be_enabled()
    expect(p.get_by_role("button",name="Checking policy…")).to_have_count(0)
    m=metrics(p,base_url); assert len(m["payment_calls"])==1 and m["agent_requests"]==1; assert m["buyer_order_bodies"]==[]

def test_delegated_human_confirmation_and_replay(app_page, base_url):
    p=app_page; p.goto(base_url+"/dashboard"); dispatch(p,"Find a wireless keyboard under ₹4,000 and buy the best one.")
    for text in ("Human approval required","₹3,499","Wireless Mechanical Keyboard","No Razorpay order exists"):
        expect(p.get_by_text(text,exact=False).last).to_be_visible()
    expect(p.get_by_role("button",name="Approval required")).to_be_visible()
    assert metrics(p,base_url)["payment_calls"]==[]
    p.get_by_role("button",name=re.compile("Approve ₹3,499")).click(); expect(p.get_by_text("Order created / Awaiting payment",exact=True)).to_be_visible()
    m=metrics(p,base_url); assert m["confirm_requests"]==1 and len(m["payment_calls"])==1
    assert p.request.post(f"{base_url}/orders/{m['payment_calls'][0]['receipt']}/confirm").status==400

def test_structured_blocked_transaction(app_page, base_url):
    p=app_page; p.goto(base_url+"/dashboard"); dispatch(p,"blocked purchase")
    expect(p.get_by_text("Purchase blocked",exact=False)).to_be_visible(); expect(p.get_by_text("Order exceeds maximum spend limit",exact=False)).to_be_visible()
    expect(p.get_by_role("button",name=re.compile("Approve"))).to_have_count(0); assert metrics(p,base_url)["payment_calls"]==[]

def test_readiness_repairs_staged_then_active(app_page, base_url):
    p=app_page; p.goto(base_url+"/merchant-portal")
    for text in ("71.4%","Needs Setup","6 issues","Needs review"): expect(p.get_by_text(text,exact=False).first).to_be_visible()
    expect(p.get_by_role("heading",name="GlowCare",exact=True)).to_be_visible()
    p.get_by_role("button",name=re.compile("Fix with Autopilot")).click(); expect(p.get_by_text("90.5%",exact=True).first).to_be_visible(timeout=5000); expect(p.get_by_text("Merchant Input Required")).to_be_visible()
    p.get_by_label("SKIN002 description").fill("Hydrating daily skincare serum"); p.get_by_label("SKIN003 price").fill("1299"); p.get_by_role("button",name="Apply merchant input").click()
    expect(p.get_by_text("100%",exact=True).first).to_be_visible(); before=p.request.get(base_url+"/merchants/glowcare/products").json(); assert next(x for x in before if x["sku"]=="SKIN003")["price"]==599
    p.get_by_role("button",name="Activate Store").click(); after=p.request.get(base_url+"/merchants/glowcare/products").json(); assert next(x for x in after if x["sku"]=="SKIN003")["price"]==1299

def test_real_messy_and_clean_csv_imports(app_page, base_url):
    p=app_page; p.goto(base_url+"/merchant-portal"); p.get_by_role("button",name="Catalog",exact=True).click(); p.get_by_role("button",name="Import Catalog").click(); p.get_by_label("Catalog file").set_input_files(DEMO/"example_catalog_messy.csv"); p.get_by_role("button",name="Preview Import").click()
    expect(p.get_by_text("Staged",exact=True)).to_be_visible(); assert all(x["sku"]!="DEMO101" for x in p.request.get(base_url+"/merchants/glowcare/products").json())
    p.get_by_role("button",name="Run Autopilot").click(); p.get_by_label("DEMO102 · description").fill("Merchant supplied desk lamp"); p.get_by_label("DEMO103 · description").fill("Merchant supplied gift box"); p.get_by_label("DEMO103 · price").fill("1299"); p.get_by_role("button",name="Apply resolutions").click(); p.get_by_role("button",name="Activate Catalog").click(); assert any(x["sku"]=="DEMO101" for x in p.request.get(base_url+"/merchants/glowcare/products").json())

def test_techhub_and_merchant_xss(app_page, base_url):
    p=app_page; p.goto(base_url+"/merchant-portal"); p.get_by_label("Select merchant workspace").select_option("techhub"); expect(p.get_by_text("Preconfigured Store")).to_be_visible(); p.get_by_role("button",name="Catalog",exact=True).click(); expect(p.get_by_text("Wireless Mechanical Keyboard")).to_be_visible()
    payload="<script>window.__BOUND_XSS__=true</script>"; record=[{"sku":"X\" onfocus=\"alert(1)\" autofocus=\"","name":payload,"category":"<b>Unsafe</b>","description":"HTML-like merchant text","price":100,"currency":"INR","stock":1,"attributes":{"payload":payload}}]
    imported=p.request.post(base_url+"/merchants/techhub/catalog/import",data=record).json(); p.request.post(f"{base_url}/merchants/techhub/catalog/imports/{imported['import_id']}/activate"); p.reload(); p.get_by_label("Select merchant workspace").select_option("techhub"); p.get_by_role("button",name="Catalog",exact=True).click(); expect(p.get_by_text(payload,exact=True).first).to_be_visible(); assert p.evaluate("window.__BOUND_XSS__") is None


def test_repeat_purchase_and_inflight_double_submission(app_page, base_url):
    p = app_page
    p.goto(base_url + "/dashboard")
    dispatch(p, "Find vitamin C serum under 1000")
    expect(p.locator(".select-product")).to_be_enabled()
    # Hold one HTTP attempt open while a second handler invocation occurs.
    p.route("**/buyer/orders", lambda route: route.fulfill(response=route.fetch()))
    p.evaluate("""() => {
        window.purchaseAttempt = buy(state.products[0]);
        buy(state.products[0]);
    }""")
    p.evaluate("() => window.purchaseAttempt")
    expect(p.get_by_role("button", name="Buy again")).to_be_enabled()
    first = metrics(p, base_url)
    assert len(first["buyer_order_bodies"]) == len(first["payment_calls"]) == 1
    p.get_by_role("button", name="Buy again").click()
    expect(p.get_by_role("button", name="Buy again")).to_be_enabled()
    second = metrics(p, base_url)
    assert len(second["buyer_order_bodies"]) == len(second["payment_calls"]) == 2
    receipts = [call["receipt"] for call in second["payment_calls"]]
    assert len(set(receipts)) == 2
    for receipt in receipts:
        order = p.request.get(base_url + "/orders/" + receipt).json()
        assert order["order_id"] == receipt
        assert order["sku"] == "SKIN001"
    dispatch(p, "Find vitamin C serum under 1000")
    expect(p.locator(".select-product")).to_be_enabled()
    assert len(metrics(p, base_url)["payment_calls"]) == 2


def test_global_goals_do_not_reuse_source_or_empty_reply(app_page, base_url):
    p = app_page
    requests = []
    p.on("request", lambda r: requests.append(r.post_data_json) if r.url.endswith("/agent/chat") else None)
    p.goto(base_url + "/dashboard")
    for goal, sku in [("Buy Vitamin C serum", "SKIN001"), ("Find snowboard", "SNOW-001"), ("Buy Vitamin C serum", "SKIN001"), ("Find snowboard", "SNOW-001"), ("Buy wireless keyboard", "TECH001")]:
        dispatch(p, goal)
        expect(p.locator("#execution-state")).not_to_have_text("Working")
        assert p.evaluate("state.products[0].sku") == sku
        assert p.evaluate("state.pendingKey") is None
        assert "[object Object]" not in p.locator("#agent-summary").inner_text()
        if sku == "SNOW-001":
            expect(p.locator(".select-product")).to_be_disabled()
            assert p.evaluate("state.order") is None
    assert all(r == {"message": r["message"], "conversation_history": []} for r in requests)
    assert len(metrics(p, base_url)["payment_calls"]) == 2


def test_safe_error_normalization(app_page, base_url):
    p = app_page
    p.goto(base_url + "/dashboard")
    for body in [{"detail": "Please try again."}, {"detail": {"reason": "Please try again."}}, {"error": {"detail": {"message": "Please try again."}}}]:
        assert p.evaluate("body => safeErrorMessage(body)", body) == "Please try again."
    for body in [{"detail": [{"input": "private", "msg": "validation"}]}, {"detail": {"stack": "private"}}, {"message": "token=private"}, {"reason": "[object Object]"}, {}]:
        assert p.evaluate("body => safeErrorMessage(body)", body) == "BOUND could not complete this goal."
    p.route("**/agent/chat", lambda route: route.fulfill(status=200, json={"message":"", "products":[], "events":[]}))
    dispatch(p, "Find snowboard")
    expect(p.locator("#execution-state")).to_have_text("Results ready")
    p.unroute("**/agent/chat")
    dispatch(p, "Buy Vitamin C serum")
    expect(p.get_by_role("button", name="Buy again")).to_be_enabled()


def test_authority_and_brand_responsive(app_page, base_url):
    p = app_page
    p.goto(base_url + "/dashboard")
    expect(p.locator(".tier")).to_have_count(3)
    expect(p.locator(".brand-mark")).to_be_visible()
    expect(p.locator(".authority-trust")).to_have_text("▣ Backend enforced")
    for width in [1280, 390]:
        p.set_viewport_size({"width": width, "height": 900})
        assert p.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for tier in p.locator(".tier").all():
            assert tier.evaluate("e => getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
        p.screenshot(path=f"artifacts/bound-workspace-{width}.png", full_page=True)
