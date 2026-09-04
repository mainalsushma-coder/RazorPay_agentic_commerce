import re
from pathlib import Path
from playwright.sync_api import expect

DEMO = Path(__file__).resolve().parents[2] / "demo"

def chat(page, text):
    page.get_by_label("Message this store").fill(text)
    page.get_by_role("button", name="Send").click()

def metrics(page, base_url):
    return page.request.get(base_url + "/__e2e__/metrics").json()

def test_entry_profile_and_mobile_smoke(app_page, base_url):
    p=app_page; p.goto(base_url+"/login")
    expect(p.get_by_text("BOUND", exact=True)).to_be_visible(); expect(p.get_by_text("Commerce built", exact=False)).to_be_visible()
    p.get_by_role("link", name="Continue as Buyer").click(); expect(p).to_have_url(re.compile("/dashboard$"))
    p.goto(base_url+"/login"); p.get_by_role("link", name="Merchant Login").click(); expect(p).to_have_url(re.compile("/merchant-portal$"))
    p.goto(base_url+"/profile")
    for text in ("Demo Buyer","Purchase Mandate","₹2,000","₹10,000","Human approval","Transaction blocked","Agent permissions"):
        expect(p.get_by_text(text, exact=False).first).to_be_visible()
    expect(p.locator("input, select, textarea")).to_have_count(0)
    p.set_viewport_size({"width":390,"height":844})
    for path, selector in (("/login",("link","Continue as Buyer")),("/dashboard",("button","New conversation")),("/profile",("text","Purchase Mandate")),("/merchant-portal",("combobox","Select merchant workspace"))):
        p.goto(base_url+path)
        loc=p.get_by_text(selector[1], exact=False).first if selector[0]=="text" else p.get_by_role(selector[0], name=selector[1])
        expect(loc).to_be_visible()

def test_scoped_history_search_markdown_xss_and_network(app_page, base_url):
    p=app_page; urls=[]; p.on("request",lambda r:urls.append(r.url)); p.goto(base_url+"/dashboard")
    expect(p.get_by_role("button",name=re.compile("GlowCare"))).to_be_visible(); expect(p.get_by_role("button",name=re.compile("TechHub"))).to_be_visible()
    chat(p,"Find vitamin C serum under 1000")
    for text in ("Vitamin C Serum","₹699","SKU SKIN001","In stock"):
        expect(p.get_by_text(text,exact=False).last).to_be_visible()
    expect(p.get_by_role("button",name="Buy now")).to_be_visible(); expect(p.get_by_text("**Vitamin C Serum**",exact=True)).to_have_count(0)
    assert p.evaluate("window.__BOUND_XSS__") is None
    p.get_by_role("button",name=re.compile("TechHub")).click(); expect(p.locator("#merchant-name")).to_have_text("TechHub")
    chat(p,"TechHub private turn"); expect(p.locator("#conversation").get_by_text("Deterministic techhub reply",exact=False)).to_be_visible()
    p.get_by_role("button",name=re.compile("GlowCare")).click(); expect(p.get_by_text("Vitamin C Serum",exact=True).last).to_be_visible(); expect(p.locator("#conversation").get_by_text("TechHub private turn",exact=False)).to_have_count(0)
    assert all("11434" not in u and "razorpay" not in u.casefold() for u in urls)
    assert all(u.startswith(base_url) for u in urls)

def test_deterministic_buy_approved_and_duplicate_click(app_page, base_url):
    p=app_page; p.goto(base_url+"/dashboard"); chat(p,"Find vitamin C serum under 1000")
    p.get_by_role("button",name="Buy now").dblclick(force=True)
    for text in ("BOUND GUARDED CHECKOUT","Purchase approved","₹699.00","Merchant price verified","Inventory verified","Within purchase mandate","Order created successfully","Razorpay Test Mode","order_test_bound_001"):
        expect(p.get_by_text(text,exact=False).last).to_be_visible()
    expect(p.get_by_text("Human Approval",exact=False)).to_have_count(0); expect(p.get_by_text("Transaction blocked",exact=False)).to_have_count(0)
    m=metrics(p,base_url); assert m["buyer_order_bodies"]==[{"merchant_id":"glowcare","sku":"SKIN001","quantity":1}]; assert len(m["payment_calls"])==1; assert m["agent_requests"]==1

def test_human_confirmation_and_replay(app_page, base_url):
    p=app_page; p.goto(base_url+"/dashboard"); p.get_by_role("button",name=re.compile("TechHub")).click(); chat(p,"Find keyboard"); p.get_by_role("button",name="Buy now").click()
    for text in ("Your approval is required","₹3,499.00","Wireless Mechanical Keyboard","TechHub","cannot approve"):
        expect(p.get_by_text(text,exact=False).last).to_be_visible()
    assert metrics(p,base_url)["payment_calls"]==[]; expect(p.get_by_text("order_test_bound_001")).to_have_count(0)
    p.get_by_role("button",name=re.compile("Review & Confirm")).click(); expect(p.get_by_text("Purchase approved",exact=True)).to_be_visible(); expect(p.get_by_text("order_test_bound_001")).to_be_visible()
    m=metrics(p,base_url); assert m["confirm_requests"]==1 and len(m["payment_calls"])==1
    assert p.request.post(f"{base_url}/orders/{m['payment_calls'][0]['receipt']}/confirm").status==400
    assert len(metrics(p,base_url)["payment_calls"])==1

def test_structured_blocked_transaction(app_page, base_url):
    p=app_page; p.goto(base_url+"/dashboard"); chat(p,"blocked purchase")
    expect(p.get_by_text("Transaction blocked",exact=False)).to_be_visible(); expect(p.get_by_text("Bound Guardrails blocked the transaction",exact=False).last).to_be_visible(); expect(p.get_by_text("Order exceeds maximum spend limit",exact=False)).to_be_visible()
    expect(p.get_by_role("button",name=re.compile("Confirm"))).to_have_count(0); expect(p.get_by_text("Purchase approved",exact=False)).to_have_count(0); expect(p.get_by_text("Razorpay Test Mode",exact=False)).to_have_count(0)
    result=p.evaluate("""async()=>{let r=await fetch('/buyer/orders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({merchant_id:'glowcare',sku:'SKIN001',quantity:15})});return {status:r.status,body:await r.json()}}""")
    assert result=={"status":403,"body":{"decision":"blocked","reason":"Order exceeds maximum spend limit"}}
    m=metrics(p,base_url); assert m["payment_calls"]==[]; assert m["buyer_order_bodies"][-1]=={"merchant_id":"glowcare","sku":"SKIN001","quantity":15}

def test_readiness_repairs_staged_then_active(app_page, base_url):
    p=app_page; p.goto(base_url+"/merchant-portal")
    for text in ("71.4%","Needs Setup","3","0","6","Required field"):
        expect(p.get_by_text(text,exact=False).first).to_be_visible()
    p.get_by_role("button",name=re.compile("Run Autopilot")).click(); expect(p.get_by_text("90.5%",exact=True).first).to_be_visible(timeout=5000); expect(p.get_by_text("Merchant Input Required")).to_be_visible()
    for text in ("₹699","699","INR","899 INR","899","8"): expect(p.get_by_text(text,exact=False).first).to_be_visible()
    p.get_by_label("SKIN002 description").fill("Hydrating daily skincare serum"); p.get_by_label("SKIN003 price").fill("1299"); p.get_by_role("button",name="Apply merchant input").click()
    expect(p.get_by_text("100%",exact=True).first).to_be_visible(); expect(p.get_by_text("Blocking issues 0",exact=False)).to_be_visible(); expect(p.get_by_role("button",name="Activate Catalog")).to_be_visible()
    before=p.request.get(base_url+"/merchants/glowcare/products").json(); assert next(x for x in before if x["sku"]=="SKIN002")["description"]=="Daily gentle cleanser"; assert next(x for x in before if x["sku"]=="SKIN003")["price"]==599
    p.get_by_role("button",name="Activate Catalog").click(); expect(p.get_by_text("Catalog activated",exact=False)).to_be_visible()
    after=p.request.get(base_url+"/merchants/glowcare/products").json(); assert next(x for x in after if x["sku"]=="SKIN002")["description"]=="Hydrating daily skincare serum"; assert next(x for x in after if x["sku"]=="SKIN003")["price"]==1299

def test_real_messy_and_clean_csv_imports(app_page, base_url):
    p=app_page; p.goto(base_url+"/merchant-portal"); p.get_by_role("button",name="Catalog").click(); p.get_by_role("button",name="Import Catalog").click(); p.get_by_label("Catalog file").set_input_files(DEMO/"example_catalog_messy.csv"); p.get_by_role("button",name="Preview Import").click()
    expect(p.get_by_text("3 products detected")).to_be_visible(); expect(p.get_by_text("Staged",exact=True)).to_be_visible(); assert all(x["sku"]!="DEMO101" for x in p.request.get(base_url+"/merchants/glowcare/products").json())
    p.get_by_role("button",name="Run Autopilot").click()
    p.get_by_label("DEMO102 · description").fill("Merchant supplied desk lamp"); p.get_by_label("DEMO103 · description").fill("Merchant supplied gift box"); p.get_by_label("DEMO103 · price").fill("1299"); p.get_by_role("button",name="Apply resolutions").click(); expect(p.get_by_text("100%",exact=True).last).to_be_visible()
    assert all(x["sku"]!="DEMO101" for x in p.request.get(base_url+"/merchants/glowcare/products").json()); p.get_by_role("button",name="Activate Catalog").click(); expect(p.get_by_text("Catalog Activated",exact=False)).to_be_visible(); assert any(x["sku"]=="DEMO101" for x in p.request.get(base_url+"/merchants/glowcare/products").json())
    p.get_by_role("button",name="Import Catalog").click(); p.get_by_label("Catalog file").set_input_files(DEMO/"example_catalog_clean.csv"); p.get_by_role("button",name="Preview Import").click(); expect(p.get_by_text("2 products detected")).to_be_visible(); assert all(x["sku"]!="DEMO001" for x in p.request.get(base_url+"/merchants/glowcare/products").json()); p.get_by_role("button",name="Run Autopilot").click(); expect(p.get_by_text("100%",exact=True).last).to_be_visible(); expect(p.get_by_role("button",name="Activate Catalog")).to_be_visible(); p.get_by_role("button",name="Activate Catalog").click(); assert [x["sku"] for x in p.request.get(base_url+"/merchants/glowcare/products").json()]==["DEMO001","DEMO002"]

def test_techhub_and_merchant_xss(app_page, base_url):
    p=app_page; p.goto(base_url+"/merchant-portal"); p.get_by_label("Select merchant workspace").select_option("techhub"); expect(p.get_by_text("Preconfigured Store")).to_be_visible(); expect(p.get_by_text("3 active products")).to_be_visible(); p.get_by_role("button",name="Catalog").click(); expect(p.get_by_text("Wireless Mechanical Keyboard")).to_be_visible()
    payload="<script>window.__BOUND_XSS__=true</script>"; record=[{"sku":"X\" onfocus=\"alert(1)\" autofocus=\"","name":payload,"category":"<b>Unsafe</b>","description":"HTML-like merchant text","price":100,"currency":"INR","stock":1,"attributes":{"payload":payload}}]
    imported=p.request.post(base_url+"/merchants/techhub/catalog/import",data=record).json(); p.request.post(f"{base_url}/merchants/techhub/catalog/imports/{imported['import_id']}/activate"); p.reload(); p.get_by_label("Select merchant workspace").select_option("techhub"); p.get_by_role("button",name="Catalog").click(); expect(p.get_by_text(payload,exact=True).first).to_be_visible(); assert p.evaluate("window.__BOUND_XSS__") is None
