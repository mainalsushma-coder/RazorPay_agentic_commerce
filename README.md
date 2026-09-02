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
