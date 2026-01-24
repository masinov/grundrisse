# Argument Extraction - Sequential Development Plan

## Current State Assessment

### Database Status (PostgreSQL)
| Entity | Count | Notes |
|--------|-------|-------|
| Works | 19,098 | With metadata |
| Editions | 19,111 | Language-specific versions |
| Paragraphs | 1,763,385 | Text available via `text_normalized` |
| SentenceSpans | 6,232,167 | Tokenized sentences |
| TextBlocks | ~100k+ | DOM structure with hierarchy |

### Infrastructure Running
| Component | Status |
|-----------|--------|
| PostgreSQL | ✅ localhost:5432 |
| Neo4j | ✅ localhost:7687 (Bolt), localhost:7474 (HTTP) |
| Qdrant | ✅ localhost:6333 |
| Python packages | ✅ grundrisse-argument-extraction, grundrisse-argument-pipeline |

### Text Status
The text is **already cleaned and structured**:
- Extracted from HTML via `ingest_service/parse/html_to_blocks.py`
- Stored in `Paragraph.text_normalized` and `SentenceSpan.text`
- No additional "cleaning" stage needed
- DOM structure preserved in `TextBlock` hierarchy

---

## Development Phases

The development is organized into **9 sequential phases**, each building on the previous.
Each phase produces a testable, deliverable component.

---

## Phase 1: Database Schema Extension

**Goal**: Add AIF/IAT tables to PostgreSQL for argument extraction results.

### Tasks
1.1 Create SQLAlchemy models:
   - `ArgumentLocution` (maps to existing Paragraph/SentenceSpan)
   - `ArgumentProposition` (I-node)
   - `ArgumentIllocution` (L→P edges)
   - `ArgumentRelation` (RA/CA/eq edges)
   - `ArgumentTransition` (discourse markers)
   - `ArgumentExtractionRun` (pipeline tracking)
   - `EntityCatalog` & `EntityBinding` (entity normalization)

1.2 Create Alembic migration

1.3 Add foreign key constraints:
   - Propositions → Locutions
   - Illocutions → Locutions + Propositions
   - Relations → Propositions + Evidence Locutions

**Deliverable**: Working migration that can be run with `alembic upgrade head`

**Estimation**: 2-3 hours

---

## Phase 2: Locution Bridge Layer

**Goal**: Expose existing Paragraphs/SentenceSpans as Locutions for the argument pipeline.

### Tasks
2.1 Create `ArgumentLocution` model that references:
   - `paragraph_id` or `sentence_span_id`
   - `edition_id`
   - `text_content`
   - Character offsets

2.2 Create factory/adapter functions:
   - `paragraph_to_locution(para: Paragraph) -> Locution`
   - `span_to_locution(span: SentenceSpan) -> Locution`

2.3 Create initial population script:
   - Backfill locutions from existing paragraphs/spans
   - Assign stable `loc_id` using deterministic UUID

**Deliverable**:
- `ArgumentLocution` model
- Bridge functions in `packages/argument_extraction/src/grundrisse_argument/locution_bridge.py`
- Initial backfill script

**Estimation**: 2-3 hours

---

## Phase 3: Windowing System

**Goal**: Group paragraphs into overlapping windows for LLM processing.

### Tasks
3.1 Create window builder:
   ```python
   class WindowBuilder:
       def build_windows(
           edition_id: UUID,
           min_paragraphs: int = 2,
           max_paragraphs: int = 6,
           overlap: int = 1
       ) -> List[ExtractionWindow]
   ```

3.2 Implement discourse marker detection:
   - Simple regex-based marker extraction
   - Classify: contrast ("however", "but"), inference ("therefore", "thus"), concession

3.3 Create `Transition` objects from markers

3.4 Window context assembly:
   - Include paragraph texts
   - Include previous/next context for overlap
   - Include transition markers

**Deliverable**: `packages/argument_extraction/src/grundrisse_argument/windowing/`

**Estimation**: 3-4 hours

---

## Phase 4: LLM Extraction Agent

**Goal**: Extract propositions, illocutions, and relations from windows.

### Tasks
4.1 Create extraction prompt using `task_c1_argument_extraction.json` schema

4.2 Implement Z.ai GLM client integration:
   - Reuse existing `nlp_pipeline/llm/zai_glm.py` pattern
   - Add retry logic with exponential backoff

4.3 Create extraction orchestrator:
   ```python
   async def extract_window(
       window: ExtractionWindowInput,
       retrieved_context: List[PropositionSummary]
   ) -> ExtractionWindow
   ```

4.4 Implement error handling:
   - Map LLM errors to `ErrorType` taxonomy
   - Automatic retry with prompt adjustment

**Deliverable**: `pipelines/argument_pipeline/src/argument_pipeline/llm/extractor.py`

**Estimation**: 4-6 hours (most complex phase)

---

## Phase 5: Validation System

**Goal**: Enforce hard and soft constraints on extractions.

### Tasks
5.1 Implement hard constraint validators:
   - `check_grounding()`: All propositions cite existing locutions
   - `check_evidence()`: All relations cite evidence spans
   - `check_schema()`: Pydantic validation

5.2 Implement soft constraint validators:
   - `check_cycles()`: No cyclic support in small windows
   - `check_overgeneration()`: Flag excessive outputs

5.3 Create validation pipeline:
   ```python
   def validate_extraction(window: ExtractionWindow) -> ValidationResult:
       # Run all validators
       # Return errors with error types
   ```

**Deliverable**: `pipelines/argument_pipeline/src/argument_pipeline/validation/`

**Estimation**: 2-3 hours

---

## Phase 6: Neo4j Persistence

**Goal**: Store AIF/IAT graph in Neo4j with constraint enforcement.

### Tasks
6.1 Implement Neo4j client methods:
   ```python
   class Neo4jClient:
       def create_locution(loc: Locution)
       def create_proposition(prop: Proposition)
       def create_illocution(illoc: IllocutionaryEdge)
       def create_relation(rel: ArgumentRelation)
       def create_transition(trans: Transition)
   ```

6.2 Create constraints in Neo4j:
   - No proposition without locution
   - No relation without evidence
   - No orphan nodes

6.3 Implement batch operations:
   - `persist_window(window: ExtractionWindow)`

**Deliverable**: Complete `packages/argument_extraction/src/grundrisrise_argument/graph/neo4j.py`

**Estimation**: 3-4 hours

---

## Phase 7: Vector Retrieval

**Goal**: Enable semantic retrieval for cross-document linking.

### Tasks
7.1 Complete Qdrant client implementation:
   ```python
   class QdrantClient:
       def upsert_proposition(prop_id, embedding, metadata)
       def search_similar(query_embedding, top_k=10)
       def initialize_collections()
   ```

7.2 Create embedding encoder wrapper:
   - Load sentence-transformers model
   - Cache embeddings
   - Batch encoding

7.3 Create retrieval service:
   ```python
   def retrieve_context(
       window_text: str,
       concept_hints: List[str],
       top_k: int = 5
   ) -> List[PropositionSummary]
   ```

**Deliverable**: Complete `packages/argument_extraction/src/grundrisse_argument/vector/`

**Estimation**: 2-3 hours

---

## Phase 8: Per-Document Analysis

**Goal**: Build internal dialectical structures within documents.

### Tasks
8.1 Implement document-level aggregation:
   - Collect all propositions from a document
   - Build support/conflict networks

8.2 Create contradiction detection:
   - Identify persistent conflicts
   - Cluster opposing proposition groups

8.3 Create CLI command:
   ```bash
   grundrisse-argument analyze <doc_id>
   ```

**Deliverable**: `pipelines/argument_pipeline/src/argument_pipeline/stages/s08_analysis.py`

**Estimation**: 3-4 hours

---

## Phase 9: Cross-Document Linking

**Goal**: Find argumentative relations across documents.

### Tasks
9.1 Implement candidate generation via vector search

9.2 Implement relation classification for cross-document pairs

9.3 Add temporal compatibility checks (earlier vs later)

**Deliverable**: `pipelines/argument_pipeline/src/argument_pipeline/stages/s09_crosslink.py`

**Estimation**: 3-4 hours

---

## Phase 10: Dialectical Motion Computation

**Goal**: Compute motion hypotheses from graph patterns.

### Tasks
10.1 Implement Neo4j queries for motion patterns:
    - Conflict → definitional re-articulation
    - Abstract → concrete movement
    - Repeated failure → new determination

10.2 Create motion hypothesis generator:
    ```python
    def compute_motion_hypotheses(doc_id: UUID) -> List[MotionHypothesis]
    ```

10.3 Store hypotheses as graph metadata

**Deliverable**: `pipelines/argument_pipeline/src/argument_pipeline/stages/s10_motion.py`

**Estimation**: 4-5 hours

---

## Summary

| Phase | Focus | Estimation | Dependencies |
|-------|-------|------------|--------------|
| 1 | Database schema extension | 2-3h | None |
| 2 | Locution bridge layer | 2-3h | Phase 1 |
| 3 | Windowing system | 3-4h | Phase 2 |
| 4 | LLM extraction agent | 4-6h | Phases 2, 3 |
| 5 | Validation system | 2-3h | Phase 4 |
| 6 | Neo4j persistence | 3-4h | Phases 1, 5 |
| 7 | Vector retrieval | 2-3h | None |
| 8 | Per-document analysis | 3-4h | Phases 5, 6 |
| 9 | Cross-document linking | 3-4h | Phases 7, 8 |
| 10 | Dialectical motion | 4-5h | Phases 6, 8, 9 |

**Total estimation**: 33-47 hours of focused development

---

## Immediate Next Step

**Start with Phase 1: Database Schema Extension**

This is the foundation that everything else builds on. Without the database tables, we cannot persist any extraction results.

```bash
# Create new branch for schema
git checkout -b feature/argument-extraction-schema

# Create migration file
cd packages/core && alembic revision -m "add argument extraction tables"
```

Would you like to begin with Phase 1?
