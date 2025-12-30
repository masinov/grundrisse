## Marxists.org Crawler/Scraper Blueprint (for a parallel worker)

This document specifies an end-to-end crawler/scraper for `https://www.marxists.org/` that can be
developed in parallel to the NLP pipeline. It is designed to integrate seamlessly with the existing
repo components (`ingest_service`, Postgres substrate schema, and the Stage A/B NLP pipeline).

The core objective is to collect a *complete, auditable corpus* of marxists.org texts (across
languages/authors/works/editions), stored as immutable raw snapshots and ingested into the database
as a versioned text substrate suitable for downstream LLM extraction, canonicalization, alignment,
and dialectical graph building.

---

## 1) Context: the overall system you are plugging into

This repo already implements:

- **Raw snapshotting** to local filesystem under `data/raw/` (HTML bytes + checksum).
- **Ingestion** into Postgres as an immutable substrate:
  - `Work` → `Edition` → `TextBlock` → `Paragraph` → `SentenceSpan`
  - Every semantic artifact later must cite `SentenceSpan` evidence (non-negotiable).
- A working ingest CLI:
  - `grundrisse-ingest ingest <url>` (single page)
  - `grundrisse-ingest ingest-work <root_url>` (multi-page “directory work” using in-scope crawling)
- NLP pipeline:
  - Stage A: A1 mentions + A3 claims (evidence-backed)
  - Stage B: concept canonicalization / clustering (with drift handling)

Your crawler/scraper should focus on producing a *reliable URL catalog + snapshot set* and then
calling/feeding the existing ingest pipeline in a deterministic way.

---

## 2) Non-negotiable constraints (must match `main_plan.txt`)

1) **Immutable substrate**
   - Once an `Edition` is ingested, it must never be mutated in-place.
   - If the page changes or parsing improves, ingest into a *new* `Edition` (new `source_url`).

2) **Atomic evidence**
   - Downstream semantic artifacts cite `SentenceSpan`s.
   - Therefore, the crawler must preserve enough provenance to reproduce exactly which raw pages
     were used to create the `SentenceSpan`s.

3) **Provenance-first**
   - Every crawl/snapshot/ingest should be attributable to a run id, timestamp, and config.

4) **Determinism**
   - Given the same inputs (seed URLs + crawl rules), the crawler should produce the same ordered
     URL list (or at least stable canonicalization).

5) **Politeness**
   - This is a public site. Implement rate limiting, crawl delays, and caching (ETag/Last-Modified).
   - Respect robots.txt.

---

## 3) What we know about marxists.org structure (practical findings)

### 3.1 Landing page and languages

- `https://www.marxists.org/` is the landing page. The user selects language and navigates into
  language-specific areas.
- Language roots often live under stable path prefixes (not guaranteed uniform).

### 3.2 Works are frequently split across multiple HTML pages

Example (English Manifesto):
- `.../communist-manifesto/index.htm`
- `.../communist-manifesto/preface.htm`
- `.../communist-manifesto/ch01.htm`, `ch02.htm`, etc.
- Sometimes `guide.htm` or other auxiliary pages exist (study guides, TOCs, etc.).

### 3.3 A “work directory” heuristic works well as a first pass

Current `ingest-work` implementation treats a work as:
- “all `.htm/.html` pages within the same directory prefix as `root_url`”
- bounded by `--max-pages`
- recursively discovered via in-page links

This works for many marxists.org works, but it will not discover *the entire corpus*.

---

## 4) Deliverables (what you should produce)

### Deliverable A — URL Catalog (authoritative)

Build a persistent URL catalog that can be incrementally updated:

- Canonical URL normalization:
  - remove fragments (`#...`)
  - remove whitespace (users may paste wrapped URLs)
  - normalize scheme/host
  - preserve querystring **only when it intentionally creates a new Edition version**
- Dedup keys:
  - canonical URL string
  - content hash after snapshot

Minimum fields recommended:
- `url` (canonical)
- `discovered_from_url`
- `discovered_at`
- `crawl_run_id`
- `status` (new, fetched, error, skipped, out_of_scope)
- `http_status`
- `content_type`
- `etag`, `last_modified` (if present)
- `sha256`
- `raw_path` (local snapshot path)

Where to store it:
- Prefer Postgres tables (new module/migrations) OR a local sqlite/dbm file if you want to keep the
  crawler decoupled. If using files, ensure it’s stable and mergeable.

### Deliverable B — Crawl strategy that reaches the whole corpus

Implement multi-stage crawling:

1) Seed discovery:
   - start from `https://www.marxists.org/` and enumerate language root pages
2) Within a language:
   - discover author indexes, “archive” or “library” pages, and other index structures
3) Within an author:
   - discover work TOCs and work pages
4) Within a work:
   - discover the work directory pages (the existing heuristic)

The crawler should output a graph of discovered relations:
- language → author → work → page URL

### Deliverable C — Snapshots (immutable raw store)

Requirements:
- Store raw HTML bytes to `data/raw/` (or a configurable root).
- Always store:
  - exact bytes
  - checksum (sha256)
  - fetch metadata (URL, headers, status, fetched_at)
- Prefer “write-once” paths keyed by checksum and/or run id.

### Deliverable D — Ingest integration (must be seamless)

Integration contract with existing repo:

Option 1 (recommended): call the existing CLI:
- `grundrisse-ingest ingest-work <root_url>` for each work root, letting ingestion handle work-dir discovery.
- Pros: reuse existing ingest logic.
- Cons: crawler must decide “root_url per work”.

Option 2: feed a manifest + snapshots list and have ingestion consume it (requires small extension).
- This repo already writes an `ingest_run_<uuid>.json` manifest in `data/raw/` for `ingest-work`.
- If you choose this path, match that manifest format:
  - `root_url`, `base_prefix`, `urls`, `snapshots[]` with `url`, `sha256`, `raw_path`, `meta_path`, `content_type`.

Either way, ensure:
- You pass a stable `author` and `title` (canonical), and a stable `language`.
- For new editions/versions, change `source_url` (e.g. add `?run=5`) to create a new deterministic
  `edition_id` without mutating old substrate.

---

## 5) Architecture recommendations (robust, production-minded)

### 5.1 Separate the crawler from ingestion

Crawler responsibilities:
- discover URLs
- snapshot raw pages
- track catalog/provenance
- decide what constitutes a “work” (root URL, title, author)

Ingestion responsibilities (already in repo):
- parse HTML → blocks/paragraphs/sentences
- store substrate

Avoid mixing these layers. The seam between them should be a manifest / run record.

### 5.2 Idempotency + incremental refresh

Implement:
- “fetch if changed”: use ETag/Last-Modified and/or sha256 of content
- never delete snapshots automatically
- separate “catalog refresh” from “ingest refresh”

### 5.3 Deterministic ordering for multi-page works

When ingesting a work directory, produce a stable order:
- index first
- preface next
- chapters by numeric
- then lexical

The current repo has `_sort_urls()` in `services/ingest_service/src/ingest_service/crawl/discover.py`.
If you replicate, keep ordering consistent.

### 5.4 Rate limiting and stability

Minimum:
- a fixed crawl delay (e.g. 0.3–1.0s)
- bounded concurrency (start with 1–4)
- retry policy on transient failures
- `User-Agent` string identifying the crawler

### 5.5 Scope control and safety

Crawler must allow:
- limiting to a language subset
- limiting to an author subset
- limiting to N works/pages for testing

Do not attempt to fetch everything in early testing.

---

## 6) How to decide “what is a work”

You need a rule to map the website’s structure into:
- `Author` (canonical)
- `Work` (canonical title)
- `Edition` (language + source_url)

Recommended approach:
1) Treat a “work” as a directory prefix under marxists.org *when it looks like a work folder*.
2) Choose a canonical `root_url` for ingestion:
   - Prefer `index.htm` when present
   - Otherwise use the first discovered “main” page for that directory
3) Record the *full page set* for the edition:
   - the directory pages discovered within that root
4) If the same directory contains multiple distinct works (rare but possible), the crawler must split.

You will likely need special-casing rules for some areas of the site. That’s normal.

---

## 7) LLM-assisted crawling (optional)

If pure heuristics are insufficient (e.g., author/title detection, filtering apparatus pages):
- You may use a local/cheap LLM pass on *TOC/index pages only* to extract structured metadata:
  - author name
  - work title
  - language
  - list of page URLs for the work
  - distinguish “main text” vs “guide/license/navigation”

Constraints:
- Any LLM-derived metadata must be stored with provenance (prompt, model, output).
- Do not use LLMs to rewrite content; only to classify and extract metadata.

---

## 8) Seamless join constraints (for merging crawler with NLP work)

To ensure your crawler output works with the NLP pipeline without refactors:

1) Keep using the repo’s raw snapshot location convention:
   - raw snapshots under `data/raw/` (or a configurable root) with stable paths

2) Ensure ingestion receives:
   - stable `author` string and stable `title` string
   - stable `language`
   - a stable `root_url` per edition (do not embed whitespace/newlines)

3) Never mutate existing Editions:
   - if you want a “re-ingest” due to changes, choose a new `source_url` (e.g., `?run=6`)

4) Prefer producing a manifest compatible with the existing `ingest_run_<uuid>.json` shape
   - so the ingest system can consume or reproduce the same run deterministically.

5) Keep URL canonicalization consistent
   - remove `#fragment`
   - remove whitespace
   - avoid accidental duplication by differing encodings/casing

---

## 9) Suggested implementation plan (phased)

### Phase 1 — Minimal production-grade crawler loop
- Implement URL catalog + snapshotter with caching and retry.
- Implement per-language seed discovery.
- Implement author/work discovery for one language (English) as a pilot.
- Feed discovered works into `grundrisse-ingest ingest-work`.

Exit criteria:
- Given an author subset, you can ingest 10–20 works reliably and repeatably.

### Phase 2 — Full site traversal
- Expand discovery to all languages desired.
- Add special casing for known index structures that don’t follow the same patterns.
- Add “resume” support and long-run observability (progress logs, counters).

Exit criteria:
- URL catalog covers the intended corpus scope with low error rate.

### Phase 3 — Corpus maintenance
- Incremental refresh runs (weekly/monthly).
- Diffing and versioning policy for new editions.
- Report generation: new/changed pages, missing snapshots, parse failures.

---

## 10) Handoff checklist (how to validate your crawler)

1) Pick one pilot work (e.g., Manifesto) and ensure:
   - discovered page list is complete and stable
   - snapshot files exist and checksums match
   - ingest produces non-zero paragraphs/spans
2) Run Stage A and Stage B (already in this repo) and confirm:
   - evidence integrity gates pass
   - the sampler shows mostly content paragraphs, not license/nav
3) Scale to 10 works and measure:
   - fetch rate and politeness compliance
   - parse success rate
   - ingest success rate

