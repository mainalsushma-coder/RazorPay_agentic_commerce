from fastapi.testclient import TestClient

from app.main import app
from app.services.policy_engine import AUTO_APPROVE_LIMIT, MAX_SPEND_LIMIT


client = TestClient(app)


def test_demo_entry_has_buyer_and_merchant_paths():
    page = client.get("/login")
    assert page.status_code == 200
    assert 'href="/buyer-login"' in page.text
    assert 'href="/merchant-login"' in page.text
    assert "Bound prototype" in page.text


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
    assert all("BOUND" in page.text for page in pages)
    assert 'class="brand-badge"' not in pages[0].text
    portal = client.get("/static/merchant-portal.js").text
    assert "Active Catalog" in portal
    assert "Staged" in portal
    assert "Not visible to buyer agents" in portal


def test_model_text_is_rendered_with_text_nodes_and_payment_id_is_conditional():
    script = client.get("/static/app.js").text
    assert "textContent=String" in script
    assert "text($(\"#agent-summary\")" in script
    assert "result.message" in script
    assert "innerHTML=result.message" not in script


def test_goal_examples_use_universal_agent_and_checkout_copy_is_structured():
    script = client.get("/static/app.js").text
    assert "[data-goal]" in script
    assert 'api("/agent/chat"' in script
    assert "Human approval required" in script
    assert "No Razorpay order exists until you approve." in script
    assert "No payment order was created." in script


def test_product_success_allows_repeat_purchase_with_busy_protection():
    script = client.get("/static/app.js").text
    state_fn = script.split("function productOrderState", 1)[1].split("function productCard", 1)[0]
    assert 'return"pending"' in state_fn
    assert 'order.status==="created")return"repeat"' in state_fn
    assert 'order.status==="requires_confirmation")return"approval"' in state_fn
    assert '==="blocked")return"blocked"' in state_fn
    assert 'return"error"' in state_fn
    assert 'pending:"Checking policy…"' in script
    assert 'repeat:"Buy again"' in script
    assert 'approval:"Approval required"' in script
    assert 'blocked:"Blocked"' in script
    assert 'error:"Purchase failed"' in script
    assert 'button.disabled=state.busy||!available||!["idle","repeat"].includes(status)||external' in script
    assert "if(state.busy)return;state.busy=true" in script
    assert "automatic_purchase_limit" not in state_fn


def test_payment_failure_is_not_labeled_as_a_policy_block():
    script = client.get("/static/app.js").text
    order_card = script.split("function orderCard", 1)[1].split("function showOrder", 1)[0]
    assert 'blocked?order.reason||' in order_card
    assert 'blocked?"Transaction exceeds mandate":"Payment order could not be created"' in order_card
    assert "The payment service returned an uncertain result." in order_card
