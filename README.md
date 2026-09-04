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
