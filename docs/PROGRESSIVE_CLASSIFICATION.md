# Progressive Classification Architecture

This document describes the two-phase progressive classification system for generalizable, budget-aware website crawling and classification.

## Overview

The progressive classifier solves a fundamental problem: **How do you classify an entire website's structure using LLMs when the site is too large to fit in a single context window?**

**Solution**: Separate cheap discovery from expensive classification, then use hierarchical progressive classification with budget control.

## Two-Phase Architecture

### Phase 1: Link Graph Building (Cheap)

**Cost**: O(pages × HTTP_request)
**No LLM calls**

```
┌─────────────────────────────────────┐
│  Input: Seed URL                    │
│  Output: Complete link graph        │
│                                     │
│  For each URL:                      │
│    1. Fetch HTML                    │
│    2. Extract links                 │
│    3. Store parent-child relations  │
│    4. Store depth in tree           │
│    5. Snapshot to disk              │
│                                     │
│  Result: UrlCatalogEntry table      │
│  populated with full link graph     │
└─────────────────────────────────────┘
```

**Database state after Phase 1**:
```sql
SELECT url_canonical, depth, parent_url_id, child_count
FROM url_catalog_entry
WHERE crawl_run_id = '...';

-- Example output:
-- marxists.org/             depth=0  parent=NULL    children=50
-- marxists.org/archive/     depth=1  parent=root    children=200
-- .../archive/marx/         depth=2  parent=archive children=30
-- .../marx/works/1844/      depth=3  parent=marx    children=15
-- .../1844/manuscripts/ch1  depth=4  parent=1844    children=0
```

### Phase 2: Progressive Classification (Expensive)

**Cost**: O(subtrees × LLM_call × tokens_per_call)
**Budget-controlled**, **resumable**, **progressive**

```
┌─────────────────────────────────────┐
│  Strategy: Leaf-to-Root             │
│                                     │
│  1. Find deepest unclassified nodes │
│  2. Group siblings (same parent)    │
│  3. Extract content samples         │
│  4. Build context with parent info  │
│  5. Ask LLM to classify subtree     │
│  6. Store classifications           │
│  7. Move to shallower depth         │
│  8. Repeat until budget exhausted   │
│                                     │
│  Context for LLM includes:          │
│   - Parent classification           │
│   - Sibling URLs                    │
│   - Page titles/h1/content samples  │
│   - Depth in tree                   │
└─────────────────────────────────────┘
```

## Why Leaf-to-Root?

Starting at the deepest pages (leaves) and moving upward (root) is optimal because:

1. **Concrete first**: Content pages are easiest to classify (they have the actual work text)
2. **Natural grouping**: Chapters of same work are siblings at same depth
3. **Context builds up**: Parent classifications inform child classifications
4. **Bottom-up aggregation**: Works → Authors → Collections → Site structure

## Example Workflow

### Step 1: Build Link Graph

```bash
grundrisse-ingest crawl-build-graph https://www.marxists.org/ \
  --max-depth 6 \
  --max-urls 5000 \
  --crawl-delay 0.5

# Output:
# Starting crawl run: abc-123-def
# Building link graph from https://www.marxists.org/...
# ✓ Link graph built successfully!
#   URLs discovered: 4,523
#   URLs fetched: 4,301
#   URLs failed: 222
#   Max depth reached: 6
#
# Next step: Run classification with:
#   grundrisse-ingest crawl-classify abc-123-def
```

**What happened**:
- Crawled site breadth-first to depth 6
- Stored all URLs with parent relationships
- No classification yet, just structure
- Cost: ~4,300 HTTP requests (~$0)

### Step 2: Progressive Classification

```bash
grundrisse-ingest crawl-classify abc-123-def \
  --budget-tokens 100000 \
  --strategy leaf_to_root \
  --max-nodes-per-call 15

# Output:
# Starting classification run: xyz-789-ghi
# Strategy: leaf_to_root
# Token budget: 100,000
#
# Classifying depth 6... (120 URLs, 8 LLM calls)
# Classifying depth 5... (250 URLs, 17 LLM calls)
# Classifying depth 4... (180 URLs, 12 LLM calls)
# ⚠ Budget exceeded (97,234 / 100,000 tokens used)
#
# ✓ Classification completed!
#   URLs classified: 550
#   LLM calls: 37
#   Errors: 2
#   Tokens used: 97,234 / 100,000
#   Status: budget_exceeded
#
# ⚠ Budget exceeded. Run again with more tokens to continue:
#   grundrisse-ingest crawl-classify abc-123-def --budget-tokens 50000
```

**What happened**:
- Started at depth 6 (deepest pages)
- Grouped siblings by parent
- Asked LLM to classify 15 URLs at a time
- Used parent classifications for context
- Stopped when budget nearly exhausted
- 550 of 4,301 URLs now classified

### Step 3: Review Classifications

```bash
grundrisse-ingest crawl-review abc-123-def --group-by work

# Output:
# Crawl Run: abc-123-def
# Total URLs: 4,301
# Classified: 550 (12.8%)
# Unclassified: 3,751
#
# Sample classifications (grouped by work):
#
#   Work: Economic and Philosophic Manuscripts of 1844
#     - .../marx/works/1844/manuscripts/ch01.htm
#       Type: work_page, Author: Karl Marx
#     - .../marx/works/1844/manuscripts/ch02.htm
#       Type: work_page, Author: Karl Marx
#     - .../marx/works/1844/manuscripts/preface.htm
#       Type: work_page, Author: Karl Marx
#     - .../marx/works/1844/manuscripts/index.htm
#       Type: work_toc, Author: Karl Marx
#
#   Work: The Communist Manifesto
#     - .../marx/works/1848/communist-manifesto/ch01.htm
#       Type: work_page, Author: Karl Marx
#     - .../marx/works/1848/communist-manifesto/ch02.htm
#       Type: work_page, Author: Karl Marx
#     ...
```

### Step 4: Continue Classification (Optional)

```bash
# Add more budget to continue
grundrisse-ingest crawl-classify abc-123-def --budget-tokens 50000

# Continues from where it left off (depth 4)
# Uses existing classifications as context for new ones
```

### Step 5: Use Classifications

Once classified, you can:

```sql
-- Find all work pages for Karl Marx
SELECT url_canonical,
       classification_result->>'work_title' as work_title,
       classification_result->>'page_type' as page_type
FROM url_catalog_entry
WHERE classification_result->>'author' = 'Karl Marx'
  AND classification_result->>'page_type' = 'work_page'
  AND classification_result->>'is_primary_content' = 'true';

-- Find all works by language
SELECT DISTINCT
       classification_result->>'work_title' as work_title,
       classification_result->>'author' as author
FROM url_catalog_entry
WHERE classification_result->>'language' = 'es'
  AND classification_result->>'work_title' IS NOT NULL
ORDER BY author, work_title;

-- Feed to ingestion
-- (Create WorkDiscovery entries from classified URLs)
```

## Classification Prompt Design

The LLM receives:

```json
{
  "parent": {
    "url": "https://www.marxists.org/archive/marx/works/1844/",
    "depth": 3,
    "classification": {
      "page_type": "work_index",
      "author": "Karl Marx",
      "language": "en"
    }
  },
  "urls": [
    {
      "url": "https://www.marxists.org/archive/marx/works/1844/manuscripts/ch01.htm",
      "depth": 4,
      "child_count": 0,
      "title": "Economic and Philosophic Manuscripts of 1844 - Chapter 1",
      "h1": "Estranged Labour",
      "content_sample": "We have proceeded from the premises of political economy..."
    },
    // ... up to 15 siblings
  ]
}
```

And returns:

```json
{
  "classifications": [
    {
      "url": "https://www.marxists.org/archive/marx/works/1844/manuscripts/ch01.htm",
      "page_type": "work_page",
      "author": "Karl Marx",
      "work_title": "Economic and Philosophic Manuscripts of 1844",
      "language": "en",
      "is_primary_content": true,
      "confidence": 0.95
    }
  ],
  "groups": [
    {
      "group_type": "work",
      "work_title": "Economic and Philosophic Manuscripts of 1844",
      "author": "Karl Marx",
      "language": "en",
      "member_urls": [
        "https://www.marxists.org/archive/marx/works/1844/manuscripts/ch01.htm",
        "https://www.marxists.org/archive/marx/works/1844/manuscripts/ch02.htm",
        "https://www.marxists.org/archive/marx/works/1844/manuscripts/ch03.htm"
      ]
    }
  ]
}
```

## Budget Control

```python
class ProgressiveClassifier:
    def classify_leaf_to_root(self, max_nodes_per_call=15):
        while self.tokens_used < self.budget_tokens:
            # Get next batch
            urls = self._get_unclassified_at_depth(current_depth, limit=15)

            # Classify
            result = self._classify_subtree(urls)

            # Track tokens
            self.tokens_used += result['tokens_used']

            # Save checkpoint
            self.session.commit()

            if self.tokens_used >= self.budget_tokens:
                status = "budget_exceeded"
                break
```

**Benefits**:
- Can pause and resume
- No wasted work if interrupted
- Incremental progress
- Cost control

## Generalizability

This approach works for **any website**, not just marxists.org:

```bash
# Crawl any site
grundrisse-ingest crawl-build-graph https://plato.stanford.edu/ \
  --max-depth 5

# Classify with same code
grundrisse-ingest crawl-classify <run_id> --budget-tokens 50000

# LLM will learn the structure from content
# No site-specific heuristics needed!
```

## Performance Characteristics

### Phase 1: Link Graph
- **Time**: O(n) where n = number of pages
- **Cost**: Network latency × page count
- **Parallelizable**: Yes (future enhancement)
- **Resumable**: Yes (checks existing URLs)

### Phase 2: Classification
- **Time**: O(n / batch_size) LLM calls
- **Cost**: Token budget (user-controlled)
- **Parallelizable**: Partially (siblings in parallel)
- **Resumable**: Yes (tracks classification status)

### Example Costs

For 10,000 page site:
- **Phase 1**: ~2-5 hours (0.5s delay between requests), $0
- **Phase 2**: 667 LLM calls @ 15 URLs/call @ ~1500 tokens/call = ~1M tokens
  - @ $0.50/M tokens = **~$0.50 total**
  - Can be split across multiple runs

## Future Enhancements

1. **Parallel fetching**: Bounded concurrency in Phase 1
2. **Strategic sampling**: Sample across depths first, infer structure, then targeted classification
3. **Active learning**: Use high-confidence classifications to skip similar pages
4. **Incremental refresh**: Re-classify only changed pages using ETag
5. **Multi-model**: Use cheap model for obvious pages, expensive model for ambiguous
6. **Human-in-loop**: Flag low-confidence for review

## Comparison to Naive Approach

### Naive Approach (Original Implementation)
```python
# Classify as you crawl
for url in discovered_urls:
    content = fetch(url)
    author, title = extract_metadata_via_heuristics(url)  # WRONG
    # Heuristics fail on non-uniform structures
```

**Problems**:
- Heuristics brittle
- No context from siblings
- No budget control
- Not generalizable

### Progressive Approach (This Implementation)
```python
# Phase 1: Build graph
graph = build_link_graph(seed_url)  # Cheap

# Phase 2: Classify with context
for depth in reversed(range(max_depth)):
    siblings = graph.get_unclassified_at_depth(depth)
    for group in group_by_parent(siblings):
        parent_context = group.parent.classification
        classifications = llm.classify(group, parent_context)  # RIGHT
```

**Benefits**:
- LLM learns structure from content
- Hierarchical context improves accuracy
- Budget-controlled
- Generalizes to any site

## Database Schema

```sql
-- Link graph
ALTER TABLE url_catalog_entry ADD COLUMN parent_url_id UUID REFERENCES url_catalog_entry(url_id);
ALTER TABLE url_catalog_entry ADD COLUMN depth INTEGER DEFAULT 0;
ALTER TABLE url_catalog_entry ADD COLUMN child_count INTEGER DEFAULT 0;

-- Classification
ALTER TABLE url_catalog_entry ADD COLUMN classification_status VARCHAR(32) DEFAULT 'unclassified';
ALTER TABLE url_catalog_entry ADD COLUMN classification_result JSONB;
ALTER TABLE url_catalog_entry ADD COLUMN classification_run_id UUID REFERENCES classification_run(run_id);

CREATE TABLE classification_run (
    run_id UUID PRIMARY KEY,
    crawl_run_id UUID REFERENCES crawl_run(crawl_run_id),
    strategy VARCHAR(64),
    budget_tokens INTEGER,
    tokens_used INTEGER DEFAULT 0,
    urls_classified INTEGER DEFAULT 0,
    status VARCHAR(32) DEFAULT 'running',
    ...
);
```

## Summary

The progressive classification system provides:

✅ **Budget-aware**: Never exceed token budget
✅ **Resumable**: Pause and continue anytime
✅ **Context-aware**: Uses hierarchical structure
✅ **Generalizable**: Works on any website
✅ **Auditable**: Stores all LLM outputs
✅ **Incremental**: Progressive improvement
✅ **Cost-effective**: Only classify what's needed

This is a **production-grade solution** for LLM-powered web classification at scale.
