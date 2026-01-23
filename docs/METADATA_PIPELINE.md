# Metadata Pipeline Documentation

This document describes the unified metadata pipeline for the Grundrisse corpus. The pipeline extracts, resolves, and derives publication dates for all works in the corpus.

## Overview

The metadata pipeline consists of 5 steps that run in sequence:

1. **Extract Metadata**: Parse Marxists.org HTML headers and source URLs for date information
2. **Resolve Authors**: Fetch author birth/death years from Wikidata
3. **Resolve Dates**: Query external APIs (OpenLibrary, Wikidata) for publication dates
4. **Derive Dates**: Analyze all evidence and derive the most likely date using confidence scoring
5. **Finalize Dates**: Copy derived dates to the canonical `first_publication_date` field

## Quick Start

### Prerequisites

1. Start the database:
   ```bash
   docker compose -f ops/docker-compose.yml up -d
   ```

2. Install packages (from repo root):
   ```bash
   python -m pip install -e packages/core -e packages/llm_contracts -e services/ingest_service
   ```

3. Run migrations:
   ```bash
   cd packages/core && alembic upgrade head
   ```

### Running the Pipeline

```bash
# Run the complete pipeline
python scripts/pipeline/metadata.py --all

# Run a specific step
python scripts/pipeline/metadata.py --step extract_metadata
python scripts/pipeline/metadata.py --step resolve_authors
python scripts/pipeline/metadata.py --step resolve_dates
python scripts/pipeline/metadata.py --step derive_dates
python scripts/pipeline/metadata.py --step finalize_dates

# Check pipeline status
python scripts/pipeline/metadata.py --status

# Run pipeline but skip specific steps
python scripts/pipeline/metadata.py --all --skip resolve_dates

# Dry run (show what would be done)
python scripts/pipeline/metadata.py --all --dry-run
```

## Pipeline Steps

### Step 1: Extract Metadata

**CLI commands:**
- `extract-marxists-source-metadata`: Parses HTML headers from Marxists.org
- `materialize-marxists-header`: Converts parsed headers to evidence rows

**What it does:**
- Extracts publication metadata from HTML `<head>` elements
- Parses dates from source URL paths (e.g., `/1844/` in URL)
- Creates `WorkMetadataEvidence` rows with source-specific confidence scores

**Output:** Metadata evidence in `work_metadata_evidence` table

### Step 2: Resolve Authors

**CLI command:**
- `resolve-author-lifespans`: Queries Wikidata for author birth/death years

**What it does:**
- Finds authors missing `birth_year` or `death_year`
- Queries Wikidata API for lifespan data
- Updates `author` table with resolved dates

**Output:** Populated `author.birth_year` and `author.death_year`

### Step 3: Resolve Dates

**CLI command:**
- `resolve-publication-dates`: Queries external APIs for publication dates

**What it does:**
- Finds works with unknown or low-confidence dates
- Queries OpenLibrary, Wikidata, and other sources
- Creates new evidence rows with API-provided dates

**Output:** Additional metadata evidence with varying confidence scores

### Step 4: Derive Dates

**CLI command:**
- `derive-work-dates`: Analyzes evidence and derives final dates

**What it does:**
- Collects all evidence for each work
- Applies confidence scoring:
  - URL dates: 0.98 (highest)
  - Header metadata: 0.70-0.90
  - OpenLibrary: 0.10-0.14
  - Wikidata: 0.60
  - Manual research: 0.60-0.90
- Selects highest-confidence date
- Handles posthumous publications correctly
- Writes to `work_date_derived` table

**Output:** Derived dates with provenance tracking

### Step 5: Finalize Dates

**CLI command:**
- `finalize-first-publication-dates`: Copies derived dates to canonical field

**What it does:**
- Copies `work_date_derived.display_date` to `work.first_publication_date`
- Makes dates available for API queries

**Output:** Populated `work.first_publication_date` for all works

## Evidence Sources and Confidence Scores

| Source | Confidence | Notes |
|--------|------------|-------|
| `marxists_url_path` | 0.98 | URL structure is highly reliable |
| `html_header_writing` | 0.90 | "Written" dates from HTML headers |
| `html_header_first_published` | 0.85 | First publication dates |
| `html_header_source` | 0.70 | Source publication dates |
| `wikidata_work` | 0.60 | Wikidata publication dates |
| `manual_research` | 0.60-0.90 | Manually researched dates |
| `openlibrary` | 0.10-0.14 | Low confidence (often edition dates, not original) |

## Current Status

As of the latest run:

- **Total works**: 19,098
- **Coverage**: 99.8% (19,069/19,098)
- **Remaining unknown**: 29 works (genuinely undatable from available sources)

## Data Model

### Key Tables

- `work`: Canonical works (title, author, type)
- `author`: Author information (name, birth/death years)
- `edition`: Language-specific versions with source URLs
- `work_metadata_evidence`: Raw evidence from various sources
- `work_metadata_run`: Pipeline execution tracking
- `work_date_derived`: Derived dates with provenance

### Evidence Flow

```
HTML/URL/API → WorkMetadataEvidence → WorkDateDerived → Work.first_publication_date
```

## Troubleshooting

### Pipeline fails at Step 1

- Check that works have been ingested: `SELECT COUNT(*) FROM work;`
- Verify editions have source URLs: `SELECT COUNT(*) FROM edition WHERE source_url IS NOT NULL;`

### Low coverage after Step 4

- Check evidence count: `SELECT source_name, COUNT(*) FROM work_metadata_evidence GROUP BY source_name;`
- Some works may genuinely have no determinable date

### Date seems incorrect

- Check provenance: `SELECT * FROM work_date_derived WHERE work_id = '...';`
- View all evidence for a work:
  ```sql
  SELECT source_name, extracted, score, retrieved_at
  FROM work_metadata_evidence
  WHERE work_id = '...'
  ORDER BY score DESC;
  ```

## Reproducibility

To reproduce the exact database state:

1. Clone repository
2. Start database with `docker compose -f ops/docker-compose.yml up -d`
3. Run migrations: `cd packages/core && alembic upgrade head`
4. Ingest works (see INGESTION.md for details)
5. Run metadata pipeline: `python scripts/pipeline/metadata.py --all`

The pipeline uses deterministic UUIDs and idempotent operations, so re-running will produce identical results.
