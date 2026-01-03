# Master Development Plan (Dialectical Knowledge Graph)

This file is the durable project roadmap for building a provenance-first, dialectics-aware knowledge
database over marxists.org texts. It is aligned with `main_plan.txt` and incorporates the operational
corrections in `revision.txt`.

## 0) Current State

- Ingestion supports multi-page works into a single `Edition` (`TextBlock/Paragraph/SentenceSpan`).
- Stage A extracts:
  - A1 Concept mentions (`ConceptMention` anchored to `SentenceSpan`)
  - A3 Claims (`Claim` + `SpanGroup` evidence + `ClaimEvidence`)
- Provenance is recorded via `ExtractionRun`.
- Evidence integrity constraint is enforced (claims cite paragraph-local sentence spans).
- Enum drift is stored as raw proposals (`*_raw`) and canonical fields may be NULL (no forced coercion).
- Idempotent skipping allows safe resume (skip paragraphs already processed by current prompt versions).

## 0.1) Gaps To Close (Robustness At Corpus Scale)

This project is deliberately staged: Stage A produces a high-integrity local semantic substrate, and
later passes build discourse-scale structure without breaking auditability. The following items are
the highest-leverage missing pieces to make the system robust, resumable, and scalable to the full
marxists.org corpus while staying consistent with `main_plan.txt` constraints.

1. **URL catalog + crawl provenance (crawler/catalog)**
   - Persist a URL catalog (language root → author pages → work TOCs → page URLs), with discovery
     provenance and crawl/run metadata.
   - Track status, content hashes, ETag/Last-Modified (when available) to support incremental refresh.

2. **True idempotent ingestion (prevent duplication on re-ingest)**
   - Re-ingesting the same work/edition must not duplicate `TextBlock/Paragraph/SentenceSpan`.
   - Use deterministic IDs and/or DB-level dedupe keys (stable hashes + order/path keys) with unique
     constraints, so ingestion is safe to retry.

3. **Run registry + prompt/version governance (end-to-end reproducibility)**
   - Central registry of prompt templates + schema hashes per version.
   - Clear operational story for bumping prompt versions and re-running without destroying prior data:
     new `ExtractionRun`s over the same immutable substrate (or new `Edition` only when the substrate changes).

4. **Job orchestration + “exactly-once” semantics**
   - A minimal job queue/locking model (even if local-first) so long runs can be distributed, resumed,
     and audited: track unit-of-work, attempts, leases, and final status per stage.

5. **LLM-call governance (stability under long runs)**
   - Rate limits, bounded concurrency, retries with jitter/backoff, circuit breaking.
   - Transport fallback (e.g., auto-disable HTTP/2 after repeated `RemoteProtocolError`).
   - Store enough raw response metadata for audit/debug (safely and without leaking secrets).

6. **Drift + quality dashboards + gold-set gating**
   - Track “raw vs canonical NULL rates” and value distributions per prompt version.
   - Maintain small gold sets for key works and run regressions whenever prompts/schemas change.

7. **Discourse/argument-structure pass (cross-paragraph scope)**
   - Add an explicit pass (recommended “A6”) that operates over section/chapter windows to create
     evidence-backed links *between* Stage-A claims across paragraphs:
     - `supports`, `depends_on`, `restates`, `objection`, `reply`, `therefore/inferred_from`, etc.
   - Crucially: outputs must still cite `SentenceSpan` evidence (often from multiple paragraphs), so
     we do not “solve scope” by unauditable summarization.

See `docs/VALIDATION.md` for the current validation workflow (DB integrity gates + coverage metrics +
targeted spot-check sampling).

## 1) Immediate Next Step — Stage B (Concept Canonicalization)

### 1.1 Goal

Turn mention-level extractions into stable, queryable concept identities with conservative sense
separation suitable for long-term concept evolution analysis.

### 1.2 Stage B outputs (DB)

- `Concept` rows with gloss, aliases, vernacular term (when available), temporal scope notes.
- `ConceptMention.concept_id` assigned for each mention.
- `ConceptEvidence` populated from definitional/central evidence spans (`SpanGroup`).
- Use `root_concept_id` later to group historical senses without premature merging.

### 1.3 Command (once implemented)

Stage B currently accepts a `work_id`:

```bash
grundrisse-nlp stage-b <work_uuid>
```

For the Manifesto, you can obtain `work_id` from the DB or ingestion output. Example previously observed:

```bash
grundrisse-nlp stage-b e079fbd2-584c-5f37-bc27-246d241c62b0
```

Note: if `grundrisse-nlp stage-b ...` raises `NotImplementedError`, the CLI stub exists but the
concept clustering/canonicalization logic still needs to be implemented.

Recommendation: add `--edition-id <uuid>` support so Stage B can be run on the latest re-ingestion
without needing to separate work-wide vs edition-scoped runs.

## 2) Full Roadmap to the “Dialectical Machine”

### Phase A — Substrate & provenance hardening

1. **Crawler/catalog**
   - Crawl `marxists.org` via language roots → author pages → work TOCs → page URLs
   - Persist a URL catalog (dedupe, crawl provenance)
2. **Idempotent ingestion**
   - Prevent duplicate paragraphs/spans on re-ingest
   - Prefer deterministic IDs or dedupe by stable hashes + order keys
3. **Structure parsing quality**
   - Improve block hierarchy (`parent_block_id`, `path`)
   - Detect apparatus blocks (`preface/afterword/footnote/editor_note`) and authorship overrides
4. **Language-aware sentence splitting**
   - Replace regex splitter with robust per-language segmentation

**Exit criteria**
- Re-ingest does not duplicate substrate; block/paragraph/span navigation is stable.

### Phase B — Stage A extraction governance and quality

5. **Prompt registry + versioning**
   - Store prompts/templates and schema hashes per version
6. **Robust extraction runner**
   - Backoff/retry, rate limiting, resumability, idempotent skipping
7. **Dedicated extraction passes**
   - A1 mentions (existing)
   - A3 claims (existing)
   - A4 explicit citations (recommended separate pass)
   - A5 dialectical relations (recommended separate pass producing evidence-backed edges)
   - A6 discourse/argument links across paragraphs/sections (recommended separate pass)

**Exit criteria**
- Evidence fidelity and drift metrics stable on pilot gold sets.

### Phase C — Stage B concepts (make concepts real and evolvable)

8. Mention clustering within-work first (string guards + optional embeddings).
9. Ontologist canonicalization with conservative sense splitting.
10. Sense/genealogy scaffolding (`root_concept_id` strategy; no premature merging).

**Exit criteria**
- Stable concept inventory with low merge errors for pilot works.

### Phase D — Claim canonicalization (make claims graphable)

11. Claim clustering/dedup within work → author → cross-author (gated).
12. Canonical claim nodes with merged evidence groups and preserved variants.

**Exit criteria**
- Reduced duplicates; stable claim nodes suitable for linking.

### Phase E — Claim ↔ Concept mapping

13. Populate `ClaimConceptLink` from about_terms + mention overlap + alias matching + disambiguation.

**Exit criteria**
- Query “claims about concept X” reliably.

### Phase F — Alignment across editions/translations

14. Hierarchical alignment: block → paragraph → sentence-group (`SpanAlignment`).
15. Cross-lingual concept genealogy (vernacular terms + translation drift).

**Exit criteria**
- Traverse from one edition’s evidence spans to aligned spans in another.

### Phase G — Cross-text theory graph (dialectical mapping)

16. Citation graph (`CitationEdge`) as high-value explicit edges.
17. Dialectical relation graph (negation, contradiction, sublation candidates, appearance/essence).
18. Evolution edges (concept sense shifts, claim refinements, applications, critiques).
19. Graph-aware retrieval + RAG (evidence-first + neighborhood expansion).

**Exit criteria**
- Evidence-backed cross-author links and dialectical relations usable for queries and chatbots.

### Phase H — Evaluation + human review loop

20. Gold sets + dashboards (evidence fidelity, merge precision, link precision).
21. Review workflow (proposed → canonical → validated), provenance for human actions.

**Exit criteria**
- “Tight” philosophical map with known confidence and auditable provenance.

## 3) Operating Principles (Non-negotiables)

- Immutable text substrate; corrections create new versions.
- Atomic evidence = `SentenceSpan`; everything semantic must cite evidence spans.
- Paragraph-in, sentence-IDs-out (LLM sees paragraph context but must reference sentence indices/IDs).
- Provenance for everything via `ExtractionRun`.
- Conservative ontology (prefer distinct senses; avoid premature merges).
- Dialectical-aware claims/edges (do not flatten appearance/essence and development into binary logic).
- Alignment must be explicit, stored, and auditable.
