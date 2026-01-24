# A SYSTEMATIC PIPELINE FOR UNSUPERVISED ARGUMENT AND DIALECTICAL MOTION EXTRACTION

## Using AIF and Inference Anchoring Theory for Philosophical Corpora

---

## 1. Purpose and scope

This document specifies a complete architecture for extracting, structuring, and interrelating arguments from large philosophical corpora—specifically Marxist texts—without manual annotation.

The system is designed to:

1. Extract arguments in a way that is **faithful to the source text**.
2. Preserve the distinction between **what is said**, **what is meant**, and **what is done** in discourse.
3. Represent **support, conflict, attribution, irony, and refutation** without relying on surface negation.
4. Scale across thousands of pages and multiple authors.
5. Enable higher-order analysis of **dialectical motion**, including contradiction, transformation, and conceptual development.

The architecture synthesizes:

* **Argument Interchange Format (AIF)** as the structural backbone.
* **Inference Anchoring Theory (IAT)** as the linguistic and pragmatic grounding framework.
* Modern **LLM-based extraction**, constrained by formal schemas and self-consistency checks.

---

## 2. Theoretical commitments

### 2.1 Separation of analytical layers

The system enforces a strict separation between:

1. **Locution**
   A concrete utterance or textual span.

2. **Proposition**
   A truth-evaluable content abstracted from one or more locutions.

3. **Illocutionary force**
   The pragmatic action performed with a proposition (asserting, denying, attributing, defining, etc.).

4. **Argumentative relations**
   Structural relations between propositions (support, conflict, rephrasing).

No object is allowed to collapse these layers.

---

### 2.2 Consequences for philosophical texts

This separation is essential for philosophical and polemical writing because:

* Authors frequently **state positions they do not endorse**.
* Refutation often occurs **without explicit negation**.
* Irony and sarcasm are common.
* Definitions function as premises long before they are used.
* Concepts evolve historically rather than remaining static.

---

## 3. Core data model

The system uses an **AIF-compatible graph** with IAT-style anchoring.

### 3.1 Document

Represents a coherent textual unit.

**Fields**

* `doc_id`
* `author`
* `year_written`
* `year_published`
* `edition`
* `translation`
* `source_url`
* `historical_context_tags`

---

### 3.2 Locution (L-node)

Represents a span of text.

**Fields**

* `loc_id`
* `doc_id`
* `start_char`
* `end_char`
* `raw_text`
* `normalized_text`
* `paragraph_id`
* `section_path`
* `footnote_links[]`

Locutions are immutable and constitute the audit trail of the system.

---

### 3.3 Transition

Represents discourse transitions between locutions.

**Fields**

* `transition_id`
* `from_loc_id`
* `to_loc_id`
* `marker` (e.g., "however", "therefore", "on the contrary")
* `function_hint` (contrast, inference, concession, continuation)

**Persistence policy**: Transitions are persisted and queryable as first-class objects. They encode rhetorical motion independent of argument structure and are analytically valuable for:
- Identifying discourse boundaries
- Recovering authorial intent
- Supporting fine-grained navigation

Transitions are not arguments themselves but signal likely illocutionary and argumentative structure.

---

### 3.4 Proposition (I-node)

Represents propositional content.

**Fields**

* `prop_id`
* `surface_locutions[]`
* `canonical_label` (optional, late-stage only)
* `temporal_scope`
* `concept_bindings[]`
* `confidence`

A proposition may be realized by multiple locutions.

---

### 3.5 Illocutionary connection

Anchors locutions to propositions.

**Fields**

* `illoc_id`
* `loc_id`
* `prop_id`
* `force ∈ {assert, deny, attribute, define, distinguish, concede, ironic, hypothetical, prescriptive, question}`
* `attributed_source` (if applicable)
* `confidence`

Illocutionary force is never inferred solely from polarity; it is grounded in discourse cues, transitions, and context.

---

### 3.6 Argumentative relations (AIF S-nodes)

#### Inference (RA-node)

* `ra_id`
* `premises[]`
* `conclusion`
* `scheme_type` (optional)
* `evidence_locutions[]`
* `confidence`

#### Conflict (CA-node)

* `ca_id`
* `targets[]` (propositions or inferences)
* `conflict_type ∈ {rebut, undercut, incompatibility}`
* `evidence_locutions[]`
* `confidence`

#### Rephrase / Equivalence

* `eq_id`
* `prop_a`
* `prop_b`
* `equivalence_type ∈ {paraphrase, abstraction, concretization}`
* `evidence_locutions[]`
* `confidence`

---

## 4. Ingestion and preprocessing

### 4.1 DOM-aware ingestion

Texts must be parsed with structural awareness:

* Preserve paragraph boundaries.
* Preserve quotations and quotation nesting.
* Extract footnotes as independent locutions linked to main text.
* Do not flatten or strip markup prematurely.

Footnotes are often polemical or definitional and must remain accessible.

---

### 4.2 Normalization and offset preservation

Normalize text for processing (whitespace, hyphenation, OCR artifacts), but maintain a reversible mapping to original offsets.

All extracted structures must reference original character spans.

---

### 4.3 Entity normalization

Before extraction, run an entity normalization step to:

1. **Canonicalize named entities**: Map all surface forms to stable entity identifiers
   - "Ricardo" → `entity:david_ricardo`
   - "David Ricardo" → `entity:david_ricardo`
   - "the English economist" (when contextually identified) → `entity:david_ricardo`

2. **Distinguish entity types**:
   - Persons: `entity_type:person`
   - Schools/Groups: `entity_type:school` (e.g., "the Ricardians", "the Young Hegelians")
   - Abstract positions: `entity_type:position`

3. **Create entity bindings**:
   - Each proposition may reference `entity_bindings[]`
   - Bindings include `entity_id`, `entity_type`, and `surface_form`

4. **Stabilize attribution across windows**:
   - Entity resolution uses both local context and a global entity catalog
   - Disambiguation prioritizes author-specific opponents and interlocutors
   - When entities cannot be resolved, mark as `implicit_opponent` with `entity_type:unknown`

This prevents fragmentation of attributed positions and maintains diachronic coherence.

---

### 4.4 Coreference resolution

After entity normalization:

* Run lightweight coreference resolution.
* Resolve pronouns and demonstratives **only in the extraction context**, not in stored text.
* Store coreference mappings separately.

This prevents argument fragmentation without altering source fidelity.

---

## 5. Chunking with long-range memory

### 5.1 Local windows

Use overlapping windows of:

* 2–6 paragraphs
* 1–2 paragraph overlap

This captures local coherence without excessive context loss.

---

### 5.2 Retrieval-augmented context

Each window operates with two contexts:

1. **Local context** (the window itself)
2. **Retrieved context** from previously processed propositions, selected by:

   * Concept overlap
   * Vector similarity
   * Definitional or foundational force tags

---

### 5.3 Mandatory retrieval trigger

If a window contains:

* Conclusion markers ("therefore", "thus", "it follows")
* Evaluative claims ("this shows", "this proves")

and no local premises are detected, the system **must retrieve prior propositions** before relation extraction proceeds.

---

### 5.4 Retrieved context presentation (critical)

To prevent context poisoning, retrieved material is presented to the extraction agent as follows:

1. **Explicit marking**: All retrieved content is prefixed with `[RETRIEVED_CONTEXT]` and structurally separated from the extraction window
2. **Read-only constraint**: Retrieved propositions are marked with `"extractable": false` and cannot generate new locutions
3. **Non-extractible tags**: The system prompt explicitly prohibits:
   - Creating new locutions from retrieved content
   - Re-extracting retrieved propositions as new
   - Inferring illocutionary force from retrieved context alone
4. **Evidence separation**: Relations may cite retrieved propositions as premises, but retrieved text cannot serve as evidence locutions

**Example presentation format**:
```
--- LOCAL WINDOW (extractable) ---
[Paragraph 1] ... [Paragraph N]

--- RETRIEVED CONTEXT (read-only, non-extractible) ---
[1] prop_1234: "Labor is the source of all value." (from Smith, Wealth of Nations, 1776)
[2] prop_5678: "Use-value and exchange-value are distinct." (from Marx, Capital Vol. 1, 1867)
```

---

## 6. Proposition extraction

### 6.1 High-recall extraction

From each window:

* Extract all candidate propositions.
* Multiple propositions per sentence are allowed.
* Each proposition must cite at least one locution span.

No canonicalization occurs at this stage.

---

### 6.2 Illocutionary force assignment

For each proposition–locution pair:

* Assign illocutionary force.
* Attribution and denial are explicitly modeled.
* Irony is treated as a first-class force.

Illocutionary force is determined using:

* Discourse transitions
* Evaluative language
* Rhetorical framing
* Quotation structure

---

### 6.3 Implicit opponent handling

When refutation or contrast occurs without an explicit opponent:

* Create a proposition marked as `attributed`.
* Assign a provisional `implicit_source`.
* Bind it to relevant concept vectors.
* Attach `entity_binding` with `entity_type:unknown` if entity cannot be resolved

Implicit propositions are never left unbound; they are designed to be clustered later.

---

## 7. Argumentative relation induction

### 7.1 Candidate generation (bounded)

For each proposition:

* Compare with propositions in the same window.
* Compare with top-k retrieved propositions.
* Compare only propositions sharing concept bindings or high vector similarity.

---

### 7.2 Relation classification

For each candidate pair, classify:

* Support (RA)
* Conflict (CA)
* Rephrase
* Neutral

Each relation must cite locutional evidence.

---

### 7.3 Undercutting

If a proposition attacks the *connection* between premises and conclusion rather than the conclusion itself, represent the conflict as targeting an inference node.

---

## 8. Canonicalization

Canonicalization is **cluster-based**, never substitution-based.

Process:

1. Build equivalence clusters using rephrase edges and embeddings.
2. Assign an optional canonical label to the cluster.
3. Preserve all surface forms, forces, and spans.

Canonicalization never deletes propositions.

---

## 9. Concept representation and temporal drift

### 9.1 Concept bindings

Each proposition may bind to one or more concepts:

* `concept_id`
* `embedding`
* `time_index` (document date)

---

### 9.2 Diachronic concept modeling

Track concept evolution by:

* Measuring embedding drift across time.
* Detecting redefinition via definitional illocutionary forces.
* Identifying abstraction/concretization patterns.

**Role of concept drift in motion hypotheses**:
- Concept drift is **supporting evidence** for dialectical transformation, not a triggering criterion
- Drift patterns alone do not generate motion hypotheses
- Motion hypotheses require graph-structural confirmation (contradiction + transformation)
- When drift coincides with structural patterns, it strengthens the hypothesis confidence

---

## 10. Cross-document linking

### 10.1 Retrieval

Use hybrid retrieval:

* Vector similarity
* Concept overlap
* Shared implicit opponent clusters
* Entity binding alignment

---

### 10.2 Cross-document relations

Classify:

* Support
* Conflict
* Rephrase
* Refinement
* Historical displacement (claims about different temporal scopes)

All cross-document edges carry confidence and evidence spans.

---

## 11. Dialectical motion derivation

Dialectical structures are **computed**, not extracted.

### 11.1 Contradiction candidates

A contradiction candidate consists of:

* Two proposition clusters
* Persistent conflict edges
* Shared concept bindings
* Comparable temporal scope

---

### 11.2 Motion patterns

Motion candidates are identified by graph-structural patterns:

* Conflict → definitional re-articulation
* Abstract opposition → concrete mechanism
* Repeated failure → new structural determination

**Triggering conditions**:
- Motion hypotheses are triggered **only** when graph-structural patterns are detected
- Concept drift may **support** a hypothesis but never triggers one independently
- Each hypothesis must cite specific nodes and edges forming the pattern

These patterns are graph-structural and time-aware.

---

## 12. Validation without gold annotation

### 12.1 Hard constraints

Reject any structure that violates:

* Span grounding
* AIF graph validity
* Missing evidence for relations
* Unanchored illocutionary force

---

### 12.2 Soft constraints

Penalize:

* Cyclic support in small windows
* Conflict between unrelated concepts
* Excessive equivalence clustering

---

### 12.3 Redundancy and stability

Run multiple extraction passes with:

* Prompt variation
* Model variation

Retain structures that are stable across runs.

---

### 12.4 Round-trip consistency

1. Graph → synthetic summary
2. Compare summary to source text
3. Penalize hallucinated or unsupported content

---

## 13. Error taxonomy for autonomous retries

The autonomous agent must distinguish between failure types to apply appropriate recovery strategies. Each failed step returns a structured error object:

### 13.1 Error types

#### Grounding failure
* **Code**: `GROUNDING_FAILURE`
* **Description**: No valid locution spans could be identified for a proposition or relation
* **Recovery**: Re-run with expanded context window or manual review

#### Schema violation
* **Code**: `SCHEMA_VIOLATION`
* **Description**: Invalid JSON, missing required fields, or type mismatches
* **Recovery**: Retry with schema enforcement; log for prompt refinement

#### Context exhaustion
* **Code**: `CONTEXT_EXHAUSTION`
* **Description**: Insufficient premises detected even after maximum retrieval attempts
* **Recovery**: Mark as enthymememic; create implicit opponent proposition if appropriate

#### Overgeneration
* **Code**: `OVERGENERATION`
* **Description**: Too many propositions generated without clear relations (noise threshold exceeded)
* **Recovery**: Re-run with stricter extraction thresholds

#### Entity resolution failure
* **Code**: `ENTITY_RESOLUTION_FAILURE`
* **Description**: Cannot resolve attributed entity and context insufficient for disambiguation
* **Recovery**: Mark as `implicit_opponent` with `entity_type:unknown`

#### Retrieval poisoning risk
* **Code**: `RETRIEVAL_POISONING_RISK`
* **Description**: Retrieved context may be influencing extraction inappropriately
* **Recovery**: Reduce retrieved context, increase separation markers

#### Validation cycle detected
* **Code**: `VALIDATION_CYCLE`
* **Description**: Same validation failure occurs repeatedly without progress
* **Recovery**: Escalate to manual review or apply fallback strategy

### 13.2 Retry policy

* Max retries per error type: 3
* Exponential backoff: 2^N seconds where N = retry attempt
* After max retries: Log to failure table, continue with next unit
* Fatal errors (corrupt data, missing corpus): Halt pipeline

---

## 14. System outputs

The system produces:

* A searchable argument graph
* Traceable support and rebuttal chains
* Cross-text ideological lineages
* Time-indexed conceptual transformations
* Hypotheses of dialectical motion with full provenance
* Persisted transition objects for discourse analysis

---

## 15. Definition of completion

The system is operational when it can, for any document:

1. Produce span-grounded locutions.
2. Extract propositions with illocutionary force.
3. Build support and conflict relations with evidence.
4. Link arguments across texts with entity alignment.
5. Derive dialectical motion hypotheses transparently.

---

## 16. Developmental Plan and System Architecture

## From Architectural Specification to Autonomous System

This section specifies **how the architecture described above is implemented as a running system**. It defines the execution model, data stores, autonomy boundaries, and validation gates required to produce a reliable, reproducible dialectical argument graph from a large philosophical corpus.

The goal is not to "interpret" texts, but to **autonomously construct the conditions under which interpretation becomes structurally possible**, at scale, and with full provenance.

---

## 16.1 Core design principles

### 16.1.1 Separation of concerns (non-negotiable)

The system is divided into **four orthogonal layers**, each with strict responsibilities:

1. **Textual grounding layer**
   Raw text, locutions, offsets, footnotes, DOM structure
   → immutable, auditable

2. **Argument extraction layer**
   Propositions, illocutionary forces, argumentative relations
   → schema-constrained, repeatable

3. **Persistence and indexing layer**
   Databases and retrieval systems
   → deterministic, versioned

4. **Dialectical analysis layer**
   Cross-text relations, contradiction patterns, motion hypotheses
   → computed, never extracted directly

No layer is allowed to collapse into another.

---

### 16.1.2 Autonomy with guardrails

Autonomy is used **only where error is detectable**.

Autonomous agents may:

* Clean text using explicit rules
* Extract arguments under schema constraints
* Re-run failed steps with error-type-specific recovery (§13)
* Propose cross-document relations with confidence thresholds

Autonomous agents may **not**:

* Delete or overwrite locutions
* Merge propositions irreversibly
* Assert dialectical resolutions without graph-structural evidence
* Modify raw corpus files

---

## 16.2 Execution model

### 16.2.1 Long-running autonomous agent

The system is designed to run under a **persistent autonomous coding agent** (e.g. Claude Code running in a loop, or a similar autonomous execution framework).

This agent:

1. Reads documents from a read-only corpus directory
2. Executes a deterministic pipeline step-by-step
3. Writes all outputs to versioned artifact stores
4. Repeats failed steps using error-type-specific recovery (§13)
5. Logs every decision, rejection, and error code

The agent does **not** reason abstractly about Marxism.
It reasons about **schemas, constraints, and graph structure**.

---

### 16.2.2 Idempotent pipeline stages

Each stage is:

* **Restartable**
* **Order-independent**
* **Addressable by document ID**

This allows:

* Partial corpus processing
* Reprocessing after schema changes
* Parallelization across documents

---

## 16.3 Data storage architecture

The system uses **three complementary stores**, each optimized for a distinct function.

### 16.3.1 Relational / columnar store (canonical index)

A local analytical database (e.g. **DuckDB** or PostgreSQL) is the **system of record** for:

* Documents and metadata
* Entities and entity bindings
* Paragraphs and locutions
* Transitions (persisted for query)
* Footnotes and offset mappings
* Extraction runs and validation results
* Confidence scores and stability metrics
* Error logs by type (§13)

This store guarantees:

* Referential integrity
* Auditability
* Deterministic reconstruction of any result

---

### 16.3.2 Graph database (argument structure)

A property graph database (e.g. **Neo4j**) stores the **AIF/IAT graph**:
* Nodes: Documents, Locutions, Propositions, Inference nodes, Conflict nodes, Concept nodes, Entities
* Edges: Illocutionary anchoring, support, conflict, rephrase, temporal succession, entity_bindings

Hard constraints enforced here:

* No proposition without locution grounding
* No relation without evidence locutions
* No inference cycles within bounded windows

The graph database is **never written to directly by the LLM**; all writes pass through schema validation.

---

### 16.3.3 Vector database (semantic candidate generation)

A vector store (e.g. **Qdrant**) is used **only for retrieval**, never as ground truth.

It stores embeddings for:

* Propositions
* Implicit opponent propositions
* Concepts (time-indexed)
* Entities (for disambiguation)

It is queried to:

* Propose candidate equivalence clusters
* Retrieve cross-document argumentative neighbors
* Detect potential conceptual continuity or drift
* Support entity disambiguation

All vector-derived links must be **confirmed structurally** before promotion.

---

## 16.4 Pipeline stages (end-to-end)

### Stage 1: Corpus ingestion and structural parsing

For each document:

1. Load extracted HTML-derived text
2. Parse with DOM awareness:

   * paragraphs
   * quotations (with nesting)
   * footnotes
3. Generate immutable **Locution nodes** with:

   * stable character offsets
   * section paths
   * footnote links
4. Extract and persist **Transition nodes** from discourse markers
5. Store all locutions, transitions, and offsets in the relational store

**No text is deleted.**
Removed artifacts are logged as excluded spans with reasons.

---

### Stage 2: Entity normalization

For each document:

1. Run entity recognition on all locutions
2. Canonicalize named entities to stable `entity_id`
3. Distinguish persons, schools, and abstract positions
4. Create entity catalog entries with:
   * `entity_id`
   * `canonical_name`
   * `entity_type`
   * `surface_forms[]`
   * `context_references[]`
5. Store entity bindings in relational store

---

### Stage 3: Normalization with reversibility

Normalize text for processing:

* whitespace
* hyphenation
* OCR artifacts

Maintain a reversible mapping:

```
normalized_span ↔ original_span
```

All downstream references use original offsets.

---

### Stage 4: Windowing and retrieval setup

For each document:

* Create overlapping windows:

  * 2–6 paragraphs
  * 1–2 paragraph overlap
* For each window:

  * Identify discourse markers
  * Pre-load retrieved context if mandatory triggers fire
    (as defined in §5.3 of the main spec)
  * Format retrieved context per §5.4 (explicit marking, read-only)

---

### Stage 5: Argument extraction (schema-constrained)

For each window:

1. Run the extraction agent using the **ExtractionWindow schema**
2. Enforce:

   * grounding rules
   * illocution separation
   * evidence requirements
3. Explicitly model:

   * irony
   * attribution
   * implicit opponents
   * entity bindings
4. Output a single JSON object per window

Any schema violation → `SCHEMA_VIOLATION` error and automatic retry.

---

### Stage 6: Validation and stability filtering

Each extraction is subjected to:

**Hard constraints**

* Missing locution grounding → `GROUNDING_FAILURE`
* Relation without evidence → `GROUNDING_FAILURE`
* Invalid AIF structure → `SCHEMA_VIOLATION`

**Soft constraints**

* Excessive equivalence → `OVERGENERATION`
* Unmotivated conflicts → `OVERGENERATION`
* Cyclic support within window → `SCHEMA_VIOLATION`

Extractions are run multiple times (prompt/model variation).
Only **stable structures** are promoted to the canonical graph.

---

### Stage 7: Persistence and indexing

Promoted structures are written to:

* Relational store (full trace, including transitions)
* Graph store (AIF/IAT graph)
* Vector store (embeddings + metadata)

Each write is tagged with:

* extraction run ID
* schema version
* confidence metrics

---

### Stage 8: Per-document dialectical structure

Once a document is fully processed:

* Retrieve all propositions within the document
* Build internal support/conflict networks
* Identify local contradiction clusters
* Generate **internal dialectical trees**

No cross-document links yet.

---

### Stage 9: Cross-document linking

After corpus-level extraction:

1. For each proposition cluster:

   * Retrieve top-k neighbors via vector + concept overlap + entity alignment
2. Classify relations:

   * support
   * conflict
   * rephrase
   * refinement
   * historical displacement
3. Require:

   * evidence spans
   * temporal compatibility checks
   * entity consistency

Only validated relations are added to the global graph.

---

### Stage 10: Dialectical motion computation

Dialectical motion is **derived**, not extracted.

**Triggering conditions**: Only graph-structural patterns (§11.2) trigger motion hypotheses.

Using graph queries:

* Persistent contradiction patterns
* Definitional re-articulations
* Conceptual drift over time (as supporting evidence)
* Support from opposing clusters

Each motion hypothesis stores:

* supporting subgraph
* time range
* confidence score
* rejection criteria
* drift_evidence (if applicable, as supporting factor)

Motion nodes never replace propositions.

---

### Stage 11: Hierarchical summaries (navigation only)

Summaries are generated:

* paragraph → section → chapter → work

They are used **only** to:

* guide retrieval
* enable coarse navigation
* accelerate search

Summaries do **not** create propositions and cannot ground arguments.

---

## 16.5 Versioning, reproducibility, and audit

The system guarantees that:

* Every node can be traced to text spans
* Every relation cites evidence
* Every graph can be regenerated from raw corpus + config
* No destructive operation is irreversible

Artifacts are versioned by:

* schema version
* extraction configuration
* model/prompt identifiers

---

## 16.6 Definition of operational readiness

The system is considered fully implemented when:

1. Any document can be processed end-to-end without manual intervention
2. All arguments are span-grounded and schema-valid
3. Entity normalization stabilizes attribution across windows
4. Cross-document dialectical relations are reproducible
5. Motion hypotheses are explainable via graph structure
6. All error types (§13) have defined recovery strategies
7. Retrieved context is properly isolated to prevent poisoning
8. The corpus can be reprocessed under new theoretical assumptions without loss of prior data

---

## Closing note

This implementation plan does not automate interpretation.
It automates **the preservation of argumentative possibility**.

The result is not *"the dialectic of Marx"*, but a machine-readable space in which dialectical critique, reconstruction, and disagreement can occur—by humans or by future autonomous theorists—without collapsing text, meaning, and action into a single layer.

---

## Appendix A: Schema Definition (Pydantic)

```python
from typing import List, Optional, Literal, Dict
from pydantic import BaseModel, Field, conlist

# --- 1. The Grounding Layer (Locutions) ---
class Locution(BaseModel):
    """
    L-Node: An immutable span of text.
    Every higher-order object MUST reference loc_ids.
    """
    loc_id: str = Field(..., description="Unique hash of doc_id + offsets")
    text: str = Field(..., description="Verbatim text slice")
    start_char: int
    end_char: int
    # Structural context
    paragraph_id: str
    section_path: List[str]
    is_footnote: bool = False

class Transition(BaseModel):
    """
    Discourse transition between locutions (persisted, queryable).
    """
    transition_id: str
    from_loc_id: str
    to_loc_id: str
    marker: str = Field(..., description="e.g., 'however', 'therefore'")
    function_hint: Literal["contrast", "inference", "concession", "continuation"]

# --- 2. The Propositional Layer (I-Nodes) ---
class EntityBinding(BaseModel):
    entity_id: str
    entity_type: Literal["person", "school", "position", "unknown"]
    surface_form: str
    confidence: float

class ConceptBinding(BaseModel):
    concept_label: str
    confidence: float

class Proposition(BaseModel):
    """
    I-Node: Abstract content.
    Separated from the act of uttering it.
    """
    prop_id: str
    # A proposition can be expressed by multiple locutions (e.g. repetition)
    surface_loc_ids: List[str] = Field(..., min_items=1, description="Must be grounded")

    # Content representation
    text_summary: str = Field(..., description="Self-contained statement of content")
    concept_bindings: List[ConceptBinding] = []
    entity_bindings: List[EntityBinding] = []

    # Temporal/Dialectical Tags
    temporal_scope: Optional[str] = Field(None, description="e.g., '1844', 'Capitalist Mode'")
    is_implicit_reconstruction: bool = Field(False, description="True if reconstructed from enthymeme")

# --- 3. The Illocutionary Layer (Anchoring) ---
IllocutionType = Literal[
    "assert", "deny", "question",
    "define", "distinguish",
    "attribute", "concede",
    "ironic", "hypothetical", "prescriptive"
]

class IllocutionaryEdge(BaseModel):
    """
    The link between L-Node and I-Node.
    Captures 'What is done' with the text.
    """
    illoc_id: str
    source_loc_id: str
    target_prop_id: str
    force: IllocutionType

    # Critical for Marxist texts:
    attributed_to: Optional[str] = Field(
        None, description="Person/School (e.g., 'Ricardo', 'The Vulgar Economists')"
    )
    is_implicit_opponent: bool = Field(False, description="True if target is an abstract/unnamed opponent")

# --- 4. The Argumentative Layer (S-Nodes) ---
RelationType = Literal["support", "conflict", "rephrase"]
ConflictType = Literal["rebut", "undercut", "incompatibility"]

class ArgumentRelation(BaseModel):
    """
    RA/CA/MA Nodes.
    Captures dialectical motion between I-Nodes.
    """
    rel_id: str
    relation_type: RelationType

    # Direction
    source_prop_ids: List[str] = Field(..., description="Premises / Attacking Claims")
    target_prop_id: str = Field(..., description="Conclusion / Attacked Claim")

    # Metadata
    conflict_detail: Optional[ConflictType] = None

    # Evidence is MANDATORY
    evidence_loc_ids: List[str] = Field(..., min_items=1, description="Text spans (e.g. 'therefore') licensing the link")

# --- 5. The Window Output Container ---
class ExtractionWindow(BaseModel):
    locutions: List[Locution]
    transitions: List[Transition]
    propositions: List[Proposition]
    illocutions: List[IllocutionaryEdge]
    relations: List[ArgumentRelation]
```

---

## Appendix B: Error Schema for Autonomous Retries

```python
from enum import Enum
from typing import Optional, Dict, Any

class ErrorType(str, Enum):
    GROUNDING_FAILURE = "GROUNDING_FAILURE"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    CONTEXT_EXHAUSTION = "CONTEXT_EXHAUSTION"
    OVERGENERATION = "OVERGENERATION"
    ENTITY_RESOLUTION_FAILURE = "ENTITY_RESOLUTION_FAILURE"
    RETRIEVAL_POISONING_RISK = "RETRIEVAL_POISONING_RISK"
    VALIDATION_CYCLE = "VALIDATION_CYCLE"

class ExtractionError(BaseModel):
    error_type: ErrorType
    stage: str  # e.g., "proposition_extraction", "relation_classification"
    doc_id: Optional[str] = None
    window_id: Optional[str] = None
    message: str
    details: Dict[str, Any]
    retry_count: int = 0
    suggested_recovery: str

class RetryPolicy(BaseModel):
    max_retries: Dict[ErrorType, int] = {
        ErrorType.GROUNDING_FAILURE: 3,
        ErrorType.SCHEMA_VIOLATION: 3,
        ErrorType.CONTEXT_EXHAUSTION: 2,
        ErrorType.OVERGENERATION: 3,
        ErrorType.ENTITY_RESOLUTION_FAILURE: 1,
        ErrorType.RETRIEVAL_POISONING_RISK: 2,
        ErrorType.VALIDATION_CYCLE: 0,  # Fatal, requires manual review
    }
    base_backoff_seconds: int = 1
```
