"""LLM-powered author name deduplication."""

from __future__ import annotations

import json
from typing import Any


class LLMAuthorDeduplicator:
    """Use LLM to deduplicate author names."""

    NAMING_CONVENTION = """
# Author Naming Convention

1. **Full given name + surname** (prefer full names over initials)
   - ✓ "Vladimir Lenin" (not "V. I. Lenin" or "Lenin")

2. **Use commonly known form** (not always legal name)
   - ✓ "Joseph Stalin" (not "Joseph Vissarionovich Dzhugashvili")
   - ✓ "Mao Zedong" (modern pinyin, not "Mao Tse-tung")

3. **Initials only when commonly known that way**
   - ✓ "C.L.R. James" (always known by initials, no spaces)
   - ✗ "V. I. Lenin" → use "Vladimir Lenin"

4. **Western name order** (given name + surname)

5. **Standard romanization** for non-Latin scripts
   - Modern pinyin for Chinese: "Mao Zedong" not "Mao Tse-tung"
"""

    EXAMPLES = """
Examples:
- ["Vladimir Lenin", "V. I. Lenin", "V.I. Lenin", "Lenin"] → "Vladimir Lenin"
- ["Joseph Stalin", "J. V. Stalin"] → "Joseph Stalin"
- ["Friedrich Engels", "Frederick Engels"] → "Friedrich Engels"
- ["Mao Tse-tung", "Mao Zedong"] → "Mao Zedong"
- ["C.L.R. James", "C. L. R. James"] → "C.L.R. James"
"""

    def __init__(self, llm_client: Any):
        """
        Initialize deduplicator.

        Args:
            llm_client: LLM client (with complete_json method)
        """
        self.llm = llm_client

    def pick_canonical_name(self, variants: list[str]) -> str:
        """
        Use LLM to pick the canonical form from variants.

        Args:
            variants: List of name variants (e.g., ["Lenin", "V. I. Lenin", "Vladimir Lenin"])

        Returns:
            Canonical name according to convention
        """
        if len(variants) == 1:
            return variants[0]

        prompt = f"""You are standardizing author names for a Marxist text archive.

{self.NAMING_CONVENTION}

{self.EXAMPLES}

Given these variants of the same author, pick the canonical form according to the convention:

Variants: {json.dumps(variants, ensure_ascii=False)}

Respond with ONLY valid JSON (no markdown, no explanations):
{{
  "canonical_name": "...",
  "reason": "Brief explanation of why this form is canonical"
}}
"""

        schema = {
            "type": "object",
            "properties": {
                "canonical_name": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["canonical_name", "reason"],
        }

        try:
            response = self.llm.complete_json(prompt=prompt, schema=schema)
            result = response.json

            if not result:
                # Fallback: pick longest name (usually most complete)
                return max(variants, key=len)

            canonical = result.get("canonical_name")
            reason = result.get("reason", "")

            # Validate that canonical is one of the variants or close to them
            if canonical not in variants:
                # LLM might have corrected a name - that's ok
                pass

            return canonical

        except Exception as e:
            # Fallback: pick longest name
            return max(variants, key=len)

    def deduplicate_batch(
        self,
        author_clusters: list[list[str]],
        *,
        show_progress: bool = True,
    ) -> dict[str, str]:
        """
        Deduplicate a batch of author name clusters.

        Args:
            author_clusters: List of clusters, each cluster is a list of variants
            show_progress: Show progress messages

        Returns:
            Dictionary mapping variant names to canonical names
        """
        mappings = {}

        for i, variants in enumerate(author_clusters):
            if show_progress and (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{len(author_clusters)} clusters...")

            canonical = self.pick_canonical_name(variants)

            # Map all variants to canonical
            for variant in variants:
                if variant != canonical:
                    mappings[variant] = canonical

        return mappings
