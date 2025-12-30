from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextWindow:
    context_only_sentences: list[str]
    target_sentences: list[str]


def build_context_window(
    prev_paragraph_sentences: list[str] | None,
    target_paragraph_sentences: list[str],
    *,
    max_context_sentences: int = 2,
) -> ContextWindow:
    """
    Implements the plan’s “anaphora window”:
    - prepend up to N sentences from the previous paragraph as CONTEXT_ONLY
    - outputs must reference only TARGET indices (enforced by llm-contracts validators)
    """
    context: list[str] = []
    if prev_paragraph_sentences:
        context = prev_paragraph_sentences[-max_context_sentences:]
    return ContextWindow(context_only_sentences=context, target_sentences=target_paragraph_sentences)

