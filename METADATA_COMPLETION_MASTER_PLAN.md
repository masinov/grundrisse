# Production-Ready Metadata Completion Master Plan

**Objective:** Complete publication date metadata for all 19,098 works in the corpus with provenance-backed, auditable correctness.

**Current State (Corpus Intelligence):**
- Total works: 19,098
- Works with dates: 15,621 (81.8%)
- Works without dates: 3,477 (18.2%)
- Editions with source_metadata: 17,782/19,111 (93.0%)
- Works without external evidence: 8,335 (43.6%)
- Author lifespan coverage: 52.4% birth, 46.0% death

**Success Criteria:**
1. ≥95% of works have verified publication dates with provenance
2. All dates have confidence scores ≥0.70 OR explicit "uncertain"标记
3. Author lifespan coverage ≥90% (for validation)
4. Full audit trail for every date decision
5. Zero "unknown" dates without explicit uncertainty note

---

## Phase 0: Infrastructure & Code Fixes (Week 1)

### 0.1 Code Corrections

**File:** `services/ingest_service/src/ingest_service/parse/marxists_header_metadata.py`

```python
# Add case-insensitive field matching
_HEADER_KEYS_LOWERCASE = {k.lower() for k in _HEADER_KEYS}

# Add "Date" field support
dates = {
    "written": parse_dateish(fields.get("Written")),
    "first_published": parse_dateish(fields.get("First Published")),
    "published": parse_dateish(fields.get("Published")),
    "date": parse_dateish(fields.get("Date")),  # NEW
    "delivered": parse_dateish(fields.get("Delivered")),  # NEW
    "title_date": title_date,
}
```

**File:** `services/ingest_service/src/ingest_service/metadata/publication_date_resolver.py`

```python
def extract_full_date_from_url(url: str) -> dict | None:
    """Extract date with full precision from URL."""
    # /YYYY/MM/DD.htm
    m = re.search(r'/(\d{4})/(\d{2})/(\d{2})(?:\.htm|\.html|/)', url)
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
        return {"year": int(m.group(1)), "month": int(m.group(2)), "day": int(m.group(3)), "precision": "day"}

    # /YYYY/MM/
    m = re.search(r'/(\d{4})/(\d{2})(?:\.htm|\.html|/)', url)
    if m and 1 <= int(m.group(2)) <= 12:
        return {"year": int(m.group(1)), "month": int(m.group(2)), "precision": "month"}

    # /YYYY/
    m = re.search(r'/(\d{4})(?:\.htm|\.html|/)', url)
    if m:
        return {"year": int(m.group(1)), "precision": "year"}

    return None
```

**File:** `services/ingest_service/src/ingest_service/metadata/work_date_deriver.py`

```python
# Add URL date as highest-priority candidate
def build_candidates_from_edition_source_metadata_with_url(
    edition_id: str, source_url: str, source_metadata: dict | None
) -> list[DateCandidate]:
    candidates = []

    # URL date is highest priority (directly reflects marxists.org curation)
    url_date = extract_full_date_from_url(source_url)
    if url_date:
        candidates.append(DateCandidate(
            role="first_publication_date",
            date=url_date,
            confidence=0.98,  # Very high - marxists.org curates URLs
            source_name="marxists_url_path",
            source_locator=source_url,
            provenance={"url": source_url}
        ))

    # Then add source_metadata candidates...
    candidates.extend(build_candidates_from_edition_source_metadata(...))
    return candidates
```

### 0.2 Database Schema Additions

Run migration to add uncertainty tracking:

```sql
ALTER TABLE work_date_derived ADD COLUMN uncertainty_reason TEXT;
ALTER TABLE work_date_derived ADD COLUMN qa_status VARCHAR(32) DEFAULT 'pending';
```

### 0.3 Quality Assurance Framework

Create validation suite:

```python
# scripts/validate_corpus_dates.py
def validate_work_date(work_id: str) -> dict:
    """Validate a work's date against all constraints."""
    issues = []

    # 1. Check against author lifespan
    if date_year > author_death_year + 10:
        issues.append("after_death_warning")
    if date_year < author_birth_year - 10:
        issues.append("before_birth_warning")

    # 2. Check confidence threshold
    if confidence < 0.70 and uncertainty_reason is None:
        issues.append("low_confidence_without_note")

    # 3. Check provenance exists
    if not evidence_rows:
        issues.append("no_provenance")

    # 4. Check precision consistency
    if precision == "day" and (day is None or month is None):
        issues.append("precision_mismatch")

    return {"valid": len(issues) == 0, "issues": issues}
```

---

## Phase 1: High-Confidence Date Recovery (Week 1-2)

**Target:** Recover ~2,500-3,000 works with URL dates

### 1.1 URL Date Extraction & Ingestion

**Script:** `scripts/phase1_url_date_recovery.py`

```python
def recover_url_dates(limit: int = None):
    """
    Extract dates from all marxists.org URLs and ingest as WorkMetadataEvidence.
    This creates auditable provenance for URL-derived dates.
    """
    # Find all works with unknown dates that have URL patterns
    works = session.execute(
        select(Work, Edition)
        .join(Edition)
        .join(WorkDateDerived)
        .where(WorkDateDerived.display_date_field == "unknown")
        .where(TextBlock.source_url.op("~*")(r"/\d{4}/"))
    ).all()

    for work, edition in works:
        url_date = extract_full_date_from_url(edition.source_url)
        if url_date:
            # Write evidence row
            evidence = WorkMetadataEvidence(
                evidence_id=uuid.uuid4(),
                run_id=RUN_ID,
                work_id=work.work_id,
                source_name="marxists_url_path",
                source_locator=edition.source_url,
                extracted=url_date,
                score=0.98,  # High confidence for curated URLs
                raw_payload={"url": edition.source_url, "extraction_method": "url_regex"}
            )
            session.add(evidence)

    session.commit()
```

**Command:**
```bash
python scripts/phase1_url_date_recovery.py
```

**Expected Impact:** +2,500-3,000 works with dates

### 1.2 Source Metadata Re-Parsing

After fixing field parsing, re-parse all source_metadata:

```python
def reparse_all_source_metadata():
    """Re-parse all edition.source_metadata with improved parser."""
    editions = session.execute(select(Edition).where(Edition.source_metadata.isnot(None))).all()

    for edition in editions:
        # Re-extract with improved parser
        new_metadata = extract_marxists_header_metadata(edition.raw_html)
        if new_metadata:
            edition.source_metadata = new_metadata

    session.commit()
```

---

## Phase 2: Author Lifespan Resolution (Week 2)

**Target:** 90%+ author coverage

### 2.1 Bulk Author Lifespan Fetch

**Script:** `scripts/phase2_author_lifespans.py`

```python
def resolve_all_author_lifespans():
    """Query Wikidata for all missing author birth/death years."""
    authors_without = session.execute(
        select(Author).where(
            (Author.birth_year.is_(None)) | (Author.death_year.is_(None))
        )
    ).all()

    for author in authors_without:
        # Query Wikidata via SPARQL
        birth_year, death_year = query_wikidata_author_dates(author.name_canonical)

        if birth_year or death_year:
            author.birth_year = birth_year
            author.death_year = death_year

    session.commit()
```

**Command:**
```bash
python scripts/phase2_author_lifespans.py --limit 1500
```

---

## Phase 3: Intelligent External Enrichment (Week 3-4)

**Target:** Resolve remaining ~1,000 unknown works via external sources

### 3.1 Tiered External Queries

For works still unknown, use GLM-4.7 to intelligently query:

**Script:** `scripts/phase3_llm_enrichment.py`

```python
async def enrich_work_with_llm(work_id: str, llm_client):
    """Use GLM-4.7 to research and verify publication dates."""
    work = session.get(Work, work_id)
    author = session.get(Author, work.author_id)

    # Build research prompt
    prompt = f"""Research the first publication date of this Marxist theoretical work.

Title: {work.title}
Author: {author.name_canonical} ({author.birth_year}-{author.death_year})
Language: {work.original_language or 'unknown'}

Steps:
1. Check if the work appears in marxists.org archives (search by title)
2. Check Wikidata for the work entity
3. Check academic bibliographies
4. Verify any found date against author lifespan

Return JSON:
{{
    "date": {{"year": 1848, "month": 2, "day": 21, "precision": "day"}},
    "confidence": 0.95,
    "sources": ["URL1", "URL2"],
    "reasoning": "Explanation of how date was determined",
    "uncertainty": null  // or explanation if uncertain
}}
"""

    result = await llm_client.generate(prompt)

    # Validate result
    if result["confidence"] >= 0.70:
        # Write evidence
        evidence = WorkMetadataEvidence(
            evidence_id=uuid.uuid4(),
            work_id=work_id,
            source_name="glm4.7_research",
            source_locator=result["sources"][0] if result["sources"] else None,
            extracted=result["date"],
            score=result["confidence"],
            raw_payload={"reasoning": result["reasoning"], "sources": result["sources"]},
            notes=result.get("uncertainty")
        )
        session.add(evidence)

    return result
```

**Execution:**
```bash
# Process in batches of 100
python scripts/phase3_llm_enrichment.py --batch-size 100 --concurrent 10
```

### 3.2 Specialized Handlers

**For Speeches/Congresses:**
```python
CONGRESS_DATES = {
    "Tenth Congress of the R.C.P.(B.)": {"year": 1921, "month": 3, "day_range": "8-16"},
    "Fourth Congress of the Comintern": {"year": 1922, "month": 11, "day_range": "5-Dec 5"},
    # ... build comprehensive lookup table
}

def lookup_congress_date(title: str) -> dict | None:
    for congress_name, date_info in CONGRESS_DATES.items():
        if congress_name.lower() in title.lower():
            return date_info
    return None
```

**For Letters/Correspondence:**
```python
def handle_correspondence(work: Work, edition: Edition) -> dict | None:
    """Letters: prefer URL date (written) over Source date (publication)."""
    if work.work_type == WorkType.correspondence:
        url_date = extract_full_date_from_url(edition.source_url)
        if url_date:
            return {
                "written_date": url_date,
                "confidence": 0.95,
                "note": "Correspondence: URL date reflects written date"
            }
    return None
```

**For Obituaries:**
```python
def handle_obituary(work: Work) -> dict | None:
    """Obituaries: search for subject's death date."""
    if "obituary" in work.title.lower():
        # Extract subject name from title
        subject = extract_obituary_subject(work.title)
        # Get their death date from author table or Wikidata
        death_date = get_author_death_date(subject)
        if death_date:
            # Obituaries typically published 1-2 weeks after death
            return {
                "approximate_date": {"year": death_date["year"], "month": death_date["month"]},
                "confidence": 0.80,
                "note": "Obituary: published shortly after death"
            }
    return None
```

---

## Phase 4: Final Derivation & QA (Week 5)

### 4.1 Complete Re-Derivation

```bash
grundrisse-ingest derive-work-dates --force --limit 20000
```

### 4.2 Comprehensive Validation

**Script:** `scripts/phase4_validate_corpus.py`

```python
def validate_entire_corpus():
    """Run comprehensive validation on all works."""
    issues_by_severity = {"critical": [], "warning": [], "info": []}

    works = session.execute(select(Work)).all()

    for work in works:
        derived = session.get(WorkDateDerived, work.work_id)
        validation = validate_work_date(work.work_id)

        if not validation["valid"]:
            for issue in validation["issues"]:
                if issue in ["after_death_error", "before_birth_error", "no_provenance"]:
                    issues_by_severity["critical"].append((work.work_id, issue))
                elif issue in ["after_death_warning", "low_confidence"]:
                    issues_by_severity["warning"].append((work.work_id, issue))
                else:
                    issues_by_severity["info"].append((work.work_id, issue))

    return issues_by_severity
```

**Success Threshold:**
- Critical issues: <50 works (0.3%)
- Warning issues: <500 works (2.6%)

### 4.3 Manual Review Queue

For remaining problematic works, create manual review interface:

```python
def generate_manual_review_queue():
    """Generate prioritized queue for manual review."""
    # Priority 1: High-profile authors with unknown dates
    priority_authors = ["Marx", "Lenin", "Trotsky", "Stalin", "Mao"]

    # Priority 2: Works with conflicting evidence
    # Priority 3: Works with very low confidence
    # Priority 4: Classical/ancient texts with uncertain dates
```

---

## Phase 5: Uncertainty Annotation (Week 5-6)

For works that truly cannot be dated, add explicit uncertainty notes:

```python
def annotate_uncertain_works():
    """Add uncertainty_reason to truly undatable works."""
    uncertain_reasons = {
        "classical_text": "Classical text with uncertain first publication date",
        "fragment": "Fragment without publication context",
        "translation_only": "Only translation date known, original date uncertain",
        "collection": "Part of collected works, original publication unknown",
        "lost": "Original publication details lost",
    }

    for work in truly_undatable_works:
        derived = session.get(WorkDateDerived, work.work_id)
        derived.uncertainty_reason = determine_uncertainty_type(work)
        derived.qa_status = "accepted_as_uncertain"
```

---

## Execution Timeline

| Phase | Duration | Works Recovered | Cumulative Coverage |
|-------|----------|-----------------|---------------------|
| 0: Setup | Week 1 | 0 | 81.8% |
| 1: URL Recovery | Week 1-2 | +2,800 | 96.5% |
| 2: Author Lifespans | Week 2 | 0 (validation) | 96.5% |
| 3: External Enrichment | Week 3-4 | +600 | 99.7% |
| 4: Derivation & QA | Week 5 | -100 (errors) | 99.1% |
| 5: Uncertainty | Week 5-6 | +150 notes | 99.1% (all annotated) |

**Final State Expected:**
- Works with verified dates: ~18,900 (99%)
- Works with uncertain dates: ~150 (1%) with explicit notes
- Author lifespan coverage: >90%
- Zero "unknown" without explanation

---

## File Structure Created

```
scripts/
├── phase0_code_fixes.py          # Apply all code corrections
├── phase1_url_date_recovery.py    # Extract URL dates at scale
├── phase2_author_lifespans.py     # Resolve all author dates
├── phase3_llm_enrichment.py       # GLM-4.7 assisted research
├── phase3_specialized_handlers.py # Congress/letters/obituary
├── phase4_validate_corpus.py      # Comprehensive validation
├── phase5_annotate_uncertain.py   # Uncertainty annotation
└── master_executor.py             # Orchestrate entire pipeline
```

---

## Immediate Actions

1. **Apply code fixes** (Phase 0)
2. **Create run scripts** for each phase
3. **Set up GLM-4.7 API access** for Phase 3
4. **Create validation suite** (Phase 4)
5. **Execute pipeline sequentially**

---

## Appendix: GLM-4.7 Integration

```python
# scripts/llm_research_agent.py
import asyncio
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key=os.environ["GRUNDRISSE_ZAI_API_KEY"],
    base_url="https://api.z.ai/v4"
)

async def research_work_publication(work: Work) -> dict:
    """Use GLM-4.7 to research publication date."""
    prompt = f"""You are a research assistant specializing in Marxist literature.

Task: Find the first publication date of: "{work.title}" by {work.author.name_canonical}

Search strategy:
1. Identify if this is a standalone work, speech, letter, article, or chapter
2. Search marxists.org for the work
3. Search academic sources
4. Cross-reference with author's biography

Respond ONLY with valid JSON:
{{
    "year": 1848,
    "month": 1,
    "day": null,
    "precision": "month",
    "confidence": 0.9,
    "sources": ["https://..."],
    "reasoning": "Found in...",
    "uncertainty": null
}}

If you cannot find a reliable date, set uncertainty to explain why.
"""

    response = await client.chat.completions.create(
        model="glm-4.7",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,  # Low temperature for factual extraction
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)
```

---

## Success Metrics Dashboard

```python
# Track throughout execution
METRICS = {
    "total_works": 19098,
    "works_with_dates": {"start": 15621, "target": 18900},
    "unknown_works": {"start": 3477, "target": 150},
    "avg_confidence": {"start": 0.65, "target": 0.85},
    "author_coverage": {"start": 0.52, "target": 0.90},
    "critical_issues": {"start": "unknown", "target": "<50"}
}
```

---

This plan prioritizes **correctness** through:
1. Provenance tracking for every date
2. Confidence thresholds
3. Author lifespan validation
4. Explicit uncertainty annotation
5. Comprehensive QA validation
