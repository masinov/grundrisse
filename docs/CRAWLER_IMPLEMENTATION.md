# Crawler Implementation Summary

This document describes the marxists.org crawler implementation added in the `feature/marxists-org-crawler` branch.

## Overview

The crawler implements the specification in `docs/CRAWLER_BLUEPRINT.md`, providing:
- **URL catalog** - persistent tracking of discovered URLs with deduplication
- **Multi-stage crawling** - seed discovery → languages → authors → works → pages
- **Rate-limited HTTP client** - with caching, retries, and politeness
- **Seamless integration** - with existing `grundrisse-ingest` commands

## Implementation Components

### Database Schema

Added three new tables to `packages/core/src/grundrisse_core/db/models.py`:

1. **`CrawlRun`**: Tracks crawler runs with scope, status, and statistics
   - `crawl_run_id`, `pipeline_version`, `crawl_scope` (JSON)
   - `urls_discovered`, `urls_fetched`, `urls_failed` counters
   - `status`: started, completed, failed

2. **`UrlCatalogEntry`**: Persistent URL catalog with deduplication
   - `url_canonical` (unique), `discovered_from_url`, `crawl_run_id`
   - `status`: new, fetched, cached, not_found, error, skipped
   - `http_status`, `content_type`, `etag`, `last_modified`
   - `content_sha256`, `raw_path`, `fetched_at`
   - Indexes on `status` and `content_sha256`

3. **`WorkDiscovery`**: Tracks discovered works awaiting ingestion
   - `root_url`, `author_name`, `work_title`, `language`
   - `page_urls` (JSON array), `discovered_at`
   - `ingestion_status`: pending, ingested, failed
   - Optional `edition_id` FK once ingested

**Migration**: `packages/core/alembic/versions/0011_add_crawler_tables.py`

### Utilities

**`services/ingest_service/src/ingest_service/utils/url_canonicalization.py`**:
- `canonicalize_url()` - remove fragments, whitespace, normalize scheme/host
- `is_same_directory()` - work directory detection
- `get_directory_prefix()` - extract directory from URL
- `is_html_url()` - filter non-HTML resources
- `is_marxists_org_url()` - domain check

### HTTP Client

**`services/ingest_service/src/ingest_service/crawl/http_client.py`**:
- `RateLimitedHttpClient` - HTTP client with rate limiting and caching
  - Fixed crawl delay between requests
  - ETag/Last-Modified conditional requests (304 Not Modified support)
  - Exponential backoff retry logic for transient failures
  - User-Agent identification
  - Configurable timeout
- `FetchResult` dataclass - structured fetch results

### Catalog Manager

**`services/ingest_service/src/ingest_service/crawl/catalog.py`**:
- `UrlCatalog` - URL catalog operations
  - `add_url()` - add URLs with deduplication
  - `get_url()` - lookup by canonical URL
  - `update_fetch_result()` - update after fetching
  - `get_urls_by_status()` - query by status
  - `get_pending_urls()` - URLs ready to fetch

- `WorkCatalog` - work discovery operations
  - `add_work()` - record discovered works
  - `get_pending_works()` - works awaiting ingestion
  - `mark_work_ingested()` / `mark_work_failed()` - status tracking

### Multi-Stage Crawler

**`services/ingest_service/src/ingest_service/crawl/marxists_org.py`**:
- `MarxistsOrgCrawler` - marxists.org-specific crawler
  - **Stage 1**: `discover_seed_urls()` - language roots from landing page
  - **Stage 2**: `discover_author_pages()` - author indexes within language
  - **Stage 3**: `discover_work_directories()` - works from author pages
  - **Stage 4**: `discover_work_pages()` - pages within work directory
  - `snapshot_url()` - fetch and write to `data/raw/` with metadata
  - Heuristics for author/title/language extraction

### CLI Commands

Added to `services/ingest_service/src/ingest_service/cli.py`:

1. **`grundrisse-ingest crawl-discover`**
   - Performs multi-stage discovery of marxists.org works
   - Options:
     - `--seed-url` (default: https://www.marxists.org/)
     - `--max-languages` (default: 1)
     - `--max-authors` (default: 10)
     - `--max-works` (default: 5)
     - `--crawl-delay` (default: 0.5s)
   - Creates `CrawlRun` and populates `UrlCatalogEntry` + `WorkDiscovery`

2. **`grundrisse-ingest crawl-ingest <crawl_run_id>`**
   - Ingests discovered works from a crawl run
   - Reads `WorkDiscovery` table
   - Calls existing `ingest_work()` for each work
   - Options: `--max-works` (default: 10)

## Design Decisions

### Separation of Concerns

The crawler is cleanly separated from ingestion:
- **Crawler responsibilities**: URL discovery, snapshot storage, catalog tracking
- **Ingestion responsibilities** (existing): HTML parsing, block/paragraph/span extraction

The seam is the `WorkDiscovery` table and `data/raw/` snapshots.

### Idempotency

- URL catalog uses `url_canonical` unique constraint for deduplication
- ETag/Last-Modified support enables incremental crawling
- Works can be re-discovered without duplication
- Snapshots are written once by content hash

### Politeness

- Configurable crawl delay (default: 0.5s)
- User-Agent identification: `grundrisse-crawler/0.1 (marxists.org corpus builder)`
- Retry with exponential backoff
- Bounded concurrency (single-threaded by default)

### Extensibility

- Multi-stage design allows targeting specific languages/authors
- `crawl_scope` JSON field tracks scope configuration
- Status tracking enables resume capability
- Catalog structure supports future features (ETag refreshes, changed page detection)

## Usage Example

```bash
# 1. Run database migrations
cd packages/core && alembic upgrade head

# 2. Discover works (limited scope for testing)
grundrisse-ingest crawl-discover \
  --max-languages 1 \
  --max-authors 2 \
  --max-works 3 \
  --crawl-delay 1.0

# Output: Crawl run ID (e.g., 123e4567-e89b-12d3-a456-426614174000)

# 3. Ingest discovered works
grundrisse-ingest crawl-ingest 123e4567-e89b-12d3-a456-426614174000 --max-works 3

# 4. Verify ingestion
# - Check `edition` table for new entries
# - Run Stage A extraction on ingested editions
```

## Integration with Existing System

### Compatibility

- Reuses existing `discover_work_urls()` logic for page discovery
- Calls existing `ingest_work()` for ingestion
- Uses existing `snapshot_url()` infrastructure (but crawler adds its own variant)
- Stores raw HTML to `data/raw/` following existing convention
- Compatible with deterministic Edition ID generation

### Database

- New tables coexist with existing schema
- Foreign key from `WorkDiscovery.edition_id` to `Edition`
- No modifications to existing tables

### No Breaking Changes

- All existing CLI commands work unchanged
- Existing ingestion workflow unaffected
- New tables are optional (system works without crawler)

## Future Enhancements

Per `CRAWLER_BLUEPRINT.md`, Phase 2-3 improvements:

1. **Full site traversal**: Expand to all languages, handle special-case index structures
2. **Resume support**: Query `UrlCatalogEntry` for pending/failed URLs and resume
3. **Incremental refresh**: Use ETag/Last-Modified to detect changed pages
4. **LLM-assisted metadata extraction**: For author/title when heuristics fail
5. **Parallel fetching**: Bounded concurrency with connection pooling
6. **Progress tracking**: Detailed metrics and dashboards
7. **robots.txt support**: Explicit robots.txt parser

## Testing Checklist

- [ ] Database migration runs cleanly (`alembic upgrade head`)
- [ ] `crawl-discover` command runs without errors
- [ ] URL catalog populated with discovered URLs
- [ ] Work catalog contains valid work metadata
- [ ] `crawl-ingest` successfully calls `ingest_work()`
- [ ] Snapshots written to `data/raw/` with correct checksums
- [ ] Rate limiting observed (timestamps in logs)
- [ ] Stage A/B can run on ingested editions
- [ ] Evidence integrity gates pass

## Files Changed

### New Files
- `packages/core/alembic/versions/0011_add_crawler_tables.py`
- `services/ingest_service/src/ingest_service/utils/url_canonicalization.py`
- `services/ingest_service/src/ingest_service/crawl/http_client.py`
- `services/ingest_service/src/ingest_service/crawl/catalog.py`
- `services/ingest_service/src/ingest_service/crawl/marxists_org.py`
- `docs/CRAWLER_IMPLEMENTATION.md` (this file)

### Modified Files
- `packages/core/src/grundrisse_core/db/models.py` (added 3 models)
- `services/ingest_service/src/ingest_service/cli.py` (added 2 commands)

## Alignment with Blueprint

This implementation addresses all Phase 1 deliverables from `CRAWLER_BLUEPRINT.md`:

✅ **Deliverable A**: URL catalog with canonical normalization, dedup, status tracking
✅ **Deliverable B**: Multi-stage crawl strategy (seed → language → author → work)
✅ **Deliverable C**: Immutable snapshots to `data/raw/` with checksums and metadata
✅ **Deliverable D**: Seamless integration via existing `ingest_work()` CLI

Meets all constraints:
✅ Immutable substrate (new Editions only, never mutate)
✅ Atomic evidence (reuses existing SentenceSpan infrastructure)
✅ Provenance-first (CrawlRun tracks all discovery)
✅ Determinism (canonical URLs, deterministic Edition IDs)
✅ Politeness (rate limiting, delays, User-Agent)
