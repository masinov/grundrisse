## Validation & QA Workflow (Pilot → Corpus)

This repository currently has minimal automated tests. Until a formal `evaluation/` suite exists,
validation is performed via:

1) **DB integrity gates** (must always pass)
2) **Coverage metrics** (should be stable and explainable)
3) **Targeted human spot-check sampling** (answers “does this hold?”)

The goal is to keep the system provenance-first and auditable: all semantic artifacts must remain
traceable to `SentenceSpan` evidence.

---

## 1) DB Integrity Gates (must pass)

### 1.1 Evidence integrity

Verify:
- every `SpanGroupSpan.span_id` belongs to the same `edition_id` as its `SpanGroup.edition_id`
- if `SpanGroup.para_id` is set, each grouped span has the same `para_id`
- there are no empty `SpanGroup`s

If any of these fail, Stage A output is not auditable and should be treated as invalid.

---

## 2) Coverage Metrics (should be explainable)

### 2.1 Per-edition substrate + outputs

For a given `work_id`, record per `edition_id`:
- `paragraph` count
- `sentence_span` count
- `concept_mention` count
- `claim` count (via `claim_evidence → span_group`)
- Stage B concept assignment % (`concept_mention.concept_id IS NOT NULL`)

Use this to detect ingestion duplication (e.g., 314 → 628 paragraphs) and partially processed runs.

### 2.2 Stage A paragraph coverage

For a given `edition_id`, count:
- paragraphs with spans but **no** mentions
- paragraphs with spans but **no** claims

These should be spot-checked; headings/apparatus often explain zeros, but systematic gaps indicate
prompt/segmentation issues.

---

## 3) Targeted Spot-Check Sampler (human validation)

Use `grundrisse-nlp sample-edition` to print a compact, auditable sample:
- paragraph text (reconstructed from ordered `SentenceSpan`s)
- mentions in that paragraph + assigned concept label (if Stage B ran)
- a few claims in that paragraph with evidence spans

Sample sets:
- random paragraphs (typical behavior)
- paragraphs with no mentions (ensure they are headings/boilerplate)
- paragraphs with no claims (ensure they are non-argumentative or very short)

Acceptance criteria for a pilot work:
- evidence indices are correct (no off-by-one / out-of-paragraph spans)
- extracted claims are readable and grounded in the printed evidence spans
- extracted concepts are not obviously garbage merges

---

## 4) Common Failure Modes & Fix Strategy

### 4.1 Stage B schema drift

Symptom: model returns invalid JSON or drifted keys (e.g., `gloss:`).
Fix strategy (in order):
1) retry with a strict “repair” prompt including the validation error
2) allow narrow, unambiguous key-typo tolerance (e.g., `gloss:` → `gloss`)
3) if still failing, mark the cluster as failed and persist raw output for audit

### 4.2 Duplicate/fragmented concepts

Symptom: multiple `Concept`s with the same `label_canonical` within a work.
Fix strategy:
- Stage B should reuse existing concepts (within the same work) when the canonical label matches.
- Improve clustering keys and add alias rules (conservative; avoid cross-work merges).

