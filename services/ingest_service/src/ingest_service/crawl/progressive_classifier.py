"""Progressive LLM-powered classification with budget control."""

from __future__ import annotations

import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from grundrisse_core.db.models import ClassificationRun, UrlCatalogEntry


class ProgressiveClassifier:
    """
    Phase 2: LLM-powered progressive classification with budget control.

    Strategies:
    - leaf_to_root: Start at deepest pages, classify upward
    - root_to_leaf: Start at root, classify downward with depth limits
    - strategic_sampling: Sample across depths, infer structure
    """

    PROMPT_VERSION = "v1.0"

    def __init__(
        self,
        session: Session,
        crawl_run_id: uuid.UUID,
        classification_run_id: uuid.UUID,
        llm_client: Any,
        budget_tokens: int,
        model_name: str = "glm-4.7",
    ):
        """
        Initialize progressive classifier.

        Args:
            session: Database session
            crawl_run_id: Crawl run ID
            classification_run_id: Classification run ID
            llm_client: LLM client (with .chat() method)
            budget_tokens: Token budget
            model_name: Model name for provenance
        """
        self.session = session
        self.crawl_run_id = crawl_run_id
        self.classification_run_id = classification_run_id
        self.llm = llm_client
        self.budget_tokens = budget_tokens
        self.tokens_used = 0
        self.model_name = model_name

    def classify_leaf_to_root(
        self,
        max_nodes_per_call: int = 15,
        include_content_samples: bool = True,
    ) -> dict:
        """
        Classify from leaves (content pages) to root (site structure).

        Strategy:
        1. Find deepest unclassified nodes
        2. Group by parent for context
        3. Ask LLM to classify and group
        4. Move up tree using child classifications
        5. Repeat until budget exhausted

        Args:
            max_nodes_per_call: Max URLs to classify per LLM call
            include_content_samples: Whether to include page content in prompts

        Returns:
            Statistics dictionary
        """
        stats = {
            "urls_classified": 0,
            "llm_calls": 0,
            "errors": 0,
        }

        # Get classification run to track progress
        class_run = self.session.get(ClassificationRun, self.classification_run_id)

        # Start at deepest unclassified level
        current_depth = self._get_max_unclassified_depth()

        print(f"🧠 Starting progressive classification (leaf-to-root)", file=sys.stderr)
        print(f"   Strategy: {strategy if 'strategy' in locals() else 'leaf_to_root'}", file=sys.stderr)
        print(f"   Token budget: {self.budget_tokens:,}", file=sys.stderr)
        print(f"   Starting depth: {current_depth}", file=sys.stderr)
        print("", file=sys.stderr)

        while self.tokens_used < self.budget_tokens and current_depth is not None:
            # Adaptive batching strategy based on depth
            # Deep depths (5-4): Use parent grouping (works well, good context)
            # Shallow depths (3-0): Batch across parents (more efficient, less context needed)
            use_parent_grouping = current_depth >= 4

            # Increase batch size for shallow depths to improve efficiency
            effective_batch_size = max_nodes_per_call if use_parent_grouping else max_nodes_per_call * 3

            # Get unclassified URLs at current depth
            urls_to_classify = self._get_unclassified_at_depth(
                depth=current_depth,
                limit=effective_batch_size * 3 if use_parent_grouping else effective_batch_size,
            )

            if not urls_to_classify:
                # Move to shallower depth
                print(f"   Depth {current_depth}: No unclassified URLs, moving up", file=sys.stderr)
                current_depth = self._get_max_unclassified_depth_below(current_depth)
                if current_depth is not None:
                    print(f"   Switching to depth {current_depth}", file=sys.stderr)
                continue

            if use_parent_grouping:
                # Deep depth: Group by parent for better context
                by_parent = self._group_by_parent(urls_to_classify)
                print(f"   Depth {current_depth}: Found {len(urls_to_classify)} URLs in {len(by_parent)} parent groups (parent-grouped)", file=sys.stderr)
                batches = [(parent_id, group[:max_nodes_per_call]) for parent_id, group in by_parent.items()]
            else:
                # Shallow depth: Simple batching across parents for efficiency
                print(f"   Depth {current_depth}: Found {len(urls_to_classify)} URLs (direct batching)", file=sys.stderr)
                batches = []
                for i in range(0, len(urls_to_classify), effective_batch_size):
                    batch = urls_to_classify[i:i + effective_batch_size]
                    # Use None as parent_id since we're batching across parents
                    batches.append((None, batch))

            for parent_id, sibling_group in batches:
                if self.tokens_used >= self.budget_tokens:
                    break

                try:
                    # Build context
                    context = self._build_classification_context(
                        sibling_group,
                        parent_id,
                        include_content_samples=include_content_samples,
                    )

                    # Classify
                    result = self._classify_subtree(context)

                    # Store classifications
                    for url_entry, classification in zip(sibling_group, result["classifications"]):
                        url_entry.classification_result = classification
                        url_entry.classification_status = "classified"
                        url_entry.classification_run_id = self.classification_run_id

                        stats["urls_classified"] += 1

                    self.tokens_used += result.get("tokens_used", 0)
                    stats["llm_calls"] += 1

                    # Update classification run
                    class_run.tokens_used = self.tokens_used
                    class_run.urls_classified = stats["urls_classified"]
                    class_run.current_depth = current_depth

                    self.session.commit()

                    # Progress update
                    print(
                        f"   ✓ Classified {len(sibling_group)} URLs | "
                        f"Total: {stats['urls_classified']} | "
                        f"LLM calls: {stats['llm_calls']} | "
                        f"Tokens: {self.tokens_used:,}/{self.budget_tokens:,} "
                        f"({100*self.tokens_used/self.budget_tokens:.1f}%)",
                        file=sys.stderr,
                    )

                except Exception as e:
                    stats["errors"] += 1
                    # Mark as failed but continue
                    for url_entry in sibling_group:
                        url_entry.classification_status = "failed"
                        url_entry.classification_result = {"error": str(e)}
                    self.session.commit()

        # Mark classification run as completed or budget_exceeded
        if self.tokens_used >= self.budget_tokens:
            class_run.status = "budget_exceeded"
        else:
            class_run.status = "completed"

        class_run.finished_at = datetime.utcnow()
        class_run.tokens_used = self.tokens_used
        self.session.commit()

        print("", file=sys.stderr)
        print(f"✅ Classification {'budget exceeded' if self.tokens_used >= self.budget_tokens else 'complete'}!", file=sys.stderr)
        print(f"   URLs classified: {stats['urls_classified']}", file=sys.stderr)
        print(f"   LLM calls: {stats['llm_calls']}", file=sys.stderr)
        print(f"   Errors: {stats['errors']}", file=sys.stderr)
        print(f"   Tokens used: {self.tokens_used:,} / {self.budget_tokens:,} ({100*self.tokens_used/self.budget_tokens:.1f}%)", file=sys.stderr)
        if self.tokens_used >= self.budget_tokens:
            print(f"   ⚠️  Budget exceeded - run again with more tokens to continue", file=sys.stderr)
        print("", file=sys.stderr)

        return stats

    def _build_classification_context(
        self,
        urls: list[UrlCatalogEntry],
        parent_id: uuid.UUID | None,
        include_content_samples: bool = True,
    ) -> dict:
        """Build context for LLM including parent, siblings, and content."""

        # Get parent context
        parent_context = None
        if parent_id:
            parent = self.session.get(UrlCatalogEntry, parent_id)
            if parent and parent.classification_result:
                parent_context = {
                    "url": parent.url_canonical,
                    "depth": parent.depth,
                    "classification": parent.classification_result,
                }

        # Build URL info
        url_info = []
        for entry in urls:
            info = {
                "url": entry.url_canonical,
                "depth": entry.depth,
                "child_count": entry.child_count,
            }

            if include_content_samples and entry.raw_path:
                try:
                    # Extract key content
                    html = Path(entry.raw_path).read_text(encoding="utf-8", errors="ignore")
                    soup = BeautifulSoup(html, "lxml")

                    info["title"] = soup.find("title").get_text(strip=True) if soup.find("title") else None
                    info["h1"] = soup.find("h1").get_text(strip=True) if soup.find("h1") else None

                    # Get first few paragraphs
                    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")[:3]]
                    info["content_sample"] = " ".join(paragraphs)[:800]

                except Exception:
                    info["content_sample"] = None

            url_info.append(info)

        return {
            "parent": parent_context,
            "urls": url_info,
        }

    def _classify_subtree(self, context: dict) -> dict:
        """Call LLM to classify a subtree."""

        parent_info = context.get("parent")
        parent_desc = json.dumps(parent_info, indent=2) if parent_info else "None (root level)"

        urls_desc = json.dumps(context["urls"], indent=2)

        prompt = f"""You are analyzing a website's structure to classify pages and identify works/authors.

PARENT CONTEXT:
{parent_desc}

PAGES TO CLASSIFY (siblings in the link tree):
{urls_desc}

For each page, classify it with:
1. page_type: One of:
   - "work_page" (actual work content - chapters, sections)
   - "work_toc" (table of contents for a work)
   - "work_index" (index page listing multiple works)
   - "author_index" (page about an author with their works)
   - "author_bio" (biographical information)
   - "study_guide" (study materials, guides)
   - "navigation" (site navigation, breadcrumbs)
   - "apparatus" (licenses, about pages, metadata)
   - "other"

2. author: Canonical author name (if identifiable, else null)
3. work_title: Work title if this is part of a work (else null)
4. language: ISO 639-1 language code (en, es, fr, de, etc.)
5. is_primary_content: true if this is main work content vs. apparatus
6. confidence: 0.0-1.0 confidence score

Also identify GROUPS of related pages (e.g., chapters of the same work):
- Group pages that belong to the same work
- Provide group_type, work_title, author, and member URLs

Respond ONLY with valid JSON (no markdown, no explanations):
{{
  "classifications": [
    {{
      "url": "...",
      "page_type": "...",
      "author": "..." or null,
      "work_title": "..." or null,
      "language": "en",
      "is_primary_content": true or false,
      "confidence": 0.95
    }}
  ],
  "groups": [
    {{
      "group_type": "work",
      "work_title": "...",
      "author": "...",
      "language": "en",
      "member_urls": ["...", "..."]
    }}
  ]
}}"""

        # Define JSON schema for response
        schema = {
            "type": "object",
            "properties": {
                "classifications": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "page_type": {"type": "string"},
                            "author": {"type": ["string", "null"]},
                            "work_title": {"type": ["string", "null"]},
                            "language": {"type": "string"},
                            "is_primary_content": {"type": "boolean"},
                            "confidence": {"type": "number"},
                        },
                        "required": ["url", "page_type", "language", "is_primary_content", "confidence"],
                    },
                },
                "groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "group_type": {"type": "string"},
                            "work_title": {"type": "string"},
                            "author": {"type": "string"},
                            "language": {"type": "string"},
                            "member_urls": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
            "required": ["classifications", "groups"],
        }

        # Call LLM
        try:
            response = self.llm.complete_json(prompt=prompt, schema=schema)

            # Extract JSON from LLMResponse
            parsed = response.json

            # If JSON parsing failed, try to extract from raw text
            if not parsed:
                response_text = response.raw_text or ""
                # Remove markdown code blocks if present
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()
                parsed = json.loads(response_text)

            # Count tokens
            tokens_used = (response.prompt_tokens or 0) + (response.completion_tokens or 0)

            return {
                "classifications": parsed.get("classifications", []),
                "groups": parsed.get("groups", []),
                "tokens_used": tokens_used,
            }

        except Exception as e:
            # Return error classifications
            # NOTE: context["urls"] is a list of dicts, not UrlCatalogEntry objects
            return {
                "classifications": [
                    {
                        "url": url_data.get("url", "unknown"),
                        "page_type": "other",
                        "author": None,
                        "work_title": None,
                        "language": "unknown",
                        "is_primary_content": False,
                        "confidence": 0.0,
                        "error": str(e),
                    }
                    for url_data in context["urls"]
                ],
                "groups": [],
                "tokens_used": len(prompt) // 4,  # Approximate
            }

    def _get_max_unclassified_depth(self) -> int | None:
        """Get the deepest depth with unclassified URLs."""
        result = self.session.execute(
            select(func.max(UrlCatalogEntry.depth))
            .where(UrlCatalogEntry.crawl_run_id == self.crawl_run_id)
            .where(UrlCatalogEntry.classification_status == "unclassified")
        ).scalar()

        return result

    def _get_max_unclassified_depth_below(self, depth: int) -> int | None:
        """Get maximum unclassified depth below given depth."""
        result = self.session.execute(
            select(func.max(UrlCatalogEntry.depth))
            .where(UrlCatalogEntry.crawl_run_id == self.crawl_run_id)
            .where(UrlCatalogEntry.classification_status == "unclassified")
            .where(UrlCatalogEntry.depth < depth)
        ).scalar()

        return result

    def _get_unclassified_at_depth(self, depth: int, limit: int) -> list[UrlCatalogEntry]:
        """Get unclassified URLs at specific depth."""
        return (
            self.session.execute(
                select(UrlCatalogEntry)
                .where(UrlCatalogEntry.crawl_run_id == self.crawl_run_id)
                .where(UrlCatalogEntry.depth == depth)
                .where(UrlCatalogEntry.classification_status == "unclassified")
                .where(UrlCatalogEntry.status == "fetched")  # Only classify fetched pages
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def _group_by_parent(self, urls: list[UrlCatalogEntry]) -> dict[uuid.UUID | None, list[UrlCatalogEntry]]:
        """Group URLs by parent for context-aware classification."""
        by_parent = defaultdict(list)

        for url in urls:
            by_parent[url.parent_url_id].append(url)

        return dict(by_parent)
