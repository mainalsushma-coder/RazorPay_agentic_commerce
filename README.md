# BOUND

BOUND is an agentic shopping prototype that turns a buyer's goal into catalog discovery and policy-controlled order creation. The agent proposes actions; backend **Bound Guardrails** enforce purchase authority using merchant-owned product data.

**Public Render deployment:** https://razorpay-agentic-commerce-m5e1.onrender.com/

**Buildathon Track 1 positioning:** a buyer-facing commerce agent with Razorpay MCP order creation, backed by a merchant catalog onboarding workflow. The demo connects natural-language intent, authoritative catalog facts, spending controls, explicit human confirmation, and auditable order outcomes.

## Core buyer flow

1. Enter the shopping workspace at `/dashboard` and type a goal, such as “Find Vitamin C serum under 1000” or “Buy a wireless keyboard.”
2. The agent discovers connected merchants and searches relevant catalogs through storefront MCP tools. Results identify their source and checkout capability.
3. A discovery goal returns products for selection; an explicit purchase goal can request native order creation directly. The backend resolves price and stock from the active catalog and evaluates the order total.
4. Eligible orders create a Razorpay order automatically; higher-value orders wait for the buyer's confirmation; blocked requests do not reach payment execution.
5. Review the outcome and recent activity, or open **My Orders** at `/orders`.

## Native merchants vs Shopify

| Source | Catalog authority | Purchase support |
| --- | --- | --- |
| Native: GlowCare and TechHub | Active `CatalogRepository` data | INR orders through Bound Guardrails and Razorpay |
| Shopify: BOUND Commerce Test | Shopify UCP/MCP catalog search followed by product-detail verification | Discovery only; external checkout connection required |

Shopify products do not create BOUND orders or invoke Razorpay. The INR purchase mandate is not applied to Shopify discovery.

## Bound Guardrails and payment safety

Thresholds apply to each native order's authoritative total, after product, quantity, price, and stock validation:

| Order total | Decision |
| --- | --- |
| Up to and including ₹2,000 | Automatically approved |
| Above ₹2,000 through ₹10,000 inclusive | Explicit human confirmation required |
| Above ₹10,000 | Blocked |

Confirmation is unavailable to the agent as a tool. The confirmation endpoint rechecks the active product, stock, price, and maximum spend; a changed price requires a new order.

The server-side Razorpay MCP executor is restricted to **`create_order`**, using only `amount` (paise), `currency`, and `receipt`. MCP credentials must be Razorpay Test Mode keys and stay server-side. The agent has no capture, refund, transfer, or human-confirmation tool. SDK fallback is limited to failures classified as transport unavailable; rejected or ambiguous MCP results are not retried through the SDK.

**“Order created / Awaiting payment” means a Razorpay order object exists. It does not mean payment succeeded.**

## Merchant catalog lifecycle / Autopilot

At `/merchant-portal`, merchants can manage products or import CSV/JSON catalogs:

**Import → staged readiness scan → Autopilot repairs → merchant resolutions → 100% ready → explicit activation.**

Autopilot deterministically normalizes safely parseable prices and stock, and fills INR only when the price explicitly supplies currency evidence. It does not invent missing descriptions, prices, or other merchant facts. Activation also requires authoritative `Product` validation. Staged imports remain unavailable to buyer search, storefront MCP, and orders until activated. Sample catalogs are in [`demo/`](demo/).

## Voice input and My Orders

- **Voice:** browser Speech Recognition (`en-IN`) fills an editable goal draft. The buyer must review and dispatch it; transcription never submits or purchases automatically. Microphone permission and browser support are required, with typing available as fallback.
- **My Orders:** read-only history and detail dialogs show order status, product, amount, safe audit context, and payment mode when known. The workspace previews the latest three orders. Blocked audit attempts without order IDs appear separately; Shopify discovery is not an order.

## Tech stack

Python 3.11+, FastAPI/Uvicorn, Pydantic, Python MCP SDK/FastMCP, HTTPX, Razorpay MCP with SDK fallback, Shopify UCP/MCP, and vanilla HTML/CSS/JavaScript. Inference supports Ollama (default `qwen3.5:4b`) or configured OpenRouter. Tooling: uv, pytest, Playwright/Chromium. Hosting: Render. Active catalogs, staging, orders, and audit logs use in-memory storage.

## Verified tests

Latest local deterministic run: **184 passed — 160 fast tests + 24 browser E2E tests; 0 failed, 0 skipped.**

```bash
python -m pytest -q tests --ignore=tests/e2e
python -m pytest -q tests/e2e
```

The browser suite drives the real frontend and FastAPI catalog, policy, and order workflows with deterministic agent/payment substitutes and a Shopify fixture. Voice tests simulate recognition events. These counts validate local behavior, not live provider availability or payment completion; no live external calls were made for this README update.

## Prototype limitations

- Demo identities and merchant selection are not production authentication. Orders and audit history are shared across users within one process, not account-isolated.
- In-memory changes disappear on restart; there is no database implementation, durable order history, or cross-worker coordination.
- Stock is checked but not reserved or decremented. There is no payment completion tracking, fulfillment, or production-wide idempotency guarantee.
- Shopify checkout is disabled. Live inference, Shopify discovery, and Razorpay availability depend on external services and configuration; browser voice support varies.

## Recommended demo flow

1. Open the public deployment and enter the buyer workspace. Show purchase authority and the three spending bands.
2. Dispatch “Buy Vitamin C serum” from GlowCare: the seeded ₹699 item demonstrates automatic order creation. Show **Awaiting payment** and the entry in My Orders.
3. Dispatch “Buy a wireless keyboard” from TechHub: ₹3,499 requires explicit approval. Confirm and inspect the updated order.
4. Request 15 units of GlowCare Vitamin C Serum: the seeded total is ₹10,485, demonstrating a blocked request without payment execution.
5. Search for a snowboard to show Shopify discovery and disabled checkout. Optionally dictate a goal, edit the transcript, then dispatch.
6. Open the merchant portal, import `demo/example_catalog_messy.csv`, run Autopilot, supply missing merchant facts, and activate only at 100% readiness. Return to buyer search to show the activated products.
