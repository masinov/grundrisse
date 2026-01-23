# Publication Date Enrichment - Manual Investigation & Pipeline Development

## Objective
Manually investigate 100 representative works with missing/faulty publication dates, determine correct dates through research, and use this experience to build a robust automated enrichment pipeline.

## Sampling Strategy

### Target: 100 works stratified by:
1. **By confidence level:**
   - 30 with `display_date_field='unknown'` (no date at all)
   - 30 with low confidence (0.00-0.49)
   - 20 with medium confidence (0.50-0.69) that might be wrong
   - 20 with after-death warnings

2. **By author distribution:**
   - Not clustering on single authors
   - Include major authors (Marx, Lenin, Stalin, Trotsky) but spread across many
   - Include lesser-known authors

3. **By work type:**
   - Speeches
   - Articles
   - Letters
   - Books
   - Pamphlets

## Investigation Process
For each work:
1. Record work_id, title, author, current date status
2. Inspect edition.source_metadata (marxists.org headers)
3. Read actual text snippets from paragraphs for date clues
4. Web search for authoritative publication date
5. Document findings and confidence
6. Record retrieval method that worked

## Progress Tracking
- [ ] Generate stratified sample (100 works)
- [ ] Manual investigation (0/100)
- [ ] Pattern analysis
- [ ] Pipeline design
- [ ] Codex/GLM delegation
- [ ] Bulk execution
- [ ] Validation

---

## Manual Investigation Log

Starting: 2026-01-20 22:30


## Patterns Discovered (Works 1-5)

### Pattern 1: Parser Field Name Case Sensitivity
**Issue:** Parser only extracts "First Published" (capital P) but not "First published" (lowercase p)
**Example:** Work 425158e0 (Shibdas Ghosh) has "First published: Ganadabi, September 15, 1948" - not extracted
**Fix:** Make field matching case-insensitive

### Pattern 2: Periodical Citations Not Parsed
**Issue:** Source field containing periodical citations like "Volume X, no Y, Date" not parsed for dates
**Example:** Work 67a0735a (Dutt) - "International Press Correspondence, Volume 20, no 31, 3 August 1940"
**Fix:** Add regex pattern to extract dates from periodical citations

### Pattern 3: work.publication_date Not Used in Derivation
**Issue:** URL heuristic captures year into work.publication_date, but derivation produces "unknown"
**Example:** Works 0a9a27b0, 67a0735a both have work.publication_date.year but derived date is "unknown"
**Fix:** Derivation should use work.publication_date as fallback evidence source

### Pattern 4: Letter/Correspondence Date Ambiguity
**Issue:** Letters have two dates - written date (from URL) vs collection publication date (from Source)
**Example:** Work 6a423962 (Engels) - written 1886-10-02, but Source says "Selected Correspondence (1975)"
**Fix:** For letters/correspondence, prefer URL path date (written) over Source date (collection)

### Pattern 5: Chapter Pages Missing Metadata
**Issue:** Chapter/section pages in multi-page works lack source_metadata (52% missing rate per earlier analysis)
**Example:** Work 711be8d1 (Lenin) - chapter URL, no source_metadata
**Fix:** Inherit metadata from parent work or root page

### Pattern 6: Congress/Conference Titles
**Issue:** Congress/conference works can be dated by event date lookup
**Example:** "Tenth Congress of the R.C.P.(B.)" - March 8-16, 1921
**Fix:** Maintain lookup table for major congresses/conferences

## Retrieval Method Success Rates (First 5 Works)

1. **source_metadata.fields parsing**: 2/5 (40%) - but would be higher with fixes
2. **URL path extraction**: 5/5 (100%) - all had years in URL
3. **Text inspection**: 2/5 (40%) - found publication info in paragraphs
4. **WebSearch**: 0/5 (0%) - not needed yet, internal sources sufficient

## Next Steps

1. Wait for Codex to complete remaining 95 investigations
2. Analyze all 100 findings for pattern validation
3. Design automated enrichment pipeline incorporating all patterns
4. Delegate pipeline execution to Codex/GLM
5. Re-run derive-work-dates with improved evidence
6. Validate results

---

## Background Task Status

- **Codex Investigation Agent**: Running (investigating works 6-100)
- **Started**: 2026-01-20 22:45
- **Expected Duration**: ~30-60 minutes
- **Output**: investigation_results.jsonl

