"""Windowing system for argument extraction.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §5.1-5.4:

Groups paragraphs into overlapping windows for LLM processing with discourse
marker detection and context assembly.

Windows: 2-6 paragraphs with 1-2 paragraph overlap (§5.1).
Retrieval: Hybrid retrieval with vector similarity, concept overlap, entity alignment (§5.2).
Mandatory retrieval: Triggered by conclusion markers without local premises (§5.3).
Context presentation: Explicit marking, read-only constraint, non-extractible (§5.4).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import List, Optional, Literal

from pydantic import BaseModel, Field

from grundrisse_core.db.models import Paragraph, ArgumentLocution


# Per Appendix A: 4 transition hints (contrast, inference, concession, continuation)
TransitionHint = Literal["contrast", "inference", "concession", "continuation"]

# Discourse marker patterns for transition detection (per §3.3)
DISCOURSE_MARKERS: dict[TransitionHint, List[str]] = {
    "contrast": [
        "however", "but", "nevertheless", "yet", "still", "conversely",
        "on the other hand", "in contrast", "rather", "instead",
        "on the contrary", "by contrast", "notwithstanding",
    ],
    "inference": [
        "therefore", "thus", "hence", "consequently", "accordingly",
        "as a result", "for this reason", "it follows that", "so",
        "then", "in consequence", "whence", "wherefore",
    ],
    "concession": [
        "although", "though", "even though", "while", "granted that",
        "admittedly", "it is true that", "even if", "notwithstanding",
    ],
    "continuation": [
        "moreover", "furthermore", "additionally", "also", "besides",
        "what is more", "in addition", "likewise", "similarly",
        "in the same way", "further", "again",
    ],
}


@dataclass
class DetectedTransition:
    """A discourse transition detected between locutions."""
    marker: str
    hint: TransitionHint
    position: int  # Character position in text
    from_loc_id: Optional[str] = None
    to_loc_id: Optional[str] = None


@dataclass
class LocutionInWindow:
    """A locution as it appears in a window, with context."""
    loc_id: str
    text: str
    paragraph_id: uuid.UUID
    order_index: int
    is_target: bool  # True if this is a target paragraph (not just context)


class ExtractionWindowInput(BaseModel):
    """
    Input to LLM for extraction from a window.

    Per §5.4: Retrieved context presentation (CRITICAL):
    Retrieved material is presented as:
    --- LOCAL WINDOW (extractable) ---
    [Paragraph 1] ... [Paragraph N]
    --- RETRIEVED CONTEXT (read-only, non-extractible) ---
    [1] prop_1234: "Labor is the source..." (from Smith, Wealth of Nations, 1776)

    To prevent context poisoning:
    - Explicit marking with [RETRIEVED_CONTEXT]
    - Read-only constraint: cannot generate new locutions
    - Relations may cite retrieved props as premises, but retrieved text
      cannot serve as evidence locutions
    """

    window_id: str = Field(..., description="Unique window identifier")
    edition_id: str = Field(..., description="Source edition identifier")
    doc_id: str = Field(..., description="Document/work identifier")

    # Paragraphs in this window
    paragraph_ids: List[str] = Field(..., description="Paragraph IDs in window")
    texts: List[str] = Field(..., description="Paragraph texts in order")

    # Detected discourse transitions
    transitions: List[dict] = Field(
        default_factory=list,
        description="Detected discourse transitions between paragraphs"
    )

    # Retrieved context (per §5.4: read-only, non-extractible)
    retrieved_context: List[dict] = Field(
        default_factory=list,
        description="Previously extracted propositions (READ-ONLY, non-extractible)"
    )

    # Metadata
    window_index: int = Field(..., description="Sequential index of this window")
    total_windows: int = Field(..., description="Total windows in document")
    has_overlap_start: bool = Field(default=False, description="Window starts with overlap context")
    has_overlap_end: bool = Field(default=False, description="Window ends with overlap context")


class WindowBuilderConfig(BaseModel):
    """Configuration for window building per §5.1."""

    min_paragraphs: int = Field(default=2, ge=1, le=10)
    max_paragraphs: int = Field(default=6, ge=1, le=20)
    overlap: int = Field(default=1, ge=0, le=5)
    prefer_break_at_transitions: bool = Field(default=True)

    class Config:
        frozen = True


class WindowBuilder:
    """
    Builds overlapping windows of paragraphs for LLM processing.

    Per §5.1-5.4:
    - Windows: 2-6 paragraphs with 1-2 paragraph overlap
    - Transition-aware: prefer breaking at discourse boundaries
    - Context-aware: include previous/next for overlap
    - Retrieved context: structurally separated, read-only (§5.4)
    """

    def __init__(self, config: WindowBuilderConfig | None = None):
        self.config = config or WindowBuilderConfig()
        self._marker_patterns = self._compile_marker_patterns()

    def _compile_marker_patterns(self) -> dict[TransitionHint, re.Pattern]:
        """Compile regex patterns for discourse markers."""
        patterns = {}
        for hint, markers in DISCOURSE_MARKERS.items():
            # Match word boundaries, case-insensitive
            pattern = r"\b(" + "|".join(re.escape(m) for m in markers) + r")\b"
            patterns[hint] = re.compile(pattern, re.IGNORECASE)
        return patterns

    def detect_transitions(
        self,
        text: str,
    ) -> List[DetectedTransition]:
        """
        Detect discourse transition markers in text.

        Args:
            text: Text to analyze

        Returns:
            List of detected transitions
        """
        transitions = []

        for hint, pattern in self._marker_patterns.items():
            for match in pattern.finditer(text):
                transitions.append(DetectedTransition(
                    marker=match.group(1),
                    hint=hint,
                    position=match.start(),
                ))

        # Sort by position
        transitions.sort(key=lambda t: t.position)
        return transitions

    def build_windows(
        self,
        paragraphs: List[Paragraph],
        edition_id: uuid.UUID,
        doc_id: str,
    ) -> List[ExtractionWindowInput]:
        """
        Build extraction windows from paragraphs.

        Args:
            paragraphs: Ordered list of paragraphs (must be pre-sorted by order_index)
            edition_id: Edition ID
            doc_id: Document/work identifier

        Returns:
            List of extraction windows
        """
        if not paragraphs:
            return []

        windows = []
        window_index = 0

        # Build windows from segments
        for i in range(0, len(paragraphs), self.config.max_paragraphs - self.config.overlap):
            # Get window paragraphs
            end_idx = min(i + self.config.max_paragraphs, len(paragraphs))

            window_paras = paragraphs[i:end_idx]

            # Check minimum size
            if len(window_paras) < self.config.min_paragraphs:
                # Merge with previous window if too small (and not first)
                if windows and len(window_paras) > 0:
                    # Extend previous window
                    prev_window = windows[-1]
                    prev_window.paragraph_ids.extend(str(p.para_id) for p in window_paras)
                    prev_window.texts.extend(p.text_normalized for p in window_paras)
                    continue
                elif i > 0:
                    # Skip if too small and not first
                    continue

            # Create window
            window = self._create_window(
                window_paras=window_paras,
                edition_id=edition_id,
                doc_id=doc_id,
                window_index=window_index,
                total_windows=len(paragraphs) // (self.config.max_paragraphs - self.config.overlap) + 1,
                has_overlap_start=(i > 0),
                has_overlap_end=(end_idx < len(paragraphs)),
            )

            windows.append(window)
            window_index += 1

        return windows

    def _create_window(
        self,
        window_paras: List[Paragraph],
        edition_id: uuid.UUID,
        doc_id: str,
        window_index: int,
        total_windows: int,
        has_overlap_start: bool,
        has_overlap_end: bool,
    ) -> ExtractionWindowInput:
        """Create an ExtractionWindowInput from paragraphs."""
        # Detect transitions between paragraphs
        transitions = []
        for i, para in enumerate(window_paras):
            para_transitions = self.detect_transitions(para.text_normalized)
            for t in para_transitions:
                transitions.append({
                    "marker": t.marker,
                    "function_hint": t.hint,  # Per Appendix A: function_hint (not hint)
                    "paragraph_index": i,
                    "position": t.position,
                })

        return ExtractionWindowInput(
            window_id=str(uuid.uuid4()),
            edition_id=str(edition_id),
            doc_id=doc_id,
            paragraph_ids=[str(p.para_id) for p in window_paras],
            texts=[p.text_normalized for p in window_paras],
            transitions=transitions,
            window_index=window_index,
            total_windows=total_windows,
            has_overlap_start=has_overlap_start,
            has_overlap_end=has_overlap_end,
        )

    def build_windows_from_locutions(
        self,
        locutions: List[ArgumentLocution],
        edition_id: uuid.UUID,
        doc_id: str,
    ) -> List[ExtractionWindowInput]:
        """
        Build extraction windows from locutions.

        This is the main entry point when locutions are already backfilled.

        Args:
            locutions: Ordered list of locutions
            edition_id: Edition ID
            doc_id: Document/work identifier

        Returns:
            List of extraction windows
        """
        # Group locutions by paragraph and sort
        para_locutions: dict[uuid.UUID, List[ArgumentLocution]] = {}
        for loc in locutions:
            if loc.paragraph_id:
                if loc.paragraph_id not in para_locutions:
                    para_locutions[loc.paragraph_id] = []
                para_locutions[loc.paragraph_id].append(loc)

        # Get unique paragraphs in order
        from sqlalchemy.orm import Session
        from grundrisse_core.db.session import SessionLocal

        with SessionLocal() as session:
            paragraph_ids = list(para_locutions.keys())
            paragraphs = (
                session.query(Paragraph)
                .filter(Paragraph.para_id.in_(paragraph_ids))
                .order_by(Paragraph.order_index)
                .all()
            )

        return self.build_windows(paragraphs, edition_id, doc_id)


def get_transition_hint_for_marker(marker: str) -> TransitionHint | None:
    """
    Get the transition hint for a specific discourse marker.

    Args:
        marker: The discourse marker text

    Returns:
        TransitionHint if found, None otherwise
    """
    marker_lower = marker.lower().strip()

    for hint, markers in DISCOURSE_MARKERS.items():
        if marker_lower in markers:
            return hint

    return None


# Export marker list for use in prompts
ALL_DISCOURSE_MARKERS = [
    marker for markers in DISCOURSE_MARKERS.values() for marker in markers
]
