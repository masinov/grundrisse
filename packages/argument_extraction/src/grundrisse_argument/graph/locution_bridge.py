"""Locution Bridge Layer - bridges existing Paragraph/SentenceSpan to argument graph.

Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §3.2 and Appendix A:

This module provides factory functions to convert existing text units (Paragraph,
SentenceSpan) into ArgumentLocution nodes (L-nodes) for the AIF/IAT argument graph.

Key design (§4.1: DOM-aware ingestion):
- Deterministic loc_id using UUID v5 (stable across runs)
- One-to-one mapping: each Paragraph/SentenceSpan gets exactly one Locution
- Text content is verbatim, immutable (audit trail)
- section_path preserves DOM structure for navigation
- Footnotes are tracked separately (often polemical/definitional)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from grundrisse_core.db.models import (
    ArgumentLocution,
    ArgumentExtractionRun,
    Paragraph,
    SentenceSpan,
    TextBlock,
)
from grundrisse_core.identity import stable_uuid


# Namespace for deterministic locution IDs
NAMESPACE_LOCUTION = uuid.UUID("a1b2c3d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d")


def _build_section_path(para: Paragraph, session: Session | None = None) -> list[str]:
    """
    Build section path from paragraph's text block hierarchy.

    Per §4.1: DOM-aware ingestion - preserve paragraph boundaries
    and structural context.
    """
    path = []

    if session is None:
        # If no session, return empty path (can be populated later)
        return path

    # Walk up the TextBlock hierarchy
    if para.block_id:
        block = session.get(TextBlock, para.block_id)
        while block:
            if block.title:
                path.insert(0, block.title)
            if block.parent_block_id:
                block = session.get(TextBlock, block.parent_block_id)
            else:
                break

    return path


def _check_is_footnote(para: Paragraph, session: Session | None = None) -> bool:
    """
    Check if paragraph is a footnote.

    Per §4.1: Footnotes are often polemical or definitional and must
    remain accessible as independent locutions.
    """
    if session and para.block_id:
        block = session.get(TextBlock, para.block_id)
        if block and block.block_subtype:
            from grundrisse_core.db.enums import BlockSubtype
            return block.block_subtype == BlockSubtype.footnote
    return False


def locution_id_for_paragraph(*, edition_id: uuid.UUID, paragraph_id: uuid.UUID) -> uuid.UUID:
    """Generate deterministic loc_id for a paragraph."""
    return stable_uuid(NAMESPACE_LOCUTION, f"paragraph:{edition_id}:{paragraph_id}")


def locution_id_for_sentence_span(*, edition_id: uuid.UUID, span_id: uuid.UUID) -> uuid.UUID:
    """Generate deterministic loc_id for a sentence span."""
    return stable_uuid(NAMESPACE_LOCUTION, f"sentence_span:{edition_id}:{span_id}")


def paragraph_to_locution(
    para: Paragraph,
    created_run_id: uuid.UUID,
    session: Session | None = None,
) -> ArgumentLocution:
    """Convert a Paragraph to an ArgumentLocution.

    Per Appendix A schema:
    - loc_id: deterministic UUID
    - text: verbatim text (immutable)
    - section_path: DOM structural context
    - is_footnote: for polemical/definitional content tracking

    Creates or retrieves a locution that bridges the paragraph to the argument graph.
    Uses deterministic UUID for stable identity across runs.

    Args:
        para: The Paragraph to convert
        created_run_id: The argument extraction run ID
        session: Optional DB session (for checking existing and building section_path)

    Returns:
        ArgumentLocution with verbatim text and structural context
    """
    loc_id = locution_id_for_paragraph(
        edition_id=para.edition_id,
        paragraph_id=para.para_id,
    )

    # Check if already exists
    if session is not None:
        existing = session.get(ArgumentLocution, loc_id)
        if existing is not None:
            return existing

    # Build section path (requires session)
    section_path = _build_section_path(para, session)
    is_footnote = _check_is_footnote(para, session)

    # Create new locution per Appendix A schema
    return ArgumentLocution(
        loc_id=loc_id,
        edition_id=para.edition_id,
        paragraph_id=para.para_id,
        sentence_span_id=None,
        text=para.text_normalized,  # Verbatim text (renamed from text_content)
        start_char=para.start_char,
        end_char=para.end_char,
        section_path=section_path,  # DOM structural context
        is_footnote=is_footnote,
        footnote_links=[],  # Can be populated later
        created_run_id=created_run_id,
    )


def span_to_locution(
    span: SentenceSpan,
    created_run_id: uuid.UUID,
    session: Session | None = None,
) -> ArgumentLocution:
    """Convert a SentenceSpan to an ArgumentLocution.

    Creates or retrieves a locution that bridges the sentence span to the argument graph.
    Uses deterministic UUID for stable identity across runs.

    Args:
        span: The SentenceSpan to convert
        created_run_id: The argument extraction run ID
        session: Optional DB session (for checking existing and building section_path)

    Returns:
        ArgumentLocution with verbatim text and structural context
    """
    loc_id = locution_id_for_sentence_span(
        edition_id=span.edition_id,
        span_id=span.span_id,
    )

    # Check if already exists
    if session is not None:
        existing = session.get(ArgumentLocution, loc_id)
        if existing is not None:
            return existing

    # Build section path from parent paragraph
    section_path = []
    is_footnote = False

    if session is not None and span.para_id:
        para = session.get(Paragraph, span.para_id)
        if para:
            section_path = _build_section_path(para, session)
            is_footnote = _check_is_footnote(para, session)

    # Create new locution per Appendix A schema
    return ArgumentLocution(
        loc_id=loc_id,
        edition_id=span.edition_id,
        paragraph_id=None,
        sentence_span_id=span.span_id,
        text=span.text,  # Verbatim text (renamed from text_content)
        start_char=span.start_char,
        end_char=span.end_char,
        section_path=section_path,
        is_footnote=is_footnote,
        footnote_links=[],
        created_run_id=created_run_id,
    )


def create_extraction_run(
    session: Session,
    pipeline_version: str = "0.1.0",
    model_name: str = "glm-4.7",
    prompt_name: str = "argument_extraction_c1",
    prompt_version: str = "0.1.0",
    params: dict | None = None,
) -> ArgumentExtractionRun:
    """Create a new ArgumentExtractionRun.

    Args:
        session: Database session
        pipeline_version: Pipeline version string
        model_name: LLM model name
        prompt_name: Prompt schema name
        prompt_version: Prompt version string
        params: Optional additional parameters

    Returns:
        New ArgumentExtractionRun (not yet committed)
    """
    if params is None:
        params = {}

    run = ArgumentExtractionRun(
        pipeline_version=pipeline_version,
        model_name=model_name,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        params=params,
        started_at=datetime.utcnow(),
    )
    session.add(run)
    session.flush()

    return run


def backfill_paragraph_locutions(
    session: Session,
    created_run_id: uuid.UUID,
    edition_id: uuid.UUID | None = None,
    batch_size: int = 1000,
    progress_every: int = 10000,
) -> dict:
    """Backfill locutions from existing paragraphs.

    Creates ArgumentLocution records for all paragraphs that don't have one yet.
    Uses deterministic UUIDs for idempotency.

    Args:
        session: Database session
        created_run_id: The argument extraction run ID
        edition_id: Optional edition ID to filter (if None, processes all)
        batch_size: Number of locutions to flush per batch
        progress_every: Print progress every N paragraphs

    Returns:
        Dict with stats: created, skipped, errors
    """
    stats = {"created": 0, "skipped": 0, "errors": 0}

    # Query paragraphs
    query = session.query(Paragraph)
    if edition_id is not None:
        query = query.filter(Paragraph.edition_id == edition_id)
    query = query.order_by(Paragraph.edition_id, Paragraph.para_id)

    total = query.count()
    print(f"Backfilling locutions for {total} paragraphs...")

    batch = []
    for i, para in enumerate(query):
        try:
            loc_id = locution_id_for_paragraph(
                edition_id=para.edition_id,
                paragraph_id=para.para_id,
            )

            # Check if exists
            existing = session.get(ArgumentLocution, loc_id)
            if existing is not None:
                stats["skipped"] += 1
                continue

            # Build structural context
            section_path = _build_section_path(para, session)
            is_footnote = _check_is_footnote(para, session)

            # Create new locution per Appendix A schema
            locution = ArgumentLocution(
                loc_id=loc_id,
                edition_id=para.edition_id,
                paragraph_id=para.para_id,
                sentence_span_id=None,
                text=para.text_normalized,  # Changed from text_content
                start_char=para.start_char,
                end_char=para.end_char,
                section_path=section_path,
                is_footnote=is_footnote,
                footnote_links=[],
                created_run_id=created_run_id,
            )
            batch.append(locution)
            stats["created"] += 1

            # Flush batch
            if len(batch) >= batch_size:
                session.add_all(batch)
                session.flush()
                batch = []

            # Progress
            if (i + 1) % progress_every == 0:
                print(f"  {i + 1}/{total}... (created: {stats['created']}, skipped: {stats['skipped']})")

        except Exception as e:
            stats["errors"] += 1
            print(f"Error processing paragraph {para.para_id}: {e}")

    # Flush remaining
    if batch:
        session.add_all(batch)
        session.flush()

    print(f"Done. Created: {stats['created']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")
    return stats


def backfill_span_locutions(
    session: Session,
    created_run_id: uuid.UUID,
    edition_id: uuid.UUID | None = None,
    batch_size: int = 1000,
    progress_every: int = 10000,
) -> dict:
    """Backfill locutions from existing sentence spans.

    Creates ArgumentLocution records for all sentence spans that don't have one yet.
    Uses deterministic UUIDs for idempotency.

    Args:
        session: Database session
        created_run_id: The argument extraction run ID
        edition_id: Optional edition ID to filter (if None, processes all)
        batch_size: Number of locutions to flush per batch
        progress_every: Print progress every N spans

    Returns:
        Dict with stats: created, skipped, errors
    """
    stats = {"created": 0, "skipped": 0, "errors": 0}

    # Query sentence spans
    query = session.query(SentenceSpan)
    if edition_id is not None:
        query = query.filter(SentenceSpan.edition_id == edition_id)
    query = query.order_by(SentenceSpan.edition_id, SentenceSpan.span_id)

    total = query.count()
    print(f"Backfilling locutions for {total} sentence spans...")

    batch = []
    for i, span in enumerate(query):
        try:
            loc_id = locution_id_for_sentence_span(
                edition_id=span.edition_id,
                span_id=span.span_id,
            )

            # Check if exists
            existing = session.get(ArgumentLocution, loc_id)
            if existing is not None:
                stats["skipped"] += 1
                continue

            # Build structural context from parent paragraph
            section_path = []
            is_footnote = False
            if span.para_id:
                para = session.get(Paragraph, span.para_id)
                if para:
                    section_path = _build_section_path(para, session)
                    is_footnote = _check_is_footnote(para, session)

            # Create new locution per Appendix A schema
            locution = ArgumentLocution(
                loc_id=loc_id,
                edition_id=span.edition_id,
                paragraph_id=None,
                sentence_span_id=span.span_id,
                text=span.text,  # Changed from text_content
                start_char=span.start_char,
                end_char=span.end_char,
                section_path=section_path,
                is_footnote=is_footnote,
                footnote_links=[],
                created_run_id=created_run_id,
            )
            batch.append(locution)
            stats["created"] += 1

            # Flush batch
            if len(batch) >= batch_size:
                session.add_all(batch)
                session.flush()
                batch = []

            # Progress
            if (i + 1) % progress_every == 0:
                print(f"  {i + 1}/{total}... (created: {stats['created']}, skipped: {stats['skipped']})")

        except Exception as e:
            stats["errors"] += 1
            print(f"Error processing span {span.span_id}: {e}")

    # Flush remaining
    if batch:
        session.add_all(batch)
        session.flush()

    print(f"Done. Created: {stats['created']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")
    return stats


def get_locution_for_paragraph(
    session: Session,
    paragraph_id: uuid.UUID,
) -> ArgumentLocution | None:
    """Get the locution for a paragraph, if it exists."""
    return session.query(ArgumentLocution).filter(
        ArgumentLocution.paragraph_id == paragraph_id
    ).first()


def get_locution_for_span(
    session: Session,
    span_id: uuid.UUID,
) -> ArgumentLocution | None:
    """Get the locution for a sentence span, if it exists."""
    return session.query(ArgumentLocution).filter(
        ArgumentLocution.sentence_span_id == span_id
    ).first()


def get_locutions_by_edition(
    session: Session,
    edition_id: uuid.UUID,
    order: str = "paragraph",
) -> list[ArgumentLocution]:
    """Get all locutions for an edition, ordered by text position.

    Args:
        session: Database session
        edition_id: Edition to query
        order: "paragraph" for paragraph-level locutions, "span" for sentence-level

    Returns:
        List of ArgumentLocution ordered by position
    """
    query = session.query(ArgumentLocution).filter(
        ArgumentLocution.edition_id == edition_id
    )

    if order == "paragraph":
        query = query.filter(ArgumentLocution.paragraph_id != None)
        query = query.join(Paragraph, ArgumentLocution.paragraph_id == Paragraph.para_id)
        query = query.order_by(Paragraph.order_index)
    elif order == "span":
        query = query.filter(ArgumentLocution.sentence_span_id != None)
        query = query.join(SentenceSpan, ArgumentLocution.sentence_span_id == SentenceSpan.span_id)
        query = query.order_by(SentenceSpan.para_index, SentenceSpan.sent_index)
    else:
        query = query.order_by(ArgumentLocution.loc_id)

    return list(query.all())
