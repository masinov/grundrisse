from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import typer

from grundrisse_core.hashing import sha256_text
from grundrisse_core.identity import author_id_for, edition_id_for, work_id_for
from grundrisse_core.settings import settings as core_settings

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.enums import BlockSubtype, TextBlockType, WorkType
from grundrisse_core.db.models import Author, Edition, IngestRun, Paragraph, SentenceSpan, TextBlock, Work
from ingest_service.crawl.discover import discover_work_urls
from ingest_service.fetch.snapshot import snapshot_url
from ingest_service.parse.html_to_blocks import parse_html_to_blocks
from ingest_service.segment.sentences import split_paragraph_into_sentences
from ingest_service.settings import settings as ingest_settings

app = typer.Typer(help="Ingest service (snapshot, parse, segment).")


@app.command()
def fetch(url: str) -> None:
    """
    Fetch and store an immutable raw HTML snapshot under `data/raw/`.

    Note: requires network access at runtime.
    """
    snap = snapshot_url(url)
    typer.echo(f"stored: {snap.raw_path}")
    typer.echo(f"meta:   {snap.meta_path}")


@app.command()
def ingest(
    url: str,
    *,
    language: str = typer.Option("en", help="Edition language code (e.g., en, es, de)."),
    author: str = typer.Option("Unknown", help="Canonical author name (override)."),
    title: str | None = typer.Option(None, help="Work title (override). If omitted, inferred from headings."),
) -> None:
    """
    Day-1 vertical-slice ingestion for a single marxists.org page:
    - snapshot raw HTML to `data/raw/`
    - parse into blocks/paragraphs
    - sentence-split into SentenceSpans
    - persist to Postgres

    Note: requires network access at runtime.
    """
    _ = core_settings.database_url  # ensure env is loaded
    snap = snapshot_url(url)
    html = snap.content.decode("utf-8", errors="replace")
    parsed_blocks = parse_html_to_blocks(html)

    inferred_title = next((b.title for b in parsed_blocks if b.title), None)
    work_title = title or inferred_title or url

    author_id = author_id_for(author)
    work_id = work_id_for(author_id=author_id, title=work_title)
    edition_id = edition_id_for(work_id=work_id, language=language, source_url=url)

    with SessionLocal() as session:
        started = datetime.utcnow()

        _upsert_author(session, author_id=author_id, name_canonical=author)
        _upsert_work(session, work_id=work_id, author_id=author_id, title=work_title)

        ingest_run = IngestRun(
            ingest_run_id=uuid.uuid4(),
            pipeline_version="v0",
            git_commit_hash=None,
            source_url=url,
            raw_object_key=str(snap.raw_path),
            raw_checksum=snap.sha256,
            started_at=started,
            finished_at=None,
            status="started",
            error_log=None,
        )
        session.add(ingest_run)

        edition = session.get(Edition, edition_id)
        if edition is None:
            edition = Edition(
                edition_id=edition_id,
                work_id=work_id,
                language=language,
                translator_editor=None,
                publication_year=None,
                source_url=url,
                ingest_run_id=ingest_run.ingest_run_id,
            )
            session.add(edition)
        else:
            edition.ingest_run_id = ingest_run.ingest_run_id

        session.flush()

        span_sequence: list[SentenceSpan] = []
        global_para_order = 0
        for b in parsed_blocks:
            block_id = uuid.uuid4()
            block_type = _map_block_type(b.block_type)
            block_subtype = _map_block_subtype(b.block_subtype)

            author_override_id = None
            if b.author_override_name:
                author_override_id = author_id_for(b.author_override_name)
                _upsert_author(session, author_id=author_override_id, name_canonical=b.author_override_name)

            text_block = TextBlock(
                block_id=block_id,
                edition_id=edition_id,
                parent_block_id=None,
                block_type=block_type,
                block_subtype=block_subtype,
                title=b.title,
                order_index=b.order_index,
                path=b.path,
                author_id_override=author_override_id,
                author_role=None,
            )
            session.add(text_block)
            session.flush()

            for block_para_index, para_text in enumerate(b.paragraphs):
                para_id = uuid.uuid4()
                normalized = para_text.strip()
                para_hash = sha256_text(normalized)
                paragraph = Paragraph(
                    para_id=para_id,
                    edition_id=edition_id,
                    block_id=block_id,
                    order_index=global_para_order,
                    start_char=None,
                    end_char=None,
                    para_hash=para_hash,
                    text_normalized=normalized,
                )
                session.add(paragraph)
                session.flush()

                sentences = split_paragraph_into_sentences(language, normalized)
                for sent_index, sentence in enumerate(sentences):
                    span = SentenceSpan(
                        span_id=uuid.uuid4(),
                        edition_id=edition_id,
                        block_id=block_id,
                        para_id=para_id,
                        para_index=global_para_order,
                        sent_index=sent_index,
                        start_char=None,
                        end_char=None,
                        text=sentence,
                        text_hash=sha256_text(sentence),
                        prev_span_id=None,
                        next_span_id=None,
                    )
                    session.add(span)
                    span_sequence.append(span)

                global_para_order += 1

        session.flush()

        for i, span in enumerate(span_sequence):
            if i > 0:
                span.prev_span_id = span_sequence[i - 1].span_id
            if i + 1 < len(span_sequence):
                span.next_span_id = span_sequence[i + 1].span_id

        ingest_run.finished_at = datetime.utcnow()
        ingest_run.status = "succeeded"

        session.commit()

    typer.echo(f"edition_id: {edition_id}")


@app.command("ingest-work")
def ingest_work(
    root_url: str,
    *,
    language: str = typer.Option("en", help="Edition language code (e.g., en, es, de)."),
    author: str = typer.Option("Unknown", help="Canonical author name (override)."),
    title: str = typer.Option(..., help="Work title (canonical)."),
    max_pages: int = typer.Option(100, help="Maximum number of pages to ingest from the work directory."),
) -> None:
    """
    Ingest a multi-page work (directory) into a single Edition.

    - Discovers pages within the same directory as root_url (bounded).
    - Snapshots each page to `data/raw/`.
    - Persists all blocks/paragraphs/sentences into ONE Edition, ordered by URL then heading order.

    This avoids creating multiple Editions for works split across pages (common on marxists.org).
    """
    _ = core_settings.database_url
    discovery = discover_work_urls(root_url, max_pages=max_pages)

    author_id = author_id_for(author)
    work_id = work_id_for(author_id=author_id, title=title)
    edition_id = edition_id_for(work_id=work_id, language=language, source_url=discovery.root_url)

    started = datetime.utcnow()
    ingest_run_id = uuid.uuid4()
    manifest = {
        "root_url": discovery.root_url,
        "base_prefix": discovery.base_prefix,
        "urls": discovery.urls,
        "snapshots": [],
        "started_at": started.isoformat(),
    }

    for url in discovery.urls:
        snap = snapshot_url(url)
        manifest["snapshots"].append(
            {
                "url": url,
                "sha256": snap.sha256,
                "raw_path": str(snap.raw_path),
                "meta_path": str(snap.meta_path),
                "content_type": snap.content_type,
            }
        )

    finished = datetime.utcnow()
    manifest["finished_at"] = finished.isoformat()

    raw_dir = ingest_settings.data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / f"ingest_run_{ingest_run_id}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with SessionLocal() as session:
        _upsert_author(session, author_id=author_id, name_canonical=author)
        _upsert_work(session, work_id=work_id, author_id=author_id, title=title)

        ingest_run = IngestRun(
            ingest_run_id=ingest_run_id,
            pipeline_version="v0",
            git_commit_hash=None,
            source_url=discovery.root_url,
            raw_object_key=str(manifest_path),
            raw_checksum=sha256_text(manifest_path.read_text(encoding="utf-8")),
            started_at=started,
            finished_at=finished,
            status="started",
            error_log=None,
        )
        session.add(ingest_run)

        edition = session.get(Edition, edition_id)
        if edition is None:
            edition = Edition(
                edition_id=edition_id,
                work_id=work_id,
                language=language,
                translator_editor=None,
                publication_year=None,
                source_url=discovery.root_url,
                ingest_run_id=ingest_run.ingest_run_id,
            )
            session.add(edition)
        else:
            edition.ingest_run_id = ingest_run.ingest_run_id

        session.flush()

        span_sequence: list[SentenceSpan] = []
        global_block_order = 0
        global_para_order = 0

        for page_idx, page in enumerate(manifest["snapshots"]):
            url = page["url"]
            html = Path(page["raw_path"]).read_text(encoding="utf-8", errors="replace")
            parsed_blocks = parse_html_to_blocks(html)

            for b in parsed_blocks:
                block_id = uuid.uuid4()
                block_type = _map_block_type(b.block_type)
                block_subtype = _map_block_subtype(b.block_subtype)

                author_override_id = None
                if b.author_override_name:
                    author_override_id = author_id_for(b.author_override_name)
                    _upsert_author(session, author_id=author_override_id, name_canonical=b.author_override_name)

                block_title = b.title
                if block_title is None:
                    block_title = f"Page {page_idx + 1}"
                # Keep page URL visible for audit/debug until we add a dedicated source_url field.
                block_title = f"{block_title} [{url}]"

                text_block = TextBlock(
                    block_id=block_id,
                    edition_id=edition_id,
                    parent_block_id=None,
                    block_type=block_type,
                    block_subtype=block_subtype,
                    title=block_title,
                    order_index=global_block_order,
                    path=f"{page_idx + 1}.{b.order_index + 1}",
                    author_id_override=author_override_id,
                    author_role=None,
                )
                session.add(text_block)
                session.flush()
                global_block_order += 1

                for para_text in b.paragraphs:
                    para_id = uuid.uuid4()
                    normalized = para_text.strip()
                    if not normalized:
                        continue
                    para_hash = sha256_text(normalized)
                    paragraph = Paragraph(
                        para_id=para_id,
                        edition_id=edition_id,
                        block_id=block_id,
                        order_index=global_para_order,
                        start_char=None,
                        end_char=None,
                        para_hash=para_hash,
                        text_normalized=normalized,
                    )
                    session.add(paragraph)
                    session.flush()

                    sentences = split_paragraph_into_sentences(language, normalized)
                    for sent_index, sentence in enumerate(sentences):
                        span = SentenceSpan(
                            span_id=uuid.uuid4(),
                            edition_id=edition_id,
                            block_id=block_id,
                            para_id=para_id,
                            para_index=global_para_order,
                            sent_index=sent_index,
                            start_char=None,
                            end_char=None,
                            text=sentence,
                            text_hash=sha256_text(sentence),
                            prev_span_id=None,
                            next_span_id=None,
                        )
                        session.add(span)
                        span_sequence.append(span)

                    global_para_order += 1

        session.flush()

        for i, span in enumerate(span_sequence):
            if i > 0:
                span.prev_span_id = span_sequence[i - 1].span_id
            if i + 1 < len(span_sequence):
                span.next_span_id = span_sequence[i + 1].span_id

        ingest_run.status = "succeeded"
        session.commit()

    typer.echo(f"edition_id: {edition_id}")


def _upsert_author(session, *, author_id: uuid.UUID, name_canonical: str) -> None:
    existing = session.get(Author, author_id)
    if existing is None:
        session.add(
            Author(
                author_id=author_id,
                name_canonical=name_canonical,
                name_variants=[],
                birth_year=None,
                death_year=None,
            )
        )


def _upsert_work(session, *, work_id: uuid.UUID, author_id: uuid.UUID, title: str) -> None:
    existing = session.get(Work, work_id)
    if existing is None:
        session.add(
            Work(
                work_id=work_id,
                author_id=author_id,
                title=title,
                work_type=WorkType.other,
                composition_date=None,
                publication_date=None,
                original_language=None,
                source_urls=[],
            )
        )


def _map_block_type(value: str) -> TextBlockType:
    mapping = {
        "chapter": TextBlockType.chapter,
        "section": TextBlockType.section,
        "subsection": TextBlockType.subsection,
        "other": TextBlockType.other,
    }
    return mapping.get(value, TextBlockType.other)


def _map_block_subtype(value: str | None) -> BlockSubtype | None:
    if value is None:
        return None
    mapping = {
        "preface": BlockSubtype.preface,
        "afterword": BlockSubtype.afterword,
        "footnote": BlockSubtype.footnote,
        "editor_note": BlockSubtype.editor_note,
        "letter": BlockSubtype.letter,
        "appendix": BlockSubtype.appendix,
        "other": BlockSubtype.other,
    }
    return mapping.get(value, BlockSubtype.other)
