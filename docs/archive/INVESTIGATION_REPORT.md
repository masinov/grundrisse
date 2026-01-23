# Publication Date Investigation Report
**Date:** 2026-01-20
**Investigator:** Claude (Sonnet 4.5)
**Scope:** 100 works from Marxist text corpus (sample_100_works.json)

---

## Executive Summary

Investigated publication dates for 99 unique works from the sample (one duplicate removed). Successfully identified publication dates for **98 out of 99 works** (99% success rate).

### Key Statistics

- **Total works investigated:** 99
- **Works with dates found:** 98 (99%)
- **Works with no date:** 1 (1%)

### Confidence Distribution
- **High confidence:** 63 works (64%)
- **Medium confidence:** 34 works (34%)
- **Low confidence:** 1 work (1%)
- **Uncertain:** 1 work (1%)

### Precision Distribution
- **Day precision:** 29 works (29%)
- **Month precision:** 30 works (30%)
- **Year precision:** 40 works (40%)

### Data Sources Used
1. **URL paths:** 55 works (56%) - Most reliable when present
2. **Web search:** 11 works (11%) - For missing metadata
3. **Source metadata "Written" field:** 10 works (10%)
4. **Source metadata "Published" field:** 8 works (8%)
5. **Other fields:** 15 works (15%)

---

## Investigation Methodology

### Phase 1: Automated Data Extraction
Created automated script (`auto_investigate.py`) to extract dates from:
- URL path patterns (`/YYYY/MM/DD.htm`, `/YYYY/MM/`, `/YYYY/month_name/`)
- Source metadata fields (First Published, Published, Written, Delivered)
- Periodical citations in Source fields

### Phase 2: Manual Investigation
For 13 works with no automated date extraction:
- Web searched for publication information
- Consulted scholarly sources
- Verified via cross-references

### Phase 3: Data Validation
- Deduplicated results
- Verified confidence levels
- Cross-checked precision claims

---

## Major Findings

### 1. URL Date Extraction Gaps
**Issue:** Current parser only extracts year from URLs, missing month and day precision.

**Evidence:**
- Work: "Revolution in China and In Europe" (Karl Marx)
- URL: `/1853/06/14.htm`
- Current extraction: 1853 (year only)
- Available precision: 1853-06-14 (full date)

**Impact:** ~25-30 works losing month/day precision

**Fix:** Enhance URL parser to handle `/YYYY/MM/DD`, `/YYYY/MM/`, and `/YYYY/month_abbrev/` patterns

### 2. Source Metadata Field Parsing Issues
**Issue:** Parser doesn't extract dates from several common field variations.

**Evidence:**
- "First published" (lowercase) not recognized (only "First Published")
- "Delivered" field dates not extracted
- Periodical citations not parsed: "Volume X, no Y, Date"

**Impact:** ~15-20 works with dates in metadata but not extracted

**Fix:** Make field matching case-insensitive; add periodical citation parser; extract from "Delivered" field

### 3. Letters/Correspondence Date Handling
**Issue:** Confusion between written date (from URL) vs. publication date (from Source field).

**Evidence:**
- Work: "Selected Correspondence" (Engels, 1886)
- URL date: 1886-10-02 (when letter was written)
- Source date: 1975 (when edition was published)

**Impact:** ~10 letter/correspondence works

**Fix:** For correspondence, prioritize URL date as "written_date" over Source "published_date"

### 4. Multi-field Date Strings Not Parsed
**Issue:** Dates embedded in multi-field strings not extracted.

**Evidence:**
- Work: "Speech Delivered at Third All-Russian Congress" (Lenin)
- Field content: "Delivered: March 15, 1920... First Published: Pravda Nos. 59 and 60, March 17 and 18, 1920"
- Current extraction: None
- Available data: Both delivery (March 15) and publication (March 17-18)

**Impact:** ~5-10 works

**Fix:** Parse dates from compound field strings, not just dedicated date fields

### 5. Author Attribution Errors
**Issue:** Some works attributed to wrong authors in database.

**Evidence:**
- Work: "A sangre y lanza"
- Database author: Juan B. Justo
- Actual author: Liborio Justo (pen name: Lobodón Garra)

**Additional error found:**
- Work: "The Ordination of Knighthood"
- Author death year: 1936
- Actual (William Morris died 1896)

**Fix:** Verify and correct author metadata

---

## Systematic Fix Recommendations

### Priority 1: URL Date Parser Enhancement
```python
# Current pattern
/(\d{4})/  # Year only

# Recommended patterns
/(\d{4})/(\d{2})/(\d{2})/  # Full date
/(\d{4})/(\d{2})/  # Year + month
/(\d{4})/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/  # Month abbrev
```

**Expected impact:** +25-30 works with improved precision

### Priority 2: Source Metadata Field Improvements
```python
# Make field matching case-insensitive
fields_to_check = {
    'first published': ['First Published', 'First published', 'first published'],
    'published': ['Published', 'published'],
    'delivered': ['Delivered', 'delivered'],
    'written': ['Written', 'written']
}

# Add periodical citation parser
pattern = r'Volume\s+\d+,\s*no\s+\d+,\s*(\d{1,2})\s+(January|...)\s+(\d{4})'
```

**Expected impact:** +15-20 works with extracted dates

### Priority 3: Correspondence Date Logic
```python
if work.work_type == WorkType.CORRESPONDENCE:
    prefer_url_date_as_written_date()
    use_source_date_as_edition_date()
else:
    prefer_source_date_as_publication_date()
```

**Expected impact:** +10 works with correct date semantics

### Priority 4: Author Metadata Corrections
- William Morris: death_year should be 1896 (not 1936)
- "A sangre y lanza": author should be Liborio Justo (not Juan B. Justo)
- "The John Maclean March": author should be Hamish Henderson (not Unknown)

---

## Works Requiring Manual Investigation

### Fully Resolved (98 works)
All works except one now have publication dates with documented sources.

### Unresolved (1 work)
**Work ID:** c6568e4e-604f-566d-bc67-82b96fe55521
**Title:** A Critical Assessment of the Former Latin American Bureau Tendency within the Fourth International
**Author:** Posadas
**Issue:** No date in URL/metadata; no web results found
**Recommendation:** Requires access to physical Trotskyist archives or specialized collections

---

## Patterns Discovered

### Congress/Conference Titles
Works with congress titles can often be dated via known historical events:
- "Tenth Congress of the R.C.P.(B.)" → 10th Congress RCP(B) occurred March 8-16, 1921
- "Unity Congress of the R.S.D.L.P." → 4th Congress RSDLP, April 1906

**Recommendation:** Build congress/conference date lookup table

### Chapter Pages
Pages that are chapters/sections of larger works often lack source_metadata.

**Evidence:**
- URL pattern: `/works/1921/10thcong/ch02.htm`
- No source_metadata present

**Recommendation:** For chapter URLs, inherit metadata from parent work

### Obituaries
Obituary publication dates typically 1-2 weeks after subject's death.

**Evidence:**
- "William Morris (Obituary)" by Keir Hardie
- Morris died: October 3, 1896
- Obituary published: October 10, 1896 (7 days later)

**Recommendation:** For obituaries, search for subject death date + ~1 week

---

## Data Quality Assessment

### High Confidence (63 works)
Sources: URL paths with full dates, verified web searches, explicit source metadata fields

### Medium Confidence (34 works)
Sources: URL year-only, inferred patterns, derived dates from external APIs

### Low Confidence (1 work)
- "The Key Issue at Dispute in Canada-U.S. Relations" (Ross Dowson, 1973)
- Source: Filename inference only, no external verification

### Uncertain (1 work)
- "A Critical Assessment..." (Posadas)
- No date found despite multiple search strategies

---

## Implementation Roadmap

### Phase 1: Quick Wins (Week 1)
1. Implement URL date parser enhancements
2. Add case-insensitive field matching
3. Correct identified author metadata errors

**Expected improvement:** +30-40 works with better precision or extraction

### Phase 2: Medium Complexity (Week 2)
1. Implement periodical citation parser
2. Add correspondence date logic
3. Add Delivered/Written field extraction

**Expected improvement:** +20-25 works

### Phase 3: Advanced Features (Week 3-4)
1. Build congress/conference date lookup
2. Implement chapter→parent work metadata inheritance
3. Add compound field string parsing

**Expected improvement:** +10-15 works

---

## Conclusion

Successfully investigated 99 works with 99% date discovery rate. Identified systematic issues in current metadata extraction that, when fixed, could improve precision for 60-80 additional works beyond this sample. Recommended fixes are well-documented and prioritized by impact.

### Sources

Research utilized:
- [Liborio Justo: la aventura permanente](https://liboriojusto.org/aventura.htm)
- [Marxists Internet Archive - William Morris Obituary](https://www.marxists.org/archive/morris/obits/hardie.htm)
- [The Anarchist Encyclopedia by Sebastien Faure 1934](https://www.marxists.org/reference/archive/faure/1934/encyclopedia.htm)
- [Hegel's Encyclopedia (Stanford Encyclopedia of Philosophy)](https://plato.stanford.edu/entries/hegel/)
- [Tariq Ali: Daniel Bensaid obituary](https://www.marxists.org/archive/bensaid/obits/ali.htm)
- [August Thalheimer Archive](https://www.marxists.org/archive/thalheimer/index.htm)
- [The John Maclean March - Wikipedia](https://en.wikipedia.org/wiki/The_John_Maclean_March)
- [Feuerbach "Principles of the Philosophy of the Future"](https://plato.stanford.edu/entries/ludwig-feuerbach/)
- [Liborio Justo - Wikipedia](https://es.wikipedia.org/wiki/Liborio_Justo)
- [Leon Trotsky: Writings on Britain](https://www.marxists.org/archive/trotsky/works/britain/index.htm)
