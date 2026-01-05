## Work dates: retrieval vs derivation

This repo stores **date evidence** (from external sources and from ingested HTML headers) and then derives a
deterministic **date bundle** per work without re-fetching anything.

### Data flow

1) **Ingest HTML** (already in the pipeline)
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

### Why this exists

- We avoid day-long re-scrapes: extraction + derivation are **no-network**.
- We keep provenance: evidence is stored (raw + structured) and derivation is reproducible.
- UI does not hardcode date rules: `work_date_derived.display_date_field` makes the policy explicit.
