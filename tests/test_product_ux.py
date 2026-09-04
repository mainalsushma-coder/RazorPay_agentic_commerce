from fastapi.testclient import TestClient

from app.main import app
from app.services.policy_engine import AUTO_APPROVE_LIMIT, MAX_SPEND_LIMIT


client = TestClient(app)


def test_demo_entry_has_buyer_and_merchant_paths():
    page = client.get("/login")
    assert page.status_code == 200
    assert 'href="/dashboard"' in page.text
    assert 'href="/merchant-portal"' in page.text
    assert "Demo identity entry only" in page.text


def test_profile_and_authoritative_mandate_metadata():
    profile = client.get("/profile")
    mandate = client.get("/buyer/mandate")
    assert profile.status_code == 200
    assert "Demo Buyer" in profile.text
    assert "Purchase Mandate" in profile.text
    assert mandate.status_code == 200
    assert mandate.json() == {
        "label": "Current demo mandate",
        "currency": "INR",
        "automatic_purchase_limit": AUTO_APPROVE_LIMIT,
        "maximum_transaction": MAX_SPEND_LIMIT,
        "above_automatic_limit": "requires_confirmation",
        "above_maximum_transaction": "blocked",
    }


def test_core_product_surfaces_and_catalog_trust_labels():
    pages = [client.get(path) for path in ("/login", "/dashboard", "/profile", "/merchant-portal")]
    assert all(page.status_code == 200 for page in pages)
    assert all("BOUND" in page.text and 'class="brand-mark"' in page.text for page in pages)
    portal = client.get("/static/merchant-portal.js").text
    assert "Active Catalog" in portal
    assert "Staged" in portal
    assert "Not visible to buyer agents" in portal


def test_model_text_is_rendered_with_text_nodes_and_payment_id_is_conditional():
    script = client.get("/static/app.js").text
    assert "appendFormattedText" in script
    assert "document.createTextNode" in script
    assert "appendFormattedText(p,t.content)" in script
    assert "innerHTML=`<div class=\"message-bubble\"><p>${" not in script
    assert "if(o.razorpay_order_id)" in script
    assert "code.textContent=o.razorpay_order_id" in script
    assert "o.razorpay_order_id||o.status" not in script


def test_empty_prompts_use_normal_chat_and_checkout_copy_is_structured():
    script = client.get("/static/app.js").text
    assert "Try asking" in script
    assert "m.category" in script
    assert "button.onclick=()=>send(prompt,button)" in script
    assert 'if(!conversation.turns.length&&!state.busy)' in script
    assert "BOUND GUARDED CHECKOUT" in script
    assert "Your AI agent cannot approve this transaction itself." in script
    assert "Bound Guardrails blocked the transaction." in script
