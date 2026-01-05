# Grundrisse API

REST API for the Grundrisse frontend, serving corpus data from the PostgreSQL database.

## Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies (from repo root, so grundrisse-core is available)
pip install -e ../packages/core
pip install -e ".[dev]"

# Set environment variables (matches ops/docker-compose.yml)
export API_DATABASE_URL="postgresql://grundrisse:grundrisse@localhost:5432/grundrisse"
export API_CORS_ORIGINS="http://localhost:3000"

# Run development server
uvicorn api.main:app --reload --port 8000
```

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| GET | /api/stats | Corpus statistics |
| GET | /api/authors | List authors |
| GET | /api/authors/{id} | Author detail with works |
| GET | /api/works | List works |
| GET | /api/works/{id} | Work detail |
| GET | /api/works/{id}/paragraphs | Work paragraphs |
| GET | /api/paragraphs/{id}/extractions | Paragraph concepts & claims |
| GET | /api/search | Search authors and works |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| API_DATABASE_URL | postgresql://grundrisse:grundrisse@localhost:5432/grundrisse | Database connection string |
| API_CORS_ORIGINS | http://localhost:3000 | Comma-separated allowed origins |
| API_DEBUG | false | Enable debug mode |
