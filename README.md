# grundrisse
A provenance-first pipeline for concept, claim, and dialectical analysis of Marxist theoretical corpora.

## Structure

- `packages/core/`: DB schema + shared domain (Alembic migrations)
- `packages/llm_contracts/`: JSON schemas + validators (LLM contracts)
- `services/ingest_service/`: marxists.org ingestion (snapshot → normalize → segment)
- `pipelines/nlp_pipeline/`: extraction and canonicalization pipeline (Stage A/B)
- `ops/`: local Postgres + pgvector
- `docs/ROADMAP.md`: implementation roadmap aligned with `main_plan.txt` and `revision.txt`

## Quickstart

- `docker compose -f ops/docker-compose.yml up`
- `python -m pip install -e packages/core -e packages/llm_contracts -e services/ingest_service -e pipelines/nlp_pipeline`
- `cd packages/core && alembic upgrade head`

See `docs/DEVELOPMENT.md`.
