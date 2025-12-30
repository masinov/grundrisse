# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Grundrisse is a provenance-first pipeline for concept, claim, and dialectical analysis of Marxist theoretical corpora. It ingests texts from marxists.org, extracts structured claims and concept mentions using LLMs, and builds a queryable knowledge graph with full evidence traceability.

## Core Design Principles

### Provenance-First Immutability

The system is built around immutable text substrate with versioned extraction runs:

1. **Immutable substrate**: `Edition`, `TextBlock`, `Paragraph`, and `SentenceSpan` are never modified after creation
2. **Evidence grounding**: Every semantic artifact (claim, mention, concept) must trace back to `SentenceSpan` evidence via `SpanGroup`
3. **Versioned extraction**: `ExtractionRun` records model name, prompt version, and schema hash; re-running with new prompts creates new runs without destroying old data
4. **Atomic evidence units**: `SentenceSpan` is the smallest unit of evidence; all claims cite ordered spans (not unauditable summaries)
5. **Paragraph-scoped extraction**: Stage A extracts per-paragraph but outputs sentence-level evidence indices

**Critical constraint**: Claims must cite paragraph-local sentence spans only. Cross-paragraph discourse links require a separate pass (future "A6" stage).

### Deterministic Identity

The system uses UUID v5 for deterministic IDs (see `packages/core/src/grundrisse_core/identity.py`):
- `author_id_for(name)`: UUID from canonical author name
- `work_id_for(author_id, title)`: UUID from author + title
- `edition_id_for(work_id, language, source_url)`: UUID from work + language + source URL

This enables idempotent reingest: re-running with same inputs reuses the same Edition.

**Important**: If parser output changes (different block paths, paragraph hashes, or ordering), ingestion raises an error to prevent mutation of existing Edition. To force new ingestion, change `source_url` (e.g., add `?run=4` query param).

## Architecture

### Multi-package Monorepo

- **`packages/core/`**: SQLAlchemy models, Alembic migrations, enums, identity functions (`author_id_for`, `work_id_for`, etc.), hashing utilities, and settings
- **`packages/llm_contracts/`**: Versioned JSON schemas (`task_a1_concept_mentions.json`, `task_a3_claims.json`, etc.) and validators for LLM I/O
- **`services/ingest_service/`**: HTML ingestion (snapshot → parse → segment)
  - `crawl/discover.py`: multi-page work URL discovery
  - `parse/html_to_blocks.py`: strip chrome, detect headings, infer author overrides (prefaces/afterwords)
  - `segment/sentences.py`: paragraph → sentence span tokenization
- **`pipelines/nlp_pipeline/`**: Two-stage extraction pipeline
  - `stage_a/`: per-paragraph concept mentions + claims (2 LLM calls)
  - `stage_b/`: concept canonicalization via clustering within a work
- **`ops/`**: Docker Compose for local Postgres 16 + pgvector

### Data Model Hierarchy

The schema models provenance-first immutable snapshots in five layers:

1. **Corpus**: `Author` → `Work` (canonical works, independent of editions/translations)
2. **Ingestion**: `IngestRun` (snapshot metadata) → `Edition` (language-specific version of a Work)
3. **Structure**: `Edition` → `TextBlock` (chapters/sections with hierarchical `parent_block_id`, author overrides for prefaces/afterwords) → `Paragraph` (normalized text with content hash) → `SentenceSpan` (atomic evidence units with prev/next links)
4. **Extraction**: `ExtractionRun` (prompt version, model fingerprint) → `ConceptMention` / `Claim`
   - Evidence: `SpanGroup` (ordered collection of `SentenceSpan`s) linked via `ClaimEvidence` / `ConceptEvidence`
5. **Canonicalization**: `Concept` (gloss, aliases, temporal scope) with `ConceptMention.concept_id` assignments

**Key tables**:
- `SpanGroup`: Represents an ordered set of `SentenceSpan`s (evidence for a claim/concept)
- `SpanGroupSpan`: Join table linking `SpanGroup` to individual `SentenceSpan`s with `order_index`
- `TextBlock.author_id_override`: Enables granular authorship (e.g., "Preface by Engels" in a Marx work)
- `ExtractionRun`: Records `pipeline_version`, `prompt_name`, `prompt_version`, `model_name`, `output_hash` for full reproducibility

### LLM Provider Configuration

The pipeline uses Z.ai's OpenAI-compatible endpoint for GLM models:

Environment variables:
- `GRUNDRISSE_ZAI_API_KEY` (required): Bearer token for Z.ai API
- `GRUNDRISSE_ZAI_BASE_URL`: defaults to `https://api.z.ai/api/paas/v4`
  - If using "coding" resource package, use `https://api.z.ai/api/coding/paas/v4`
- `GRUNDRISSE_ZAI_MODEL`: defaults to `glm-4.7`
- `GRUNDRISSE_ZAI_TIMEOUT_S`: defaults to `60.0`
- `GRUNDRISSE_ZAI_THINKING_ENABLED`: set to `false` for extraction runs (default)

Database:
- `GRUNDRISSE_DATABASE_URL`: defaults to `postgresql+psycopg://grundrisse:grundrisse@localhost:5432/grundrisse`

### Stage A: Paragraph-Level Extraction

Stage A processes each paragraph with **two sequential LLM calls**:

1. **A1 - Concept Mentions** (`task_a1_concept_mentions.json`):
   - Extracts concept mentions with surface form, normalized form, technicality rating
   - Outputs sentence-level indices (which sentences contain each mention)
   - Schema validates technicality as boolean, but stores raw string in `is_technical_raw` for drift tracking

2. **A3 - Claims** (`task_a3_claims.json`):
   - Extracts claims with canonical text, type, polarity, modality, dialectical status, attribution
   - Each claim cites evidence via sentence indices (paragraph-local only)
   - Records `claim_type_raw`, `polarity_raw`, `modality_raw`, `dialectical_status_raw`, `attribution_raw` to track model drift

**Context windows**: Prompts include surrounding sentence context (CONTEXT_ONLY spans) for anaphora resolution, but extraction outputs must cite only TARGET paragraph spans.

**Idempotent skipping**: Pipeline checks if paragraph already has successful extraction run for current `(prompt_name, prompt_version)` and skips re-processing. Safe to stop/resume.

**Evidence integrity**: All evidence indices resolve to `SentenceSpan` IDs within the target paragraph. Cross-paragraph citations are forbidden (enforced by pipeline logic).

### Stage B: Concept Canonicalization

Stage B clusters unassigned `ConceptMention`s within a `work_id` and canonicalizes them into `Concept` nodes:
- Conservative sense splitting (prefer distinct concepts over premature merging)
- Outputs: `label_canonical`, `gloss`, `aliases`, `temporal_scope`
- Assigns `ConceptMention.concept_id` to link mentions to canonical concepts
- `root_concept_id` enables historical sense grouping without flattening differences

## Development Setup

### Initial Setup

1. Start database:
   ```bash
   docker compose -f ops/docker-compose.yml up
   ```

2. Install packages (editable mode from repo root):
   ```bash
   python -m pip install -e packages/core -e packages/llm_contracts -e services/ingest_service -e pipelines/nlp_pipeline
   ```
   Note: Install `pipelines/nlp_pipeline` (NOT just `pipelines/`)

3. Run migrations:
   ```bash
   cd packages/core && alembic upgrade head
   ```

### Common Commands

#### Linting
```bash
ruff check .
ruff format .
```

#### Database Migrations

From `packages/core/`:
```bash
# Apply migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Use custom DB URL
GRUNDRISSE_DATABASE_URL=... alembic upgrade head
```

#### Ingestion

Single page:
```bash
grundrisse-ingest ingest --language en --author "Karl Marx" --title "Economic and Philosophic Manuscripts of 1844" <work_url>
```

Multi-page work (discovers pages in same directory):
```bash
grundrisse-ingest ingest-work --language en --author "Karl Marx" --title "Manifesto of the Communist Party" <root_url>
```
- Adds `--max-pages` limit (default protects against runaway crawl)
- Writes manifest to `data/raw/ingest_run_<uuid>.json`
- All pages → single `edition_id`

**Idempotency**: Re-running with same inputs reuses the same deterministic `edition_id`. If parser output changes, ingestion raises an error to avoid mutating existing Edition. To force new ingestion, change `source_url` (e.g., add `?run=4` query param).

**Author override detection**: The parser automatically detects author overrides from heading patterns (e.g., "Preface by Engels", "Afterword by Marx") and sets `TextBlock.author_id_override` and `author_role`. This enables granular attribution for prefaces, afterwords, and editorial apparatus.

#### NLP Pipeline

Run Stage A (after ingest):
```bash
GRUNDRISSE_ZAI_API_KEY=... grundrisse-nlp stage-a <edition_uuid> --progress-every 10 --commit-every 5
```
- `--progress-every N`: print progress every N paragraphs
- `--commit-every N`: commit transaction every N paragraphs (reduces overhead)
- `--include-apparatus`: include TOC/navigation/license blocks (default: skip)

Inspect label drift after Stage A:
```bash
grundrisse-nlp modality-stats <edition_uuid>
grundrisse-nlp claim-type-stats <edition_uuid>
grundrisse-nlp polarity-stats <edition_uuid>
grundrisse-nlp dialectical-stats <edition_uuid>
grundrisse-nlp attribution-stats <edition_uuid>
grundrisse-nlp technicality-stats <edition_uuid>
```

Spot-check validation:
```bash
grundrisse-nlp sample-edition <edition_uuid> --n 5 --include-no-mentions 2 --include-no-claims 2
```

Run Stage B (concept canonicalization):
```bash
GRUNDRISSE_ZAI_API_KEY=... grundrisse-nlp stage-b <work_uuid>
```

## Code Patterns & Constraints

### Enum Usage

All categorical values use string enums in `packages/core/src/grundrisse_core/db/enums.py`:
- **Structural**: `WorkType`, `TextBlockType`, `BlockSubtype`, `AuthorRole`
- **Extraction**: `ClaimType`, `Polarity`, `Modality`, `DialecticalStatus`, `ClaimAttribution`
- **Linking**: `ClaimLinkType`, `AlignmentType`

**Important**: When adding new categorical values, update BOTH:
1. The enum definition in `enums.py`
2. Related LLM contract schemas in `packages/llm_contracts/src/grundrisse_contracts/schemas/`

### Label Drift Handling

Stage A is designed to be robust to model "label drift" (when LLM outputs values not in current enum):

**Pattern**:
- Unknown categorical values → stored in `*_raw` columns (e.g., `claim_type_raw`, `polarity_raw`)
- Canonical enum fields → `NULL` (no forced coercion that would hide drift)
- Models can return `claim_type="premise"` even if not in `ClaimType` enum → pipeline stores raw value, sets `claim_type=NULL`

**Workflow**:
1. Run Stage A
2. Use stats commands to inspect drift:
   ```bash
   grundrisse-nlp modality-stats <edition_uuid>
   grundrisse-nlp claim-type-stats <edition_uuid>
   ```
3. Decide whether to:
   - Add new values to enums (if valid semantic categories)
   - Update LLM schemas to constrain outputs more strictly
   - Improve prompts to reduce drift

### LLM Contract Versioning

JSON schemas in `packages/llm_contracts/src/grundrisse_contracts/schemas/` define strict contracts for LLM I/O:
- `task_a1_concept_mentions.json`: A1 extraction schema
- `task_a3_claims.json`: A3 extraction schema
- `task_b_concept_canonicalize.json`: Stage B schema

**Versioning strategy**: Create new filenames (e.g., `task_a3_claims_v2.json`) to maintain provenance. `ExtractionRun.prompt_version` tracks which schema version produced which extractions.

### Validation & Testing

The system has **minimal automated tests**. Validation relies on:

1. **DB integrity gates** (must pass):
   - Every `SpanGroupSpan.span_id` belongs to same `edition_id` as its `SpanGroup.edition_id`
   - If `SpanGroup.para_id` set, all grouped spans have same `para_id`
   - No empty `SpanGroup`s

2. **Coverage metrics** (should be explainable):
   - Paragraphs with spans but no mentions/claims (often headings/apparatus)
   - Stage B concept assignment percentage
   - Per-edition paragraph/span/mention/claim counts

3. **Targeted spot-check sampling** (human validation):
   ```bash
   grundrisse-nlp sample-edition <edition_uuid> --n 5 --include-no-mentions 2 --include-no-claims 2
   ```
   Acceptance criteria: evidence indices correct, claims grounded, concepts not garbage merges

See `docs/VALIDATION.md` for details.

### Common Failure Modes

1. **Ingestion idempotency violation**: Re-ingesting with same inputs but different parser output raises error. Fix: change `source_url` (add query param like `?run=4`) to create new Edition.

2. **Stage B schema drift**: Model returns invalid JSON or drifted keys. Fix strategy:
   - Retry with repair prompt including validation error
   - Allow narrow key-typo tolerance (e.g., `gloss:` → `gloss`)
   - If still failing, mark cluster as failed and persist raw output

3. **Duplicate/fragmented concepts**: Multiple `Concept`s with same `label_canonical` within a work. Fix: Stage B should reuse existing concepts when canonical label matches.

4. **Cross-paragraph evidence citations**: Claims citing spans from different paragraphs. Fix: This violates core constraint; improve A3 prompt to restrict to paragraph-local spans.

### Database Session Management

All CLI commands use `grundrisse_core.db.session.SessionLocal`:
```python
from grundrisse_core.db.session import SessionLocal

with SessionLocal() as session:
    # query/insert operations
    session.commit()
```

### Raw HTML Snapshots

Ingestion stores immutable raw HTML to `data/raw/`:
- `<checksum>.html`: raw bytes
- `<checksum>.meta.json`: fetch metadata (URL, timestamp, headers)
- `ingest_run_<uuid>.json`: multi-page work manifest

This enables deterministic replay and re-parsing without re-fetching.

## Important File References

**Core utilities** (packages/core/src/grundrisse_core/):
- `identity.py`: Deterministic UUID generation (`author_id_for`, `work_id_for`, `edition_id_for`)
- `hashing.py`: SHA-256 utilities for content hashing
- `db/models.py`: Full SQLAlchemy schema (421 lines, all tables)
- `db/enums.py`: All categorical value enums
- `db/session.py`: Database session factory

**Ingestion** (services/ingest_service/src/ingest_service/):
- `parse/html_to_blocks.py`: HTML → TextBlock parser (strips chrome, detects author overrides)
- `segment/sentences.py`: Paragraph → SentenceSpan segmentation
- `crawl/discover.py`: Multi-page work URL discovery

**Pipeline** (pipelines/nlp_pipeline/src/nlp_pipeline/):
- `stage_a/run.py`: Stage A orchestration (A1 + A3 extraction)
- `stage_b/run.py`: Stage B concept canonicalization
- `llm/zai_glm.py`: Z.ai GLM client wrapper

**Contracts** (packages/llm_contracts/src/grundrisse_contracts/schemas/):
- `task_a1_concept_mentions.json`: A1 schema
- `task_a3_claims.json`: A3 schema
- `task_b_concept_canonicalize.json`: Stage B schema

**Documentation**:
- `docs/VALIDATION.md`: Validation workflow (DB integrity gates, coverage metrics, spot-check sampling)
- `docs/DEVELOPMENT.md`: Development setup and next coding steps
- `docs/MASTER_PLAN.md`: Project roadmap and design philosophy
- `docs/ROADMAP.md`: Implementation milestones aligned with main plan
