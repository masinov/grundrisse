# Argument Extraction Infrastructure - Setup Plan

## Overview

This document outlines the infrastructure setup for implementing the AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION specification.

---

## Existing Infrastructure (Reusable)

| Component | Status | Notes |
|-----------|--------|-------|
| PostgreSQL | ✅ Running | Docker Compose at `ops/docker-compose.yml` |
| SQLAlchemy | ✅ Installed | Via `grundrisse-core` |
| Pydantic | ✅ Installed | Via `grundrisse-core` |
| LLM (GLM via Z.ai) | ✅ Implemented | In `nlp_pipeline/llm/zai_glm.py` |
| Text ingestion | ✅ Implemented | `ingest_service/parse/html_to_blocks.py` |
| Locution extraction | ✅ Implemented | `TextBlock`, `Paragraph`, `SentenceSpan` models |

---

## New Infrastructure Required

### 1. Graph Database (Neo4j)

**Purpose**: Store AIF/IAT argument graph

**Package**: `neo4j>=5.0`

**Docker service** (add to `ops/docker-compose.yml`):
```yaml
neo4j:
  image: neo4j:5.15-community
  ports:
    - "7474:7474"  # HTTP
    - "7687:7687"  # Bolt
  environment:
    NEO4J_AUTH: neo4j/grundrisse
    NEO4J_PLUGINS: '["apoc"]'
    NEO4J_dbms_memory_heap_initial__size: 512m
    NEO4J_dbms_memory_heap_max__size: 1G
  volumes:
    - neo4j_data:/data
```

**Environment variables**:
```bash
GRUNDRISSE_NEO4J_URI=bolt://localhost:7687
GRUNDRISSE_NEO4J_USER=neo4j
GRUNDRISSE_NEO4J_PASSWORD=grundrisse
```

---

### 2. Vector Database (Qdrant)

**Purpose**: Semantic retrieval for cross-document linking, concept drift detection

**Package**: `qdrant-client>=1.7`

**Docker service** (add to `ops/docker-compose.yml`):
```yaml
qdrant:
  image: qdrant/qdrant:1.7.4
  ports:
    - "6333:6333"  # HTTP
    - "6334:6334"  # gRPC
  volumes:
    - qdrant_data:/qdrant/storage
```

**Environment variables**:
```bash
GRUNDRISSE_QDRANT_HOST=localhost
GRUNDRISSE_QDRANT_PORT=6333
```

---

### 3. Entity Recognition & Normalization

**Purpose**: Canonicalize named entities (persons, schools, positions)

**Package options**:

| Option | Pros | Cons |
|--------|------|------|
| `spacy>=3.7` | Fast, easy, multilingual models | Requires model download |
| `transformers`+HF | State-of-the-art | Heavier, slower |
| API (OpenAI/Anthropic) | No local setup | Cost, latency |

**Recommendation**: Start with `spacy` with `en_core_web_trf` model

**Installation**:
```bash
pip install spacy>=3.7
python -m spacy download en_core_web_trf
```

**Environment variables**:
```bash
GRUNDRISSE_SPACY_MODEL=en_core_web_trf
```

---

### 4. Vector Embeddings

**Purpose**: Embed propositions, concepts, entities for retrieval

**Package options**:

| Option | Pros | Cons |
|--------|------|------|
| `sentence-transformers` | Local, fast, good quality | ~500MB model |
| `openai` embeddings | Best quality | Cost, API dependency |
| GLM embeddings | Already using GLM | May need separate endpoint |

**Recommendation**: Start with `sentence-transformers` using `all-MiniLM-L6-v2`

**Installation**:
```bash
pip install sentence-transformers
```

**Environment variables**:
```bash
GRUNDRISSE_EMBEDDING_MODEL=all-MiniLM-L6-v2
GRUNDRISSE_EMBEDDING_DEVICE=cpu  # or cuda
```

---

### 5. Coreference Resolution

**Purpose**: Resolve pronouns and demonstratives in extraction context

**Package**: `fastcoref` or `spacy-experimental`

**Recommendation**: Start with `fastcoref` (faster, good quality)

**Installation**:
```bash
pip install fastcoref
```

---

## New Package Structure

```
packages/
  argument_extraction/           # NEW: Core AIF/IAT data models
    src/grundrisse_argument/
      __init__.py
      models/
        __init__.py
        locution.py              # L-node
        proposition.py           # I-node
        illocution.py            # Illocutionary edge
        relation.py              # S-node (RA/CA/eq)
        transition.py            # Discourse transitions
        entity.py                # Entity bindings
      errors/
        __init__.py
        types.py                 # Error taxonomy
      graph/
        __init__.py
        neo4j.py                 # Neo4j client
      vector/
        __init__.py
        qdrant.py                # Qdrant client
      entity/
        __init__.py
        normalizer.py            # Entity normalization
      embeddings/
        __init__.py
        encoder.py               # Sentence encoder
    pyproject.toml

pipelines/
  argument_pipeline/             # NEW: Pipeline orchestration
    src/argument_pipeline/
      __init__.py
      cli.py                     # Main CLI
      settings.py                # Configuration
      stages/
        __init__.py
        s01_parse.py             # DOM parsing (reuse ingest)
        s02_entity_norm.py       # Entity normalization
        s03_window.py            # Windowing + retrieval
        s04_extract.py           # LLM extraction
        s05_validate.py          # Validation
        s06_persist.py           # Persistence
        s07_crossdoc.py          # Cross-document linking
        s08_motion.py            # Dialectical motion
      llm/
        __init__.py
        extractor.py             # Extraction agent
        prompts.py               # System/extractor prompts
      validation/
        __init__.py
        constraints.py           # Hard/soft constraints
      retrieval/
        __init__.py
        vector_store.py          # Vector retrieval
    pyproject.toml

packages/
  llm_contracts/
    src/grundrisse_contracts/
      schemas/
        task_c1_extraction.json  # Argument extraction schema
```

---

## Installation Dependencies Summary

### For `packages/argument_extraction/pyproject.toml`:
```toml
dependencies = [
  "grundrisse-core",
  "pydantic>=2.0",
  "neo4j>=5.0",
  "qdrant-client>=1.7",
  "sentence-transformers>=2.2",
  "spacy>=3.7",
  "fastcoref>=1.0",
]
```

### For `pipelines/argument_pipeline/pyproject.toml`:
```toml
dependencies = [
  "grundrisse-core",
  "grundrisse-argument-extraction",
  "grundrisse-llm-contracts",
  "typer>=0.12",
  "httpx>=0.27",
  "pydantic-settings>=2.0",
  "rich>=13.0",  # CLI progress/output
]
```

---

## First Feature: Foundation Setup

**Branch name**: `feature/argument-extraction-infrastructure`

**Tasks**:
1. Add Neo4j and Qdrant to Docker Compose
2. Create `packages/argument_extraction/` with Pydantic models
3. Create `pipelines/argument_pipeline/` skeleton
4. Set up database connection abstractions
5. Create initial CLI entry point
6. Add environment configuration
7. Install and verify spacy model
8. Install and verify sentence-transformers

**Definition of done**:
- [ ] `docker compose up` starts PostgreSQL, Neo4j, and Qdrant
- [ ] All Pydantic models defined and validated
- [ ] CLI command `grundrisse-argument --help` works
- [ ] Can connect to Neo4j and Qdrant
- [ ] Can encode a test sentence and store in Qdrant
- [ ] Can create a simple node in Neo4j

---

## CLI Preview

```bash
# Main entry point
grundrisse-argument extract <doc_id>          # Extract arguments from document
grundrisse-argument validate <doc_id>         # Validate extraction
grundrisse-argument cross-link <doc_id>       # Cross-document linking
grundrisse-argument motion <doc_id>           # Compute dialectical motion
grundrisse-argument status                    # Show pipeline status
```

---

## Development Sequence

| Phase | Focus | Estimated Complexity |
|-------|-------|---------------------|
| 1 | Infrastructure setup | Medium |
| 2 | Data models + schemas | Low-Medium |
| 3 | Entity normalization | Medium |
| 4 | Windowing + retrieval | Medium |
| 5 | LLM extraction | High |
| 6 | Validation | Low-Medium |
| 7 | Persistence | Medium |
| 8 | Cross-document linking | High |
| 9 | Dialectical motion | High |

This setup focuses on **Phase 1** first.
