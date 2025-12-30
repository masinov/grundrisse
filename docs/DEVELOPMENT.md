# Development

This repo is scaffolded to implement the pipeline defined in `main_plan.txt` and `revision.txt`.

## Local Postgres

- Start DB: `docker compose -f ops/docker-compose.yml up`
- DB URL default: `postgresql+psycopg://grundrisse:grundrisse@localhost:5432/grundrisse`

`ops/sql/init.sql` enables `pgcrypto` and `pgvector`.

## Python setup (editable installs)

From the repo root:

- Core: `python -m pip install -e packages/core`
- LLM contracts: `python -m pip install -e packages/llm_contracts`
- Ingest service: `python -m pip install -e services/ingest_service`
- NLP pipeline: `python -m pip install -e pipelines/nlp_pipeline` (note: **not** `-e pipelines/`)

## Migrations

Run from `packages/core/`:

- `alembic upgrade head`

Configure DB via env var:

- `GRUNDRISSE_DATABASE_URL=... alembic upgrade head`

## Next coding steps (Day-1 vertical slice)

1. Implement `services/ingest_service`:
   - snapshot raw HTML (store bytes + checksum) and record `IngestRun`
   - parse into `TextBlock` with `author_id_override`/`block_subtype` when applicable
   - normalize paragraphs and sentence-split into `SentenceSpan`
2. Implement `pipelines/nlp_pipeline` Stage A:
   - build context windows (`CONTEXT_ONLY` + `TARGET`)
   - validate outputs against `packages/llm_contracts/.../schemas/`
   - write `ExtractionRun` + `ConceptMention` + `Claim` + evidence `SpanGroup`s

## GLM (Z.ai) configuration

This repo expects Z.ai’s OpenAI-compatible endpoint:

- Base URL: `https://api.z.ai/api/paas/v4`
- Chat endpoint: `POST /chat/completions`

Env vars:

- `GRUNDRISSE_ZAI_API_KEY` (Bearer token)
- `GRUNDRISSE_ZAI_BASE_URL` (default `https://api.z.ai/api/paas/v4`)
- `GRUNDRISSE_ZAI_MODEL` (default `glm-4.7`)
- `GRUNDRISSE_ZAI_TIMEOUT_S` (default `60.0`, increase if you see ReadTimeouts)
- For extraction runs, keep thinking disabled unless you have a reason: `GRUNDRISSE_ZAI_THINKING_ENABLED=false`

If your Z.ai key is provisioned under the "coding" resource package, set:

- `GRUNDRISSE_ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4`

## Running Stage A (after ingest)

Once you have an `edition_id` in Postgres:

- `GRUNDRISSE_ZAI_API_KEY=... grundrisse-nlp stage-a <edition_uuid>`
  - add `--progress-every 10` to print progress
  - add `--commit-every 5` to reduce transaction overhead

Stage A is designed to be robust to minor model “label drift” (e.g. `claim_type="premise"`). The pipeline:

- records unknown categorical values into `*_raw` columns and leaves canonical fields NULL (no forced coercion)

After running Stage A, inspect drift:

- `grundrisse-nlp modality-stats <edition_uuid>`
- `grundrisse-nlp claim-type-stats <edition_uuid>`
- `grundrisse-nlp polarity-stats <edition_uuid>`
- `grundrisse-nlp dialectical-stats <edition_uuid>`
- `grundrisse-nlp attribution-stats <edition_uuid>`
- `grundrisse-nlp technicality-stats <edition_uuid>`

## Performance notes

Stage A performs two LLM calls per paragraph (A1 mentions + A3 claims) and reuses an HTTP client
connection pool. If runs are still slow, reduce `GRUNDRISSE_LLM_MAX_TOKENS` and increase parallelism only
after idempotent skipping is implemented.

## Idempotent skipping / resuming

Stage A will skip paragraphs that already have a successful extraction run for the current prompt version.
This makes it safe to stop and restart without re-calling the LLM.

## Running ingest (single page)

Example (override author/title for now; we’ll improve inference/crawling next):

- `grundrisse-ingest ingest --language en --author "Karl Marx" --title "Economic and Philosophic Manuscripts of 1844" <work_url>`

This writes raw HTML snapshots to `data/raw/` and persists `Edition/TextBlock/Paragraph/SentenceSpan` to Postgres.

## Running ingest (multi-page work)

For works split across multiple pages, ingest the whole directory into ONE Edition:

- `grundrisse-ingest ingest-work --language en --author "Karl Marx" --title "Manifesto of the Communist Party" https://www.marxists.org/archive/marx/works/1848/communist-manifesto/preface.htm`

This will:

- recursively discover URLs within the same directory as the root page (bounded by `--max-pages`)
- snapshot each page to `data/raw/`
- write a manifest `data/raw/ingest_run_<uuid>.json`
- persist all paragraphs/sentence spans to a single `edition_id`
