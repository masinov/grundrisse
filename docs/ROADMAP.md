# Repo Roadmap (Python)

This repository follows the invariants in `main_plan.txt` and incorporates the reviewer corrections in
`revision.txt`:

- Immutable text substrate (raw snapshots + normalized text), versioned by `Edition`/ingest runs.
- Atomic evidence = `SentenceSpan` and explicit evidence groupings via `SpanGroup`.
- Paragraph-in, sentence-IDs-out for all LLM extraction.
- Provenance-first: every semantic artifact is grounded in evidence spans and tied to an `ExtractionRun`.
- Dialectical-aware claims: modality/scope + dialectical status are first-class, not flattened.
- Conservative ontology: prefer distinct senses; root/sense grouping is explicit.
- Alignment is explicit: translation/edition alignment is stored as `SpanAlignment` records.
- Granular authorship: `TextBlock.author_id_override` (preface/afterword/editorial apparatus).
- Explicit citations are separate from semantic links (`CitationEdge` vs `ClaimLink`).
- Context injection (“anaphora window”) is implemented in pipeline prompts but forbidden in outputs.

## Layout

- `packages/core/`: shared domain + DB models + migrations
- `packages/llm_contracts/`: JSON schemas + prompt templates + validators
- `services/ingest_service/`: marxists.org snapshotting + normalization + segmentation
- `pipelines/nlp_pipeline/`: Stage A/B extraction + clustering/canonicalization
- `ops/`: local infra (Postgres + pgvector)
- `evaluation/`: gold sets + sanity checks (pilot gating)

## Day-1 milestone (vertical slice)

1. Bring up Postgres (`ops/docker-compose.yml`).
2. Apply DB migrations (Alembic in `packages/core/`).
3. Ingest one pilot work (e.g. 1844 Manuscripts) into:
   - `Edition`, `TextBlock`, `Paragraph`, `SentenceSpan`
4. Run Stage A:
   - A1 ConceptMention extraction per paragraph (context injection allowed but output restricted to TARGET)
   - A3 Claim extraction per paragraph (with `attribution` and minimal citation capture)
5. Confirm:
   - evidence indices resolve to existing `SentenceSpan`s
   - block-level authorship overrides work
   - citations are not misattributed to the work author

