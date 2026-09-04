from __future__ import annotations
import os, socket, subprocess, sys, time, urllib.request
from collections.abc import Iterator
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); return int(sock.getsockname()[1])

@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    port = _free_port(); url = f"http://127.0.0.1:{port}"; env = os.environ.copy()
    env.update(RAZORPAY_KEY_ID="e2e_test_key", RAZORPAY_KEY_SECRET="e2e_test_secret", PYTHONPATH=str(ROOT))
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "tests.e2e.server:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    try:
        for _ in range(100):
            try: urllib.request.urlopen(url + "/", timeout=.2).close(); break
            except OSError:
                if process.poll() is not None: raise RuntimeError("E2E server exited")
                time.sleep(.05)
        else: raise RuntimeError("E2E server did not start")
        yield url
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill()

@pytest.fixture(autouse=True)
def reset_application(base_url):
    urllib.request.urlopen(urllib.request.Request(base_url + "/__e2e__/reset", method="POST"), timeout=2).close()

@pytest.fixture
def app_page(page):
    errors=[]
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    # Chromium reports intentionally asserted 4xx fetches as console resource
    # errors even when application code handles the response successfully.
    page.on("console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" and "403 (Forbidden)" not in message.text else None)
    yield page
    assert errors == []
