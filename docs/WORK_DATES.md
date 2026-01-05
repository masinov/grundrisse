## Work dates: retrieval vs derivation

This repo stores **date evidence** (from external sources and from ingested HTML headers) and then derives a
deterministic **date bundle** per work without re-fetching anything.

Terminology note: this document uses **crawl/ingest** to mean “fetch HTML + store raw snapshots + persist text”.
This is separate from the **NLP pipelines** (“Stage A/B”) that operate on already-ingested text.

## Quick start (from zero local data)

This is the clean, reproducible, end-to-end sequence to populate the DB with:
- marxists.org text (ingested)
- stored date evidence (append-only)
- derived work-level date bundles (deterministic)

### Prereqs

1) Ensure Postgres is running and reachable.

2) Point the app at the DB:
- Set `GRUNDRISSE_DATABASE_URL`, e.g.:
  - `export GRUNDRISSE_DATABASE_URL="postgresql+psycopg://grundrisse:grundrisse@localhost:5432/grundrisse"`

3) Run migrations:
- `cd packages/core && ../../.venv/bin/alembic upgrade head`

4) Install the packages in editable mode:
- `.venv/bin/pip install -e packages/core -e services/ingest_service`

### Phase 1: Fetch + ingest text (network)

Use one of the following:

**A) Ingest a single work (recommended for testing)**

Example:
- `grundrisse-ingest ingest-work "https://www.marxists.org/archive/trotsky/1930/italy.htm" --language en --author "Leon Trotsky" --title "A Letter on the Italian Revolution" --max-pages 100`

**B) Crawl-discover + ingest many works**

Example (bounded):
- `grundrisse-ingest crawl-discover --max-languages 1 --max-authors 500 --max-works 200 --crawl-delay 0.6`
- Note the printed `crawl_run_id`, then:
- `grundrisse-ingest crawl-ingest <CRAWL_RUN_ID> --max-works 100000`

This writes raw snapshots into `data/raw/` and persists the text into Postgres (editions/paragraphs/etc).

### Phase 2: Fetch metadata evidence (network, append-only)

These commands are the *only* ones that should need network access for dates.
They write evidence rows you can reuse forever.

- Resolve author lifespans:
  - `grundrisse-ingest resolve-author-lifespans --limit 200000`

- Fetch external work date evidence (Wikidata/OpenLibrary):
  - `grundrisse-ingest resolve-publication-dates --sources wikidata,openlibrary --limit 200000 --min-score 0.90 --crawl-delay-s 0.6`

Notes:
- `resolve-publication-dates` stores provenance in `work_metadata_evidence` and uses a disk cache under `data/cache/publication_dates/`.
- For marxists.org works, prefer the no-network Phase 3 extraction instead of re-fetching HTML.

### Phase 3: Local extraction + derivation (no network; safe to rerun)

1) Extract marxists header metadata from already-ingested snapshots:
- `grundrisse-ingest extract-marxists-source-metadata --limit 200000 --progress-every 500`

2) Materialize a query-friendly header table:
- `grundrisse-ingest materialize-marxists-header --limit 200000 --progress-every 500`

3) Canonicalize names for display/search:
- `grundrisse-ingest canonicalize-work-titles --no-only-missing --limit 200000`
- `grundrisse-ingest author-deduplicate`
- `grundrisse-ingest author-apply-mappings`

4) Derive the deterministic work date bundle:
- `grundrisse-ingest derive-work-dates --force --limit 200000 --progress-every 2000`

Output:
- `work_date_derived.dates`: multi-date bundle (written / first publication / edition publication / upload-ish / heuristic)
- `work_date_derived.display_date_field`: explicit UI selector (`first_publication_date` or `written_date`)
- `work_date_derived.display_year`: indexed year for filtering/sorting

### Data flow

1) **Ingest HTML** (network)
   - Raw snapshots live in `data/raw/*.html` and ingest manifests in `data/raw/ingest_run_*.json`.

2) **Extract source header metadata** (no network)
   - Backfills `edition.source_metadata` from already-ingested marxists.org pages:
   - `grundrisse-ingest extract-marxists-source-metadata --limit 200000 --progress-every 500`

2b) **Materialize normalized header table** (no network)
   - Writes `edition_source_header` from `edition.source_metadata`:
   - `grundrisse-ingest materialize-marxists-header --limit 200000 --progress-every 500`

3) **Fetch external date evidence** (network, append-only)
   - `grundrisse-ingest resolve-publication-dates` writes candidates into `work_metadata_evidence`.
   - Prefer `--sources wikidata,openlibrary` when you want original-publication dates for non-marxists works.

4) **Derive work date bundle** (no network, deterministic)
   - Derives a multi-date bundle per work from stored evidence only:
   - `grundrisse-ingest derive-work-dates --limit 200000 --progress-every 500`
   - Writes to `work_date_derived`:
     - `dates`: a JSON bundle (written / first publication / edition-year / heuristic-year / upload-year)
     - `display_date`: selected date for UI ordering
     - `display_date_field`: explicit selector (`first_publication_date` or `written_date`)
     - `display_year`: indexed year for filtering/sorting

### Migrations

- `0018_edition_source_metadata`: adds `edition.source_metadata`
- `0019_work_date_derived`: adds `work_date_derivation_run` + `work_date_derived`
- `0020_edition_source_header`: adds `edition_source_header`

### Auditing / sanity checks (optional)

These are useful to confirm you’re not “accidentally upgrading” to edition/upload years.

If you run Postgres in Docker:
- `sudo docker exec -i <POSTGRES_CONTAINER> psql -U grundrisse -d grundrisse -c "<SQL>"`

Example: distribution of first-publication sources for post-death display years:
- `select wdd.dates->'first_publication_date'->>'source' as source, count(*) from work_date_derived wdd join work w on w.work_id=wdd.work_id join author a on a.author_id=w.author_id where wdd.display_year is not null and a.death_year is not null and wdd.display_year > a.death_year + 5 group by 1 order by 2 desc;`

### Legacy / deprecated

The following commands were part of earlier iterations and should be avoided for new runs:
- `finalize-first-publication-dates` (superseded by `derive-work-dates`)
- `extract-publication-years` (URL heuristic; keep only as a fallback evidence source)
- Directly relying on `work.publication_date` for chronology (use `work_date_derived` instead)

### Why this exists

- We avoid day-long re-scrapes: extraction + derivation are **no-network**.
- We keep provenance: evidence is stored (raw + structured) and derivation is reproducible.
- UI does not hardcode date rules: `work_date_derived.display_date_field` makes the policy explicit.
