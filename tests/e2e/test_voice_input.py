import pytest
from playwright.sync_api import expect

from tests.e2e.test_bound_journey import dispatch, metrics


def mock_recognition(page, api="SpeechRecognition"):
    page.add_init_script("""(api => {
      window.SpeechRecognition = undefined;
      window.webkitSpeechRecognition = undefined;
      window[api] = class {
        constructor() { window.recognition = this; }
        start() { if (window.failStart) throw new Error('unavailable'); this.onstart?.(); }
        abort() { this.aborted = true; this.onend?.(); }
        result(text) {
          const result = [{transcript: text}]; result.isFinal = true;
          this.onresult({results: [result]});
        }
      };
    })(""" + repr(api) + ");")


@pytest.mark.parametrize("api", ["SpeechRecognition", "webkitSpeechRecognition"])
def test_voice_is_editable_draft_only(app_page, base_url, api):
    p = app_page
    mock_recognition(p, api)
    p.goto(base_url + "/dashboard")
    button = p.get_by_role("button", name="Speak a shopping goal")
    button.focus()
    p.keyboard.press("Enter")
    expect(p.get_by_role("button", name="Stop voice input")).to_have_attribute("aria-pressed", "true")
    expect(p.locator("#voice-status")).to_contain_text("Listening")
    p.evaluate("recognition.result('Buy Vitamin C serum under 1000')")
    expect(p.get_by_label("Shopping objective")).to_have_value("Buy Vitamin C serum under 1000")
    expect(button).to_have_attribute("aria-pressed", "false")
    assert metrics(p, base_url)["agent_requests"] == 0
    assert metrics(p, base_url)["payment_calls"] == []
    dispatch(p, "Find Vitamin C serum")
    expect(p.locator(".product-name")).to_have_text("Vitamin C Serum")
    assert metrics(p, base_url)["agent_requests"] == 1
    assert metrics(p, base_url)["payment_calls"] == []


def test_unsupported_voice_keeps_typing(app_page, base_url):
    p = app_page
    p.add_init_script("window.SpeechRecognition = undefined; window.webkitSpeechRecognition = undefined;")
    p.goto(base_url + "/dashboard")
    expect(p.locator("#voice-goal")).to_be_hidden()
    dispatch(p, "Find Vitamin C serum")
    expect(p.locator(".product-name")).to_have_text("Vitamin C Serum")


@pytest.mark.parametrize("failure, message", [
    ("not-allowed", "Microphone permission is required"),
    ("no-speech", "No speech detected"),
    ("network", "Voice input could not connect"),
    ("throw", "Voice input is unavailable"),
    ("end", "No speech detected"),
])
def test_voice_failure_preserves_typed_goal(app_page, base_url, failure, message):
    p = app_page
    mock_recognition(p)
    p.goto(base_url + "/dashboard")
    p.get_by_label("Shopping objective").fill("Find Vitamin C serum")
    if failure == "throw": p.evaluate("window.failStart = true")
    p.locator("#voice-goal").click()
    if failure == "end": p.evaluate("recognition.onend()")
    elif failure != "throw": p.evaluate("error => recognition.onerror({error})", failure)
    expect(p.locator("#voice-status")).to_contain_text(message)
    expect(p.get_by_label("Shopping objective")).to_have_value("Find Vitamin C serum")
    expect(p.locator("#voice-goal")).to_have_attribute("aria-pressed", "false")
    dispatch(p, "Find Vitamin C serum")
    expect(p.locator(".product-name")).to_have_text("Vitamin C Serum")


def test_cancel_typing_and_dispatch_ignore_late_speech(app_page, base_url):
    p = app_page
    mock_recognition(p)
    p.goto(base_url + "/dashboard")
    mic = p.locator("#voice-goal")
    mic.click()
    mic.click()
    p.evaluate("recognition.result('Buy stale cancelled goal')")
    expect(p.get_by_label("Shopping objective")).to_have_value("")
    mic.click()
    p.get_by_label("Shopping objective").fill("Find Vitamin C serum")
    p.evaluate("recognition.result('Buy stale overwritten goal')")
    expect(p.get_by_label("Shopping objective")).to_have_value("Find Vitamin C serum")
    mic.click()
    p.get_by_role("button", name="Dispatch Bound").click()
    p.evaluate("recognition.result('Buy stale submitted goal')")
    expect(p.locator(".product-name")).to_have_text("Vitamin C Serum")
    expect(p.get_by_label("Shopping objective")).to_have_value("")
    assert metrics(p, base_url)["agent_requests"] == 1
    assert metrics(p, base_url)["payment_calls"] == []


def test_voice_command_bar_mobile(app_page, base_url):
    p = app_page
    mock_recognition(p)
    p.set_viewport_size({"width": 390, "height": 844})
    p.goto(base_url + "/dashboard")
    p.locator("#voice-goal").click()
    expect(p.locator("#voice-status")).to_contain_text("Listening")
    assert p.evaluate("document.documentElement.scrollWidth <= innerWidth")
    p.screenshot(path="artifacts/bound-voice-mobile.png", full_page=True)
