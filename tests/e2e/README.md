# Bound deterministic browser suite

Run separately from the fast suite:

```powershell
$env:UV_CACHE_DIR="$PWD/.uv-cache"
$env:PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers"
uv run pytest -q tests/e2e
```

The suite launches the real FastAPI application and drives its real frontend in
Chromium. Catalog staging/readiness/repair/resolution/activation, repository,
order service, policy, and HTTP routes are real. Qwen/MCP orchestration and the
server-side Razorpay call are the only deterministic fakes. Test-only middleware
records trusted buyer intent and payment-call counts.

Console and `pageerror` events fail each test. The sole exclusion is Chromium's
generic failed-resource console line for the deliberately asserted HTTP 403
blocked-order response; the response status and body are asserted directly.
