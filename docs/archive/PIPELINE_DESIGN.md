# Publication Date Enrichment Pipeline Design

## Overview
Multi-stage pipeline to systematically enrich publication dates for ~3,500 works with missing/low-confidence dates.

## Architecture

### Stage 1: Parser Fixes (One-time Code Changes)
**Goal:** Fix bugs in existing parsers to capture more dates from source_metadata

#### Fix 1.1: Case-Insensitive Field Matching
**File:** `services/ingest_service/src/ingest_service/parse/marxists_header_metadata.py`
**Change:** Make `_HEADER_KEYS` matching case-insensitive
```python
# Current: Exact match on "First Published"
# New: Match "First Published", "First published", "first published"
```
**Impact:** Captures dates from ~10-15% of works with lowercase field names

#### Fix 1.2: Periodical Citation Parsing
**File:** `services/ingest_service/src/ingest_service/parse/marxists_header_metadata.py`
**Function:** `parse_dateish()` or new `parse_periodical_citation()`
**Pattern:** `"Volume X, no Y, Date"` → extract Date
```python
# Regex: r'Volume\s+\d+,\s*no\.\s*\d+,\s*(.+?)(?:\.|$)'
# Then pass extracted date to parse_dateish()
```
**Impact:** Captures dates from ~20-30% of works with periodical Source fields

#### Fix 1.3: work.publication_date as Fallback Evidence
**File:** `services/ingest_service/src/ingest_service/metadata/work_date_deriver.py`
**Function:** `build_candidates_from_*()` - add new function
```python
def build_candidates_from_work_publication_date(
    work_id: str,
    publication_date: dict | None
) -> list[DateCandidate]:
    """Use work.publication_date as low-confidence fallback evidence"""
    if not publication_date or not publication_date.get('year'):
        return []

    return [DateCandidate(
        role="first_publication_date",  # or heuristic_publication_year
        date={"year": publication_date['year'], ...},
        confidence=0.40,  # low but better than nothing
        source_name="work_publication_date_fallback",
        source_locator=None,
        provenance={"method": publication_date.get('method', 'unknown')},
        notes="Fallback from work.publication_date (URL heuristic or legacy)"
    )]
```
**Impact:** Rescues ~50% of "unknown" works that have work.publication_date but no derived date

### Stage 2: Re-extract Source Metadata (No-Network)
**Goal:** Re-run extraction on editions to capture dates with fixed parsers

#### Command:
```bash
grundrisse-ingest extract-marxists-source-metadata \
  --force \
  --limit 20000 \
  --progress-every 500
```

**Expected Impact:** ~500-1000 additional dates captured from previously unparsed fields

### Stage 3: Text-Based Date Extraction (GLM-4.7)
**Goal:** Extract dates from paragraph text when headers are missing

#### Use Cases:
- Chapter pages (no source_metadata)
- Works with publication info in body text
- Congress/conference proceedings (dates in titles/text)

#### Method:
Delegate to GLM-4.7 for bulk extraction:
```python
def extract_date_from_text_llm(
    work_id: str,
    title: str,
    author: str,
    paragraphs: list[str],  # first 3-5 paragraphs
    url: str
) -> dict | None:
    """
    Use GLM-4.7 to extract publication date from text.

    Prompt:
    - Provide title, author, URL, first paragraphs
    - Ask for publication date extraction
    - Require JSON output with date + confidence + evidence snippet
    """
    prompt = f'''Extract the publication date from this Marxist text.

Title: {title}
Author: {author}
URL: {url}

First paragraphs:
{format_paragraphs(paragraphs)}

Task: Find the ORIGINAL publication date (not collection/reprint dates).
Look for: newspaper names + issue numbers + dates, congress dates, "Published in...", etc.

Output JSON:
{{
  "date": "YYYY-MM-DD or YYYY-MM or YYYY or null",
  "confidence": "high/medium/low",
  "evidence": "exact text snippet that contains the date"
}}
'''
    # Call GLM-4.7, parse response, validate
```

**Target:** ~1,000 works with chapter URLs or body-text-only dates

### Stage 4: External Source Enrichment (Network, Batch)
**Goal:** Query Wikidata/OpenLibrary for works still missing dates

#### Targets:
- Works with no internal evidence at all
- Works with low-confidence dates needing validation

#### Method:
Improved `resolve-publication-dates` or new targeted script
```bash
grundrisse-ingest resolve-publication-dates \
  --only-unknown \
  --sources "wikidata,openlibrary" \
  --limit 3000 \
  --min-score 0.70 \
  --crawl-delay-s 0.8 \
  --progress-every 50
```

**Expected Impact:** ~15-20% success rate (300-600 dates from ~3,000 attempts)

### Stage 5: URL Path Inheritance for Chapter Pages
**Goal:** Chapter/section pages inherit date from parent work

#### Logic:
```python
def inherit_date_from_parent_work(edition_id: str) -> DateCandidate | None:
    """
    For chapter URLs like /works/1921/10thcong/ch02.htm:
    1. Extract parent path: /works/1921/10thcong/
    2. Find edition with that parent path
    3. Get its derived date
    4. Return as inherited evidence
    """
```

**Target:** ~700 chapter pages (52% of 1,329 editions without source_metadata)

### Stage 6: Re-derive Work Dates
**Goal:** Incorporate all new evidence into work_date_derived

#### Command:
```bash
grundrisse-ingest derive-work-dates \
  --force \
  --limit 20000 \
  --progress-every 1000
```

**Expected Results:**
- "Unknown" works: 3,477 → ~1,500 (56% reduction)
- Low confidence works: 9,276 → ~6,000 (35% improvement)
- Overall coverage: 81.8% → ~92% with dates

### Stage 7: Validation & Manual Review
**Goal:** Spot-check improvements and identify remaining gaps

#### Metrics:
- Date coverage by confidence tier
- Dates per author (ensure Stalin/Lenin/etc have good coverage)
- Sample 50 newly-enriched dates for manual validation
- Flag suspicious patterns (after-death dates, etc.)

## Execution Timeline

### Phase 1: Code Fixes + Re-extraction (2-3 hours)
1. Implement parser fixes
2. Re-extract source metadata (20K editions)
3. Initial derive-work-dates run

### Phase 2: LLM-Based Extraction (4-6 hours)
4. Delegate text extraction to GLM-4.7 (1,000 works)
5. Write evidence rows
6. Re-derive dates

### Phase 3: External Enrichment (8-12 hours)
7. Run Wikidata/OpenLibrary queries (3,000 works)
8. Final derive-work-dates run

### Phase 4: Validation (2-3 hours)
9. Generate metrics
10. Manual spot-checking
11. Final report

**Total:** ~16-24 hours (can run overnight/unattended)

## Delegation Strategy

### Codex Tasks:
1. Implement parser fixes (Fixes 1.1, 1.2, 1.3)
2. Write URL inheritance logic (Stage 5)
3. Execute re-extraction and derivation commands (Stages 2, 6)
4. Generate validation metrics (Stage 7)

### GLM-4.7 Tasks:
1. Bulk text-based date extraction (Stage 3)
2. Confidence scoring for ambiguous dates

### Manual Tasks (Me):
1. Review Codex code changes
2. Spot-check LLM extractions
3. Final validation and reporting

## Success Criteria

**Minimum Acceptable:**
- Unknown works: < 10% (< 1,900 works)
- Low confidence: < 30% (< 5,700 works)
- Overall dated: > 90%

**Target Goal:**
- Unknown works: < 5% (< 950 works)
- Low confidence: < 20% (< 3,800 works)
- Overall dated: > 95%

---

## Next Actions
1. Wait for Codex to complete 100-work investigation
2. Analyze findings to validate/refine pipeline design
3. Delegate Phase 1 (Code Fixes) to Codex
4. Execute pipeline stages sequentially
5. Validate and report

