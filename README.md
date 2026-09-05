# Agentic Commerce Gateway

API Gateway for the Agentic Commerce system built with FastAPI and `uv`.

## Project Structure

```
agentic-commerce-gateway/
│
├── app/
│   ├── __init__.py
│   └── main.py
│
├── .venv/
├── pyproject.toml
├── uv.lock
└── README.md
```

## Running the Application

Start the FastAPI development server:

```bash
uv run fastapi dev app/main.py
```

Or using uvicorn directly:

```bash
uv run uvicorn app.main:app --reload
```

## API Documentation

Once the server is running:
- **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

## Catalog architecture

Buyer search, MCP, order creation, and confirmation read only from the active
catalog through `CatalogRepository`. The prototype binds that interface to
`InMemoryCatalogRepository`, seeded with GlowCare and TechHub. Production can
bind the same interface to a `PostgreSQLCatalogRepository` without rewriting
commerce or policy logic.

CSV and JSON uploads are held in an in-memory staging store. They pass through
one readiness, deterministic repair, merchant-resolution, and authoritative
`Product` validation pipeline. Staged records are never visible to buyers, MCP,
orders, or Razorpay. A merchant must explicitly activate a 100%-ready catalog.

CSV fields are `sku,name,category,description,price,currency,stock,attributes`.
`attributes` is optional and, when supplied, must be a JSON object encoded as a
CSV string. Demo files are in `demo/`.

### My Orders prototype

The buyer navigation links to `/orders`, with read-only details in an accessible modal and data from `/buyer/order-history`. Shopping workspace shows the latest three orders and a View all orders link. Orders and audit state are shared within the current FastAPI process, are not account-isolated, and disappear on restart; no database was added. Earlier orders may lack creation metadata.

`created` is displayed as **Order created**, with **Awaiting payment**: only a Razorpay order object exists, and payment completion is not tracked. `requires_confirmation` is **Confirmation required**; `blocked` is **Blocked**; unknown states are **Status unavailable**. Blocked audit attempts without an order ID appear separately and never become orders. Confirmation is identified from linked human-confirmed audit events. Shopify discovery does not create BOUND orders. Test Mode is indicated only when creation metadata identifies a Razorpay test key. Details expose an allowlist of fields and safe audit labels, never raw payment payloads.
