"""Windowing system for argument extraction.

Groups paragraphs into overlapping windows for LLM processing.
"""

from grundrisse_argument.windowing.builder import (
    ALL_DISCOURSE_MARKERS,
    DetectedTransition,
    ExtractionWindowInput,
    LocutionInWindow,
    WindowBuilder,
    WindowBuilderConfig,
    get_transition_hint_for_marker,
)

__all__ = [
    "ALL_DISCOURSE_MARKERS",
    "DetectedTransition",
    "ExtractionWindowInput",
    "LocutionInWindow",
    "WindowBuilder",
    "WindowBuilderConfig",
    "get_transition_hint_for_marker",
]
