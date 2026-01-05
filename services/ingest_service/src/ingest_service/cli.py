from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import typer
from sqlalchemy import func, select

from grundrisse_core.hashing import sha256_text
from grundrisse_core.identity import author_id_for, edition_id_for, work_id_for
from grundrisse_core.settings import settings as core_settings

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.enums import BlockSubtype, TextBlockType, WorkType
from grundrisse_core.db.models import (
    Author,
    AuthorAlias,
    AuthorMetadataEvidence,
    AuthorMetadataRun,
    Edition,
    IngestRun,
    Paragraph,
    SentenceSpan,
    TextBlock,
    Work,
    WorkDateFinal,
    WorkDateDerivationRun,
    WorkDateDerived,
    EditionSourceHeader,
    WorkMetadataEvidence,
    WorkMetadataRun,
)
from ingest_service.crawl.discover import discover_work_urls
from ingest_service.fetch.snapshot import snapshot_url
from ingest_service.parse.html_to_blocks import parse_html_to_blocks
from ingest_service.parse.marxists_header_metadata import extract_marxists_header_metadata
from ingest_service.segment.sentences import split_paragraph_into_sentences
from ingest_service.settings import settings as ingest_settings
from ingest_service.utils.title_canonicalization import canonicalize_title

app = typer.Typer(help="Ingest service (snapshot, parse, segment).")

def _sanitize_url(url: str) -> str:
    # Users may paste line-wrapped URLs; remove whitespace defensively.
    return "".join(url.split())


@app.command()
def fetch(url: str) -> None:
    """
    Fetch and store an immutable raw HTML snapshot under `data/raw/`.

    Note: requires network access at runtime.
    """
    snap = snapshot_url(_sanitize_url(url))
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
    url = _sanitize_url(url)
    snap = snapshot_url(url)
    html = snap.content.decode("utf-8", errors="replace")
    header_meta = extract_marxists_header_metadata(html)
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
                source_metadata=_normalize_source_metadata(
                    header_meta,
                    source_url=url,
                    raw_object_key=str(snap.raw_path),
                    raw_sha256=snap.sha256,
                ),
                ingest_run_id=ingest_run.ingest_run_id,
            )
            session.add(edition)
        else:
            edition.ingest_run_id = ingest_run.ingest_run_id
            if header_meta is not None:
                edition.source_metadata = _merge_source_metadata(
                    edition.source_metadata,
                    _normalize_source_metadata(
                        header_meta,
                        source_url=url,
                        raw_object_key=str(snap.raw_path),
                        raw_sha256=snap.sha256,
                    ),
                )

        session.flush()

        existing_blocks_by_order = _load_existing_blocks_by_order(session, edition_id=edition_id)
        existing_paras_by_order = _load_existing_paragraphs_by_order(session, edition_id=edition_id)
        existing_para_ids_with_spans = {
            r[0]
            for r in session.query(SentenceSpan.para_id)
            .filter(SentenceSpan.edition_id == edition_id)
            .distinct()
            .all()
        }

        created_spans = 0
        global_para_order = 0
        for b in parsed_blocks:
            block_type = _map_block_type(b.block_type)
            block_subtype = _map_block_subtype(b.block_subtype)

            author_override_id = None
            if b.author_override_name:
                author_override_id = author_id_for(b.author_override_name)
                _upsert_author(session, author_id=author_override_id, name_canonical=b.author_override_name)

            existing_block = existing_blocks_by_order.get(b.order_index)
            effective_subtype = _prefer_subtype(_infer_page_subtype(url), block_subtype)
            if existing_block is not None:
                if existing_block.block_type != block_type or existing_block.block_subtype != effective_subtype:
                    raise RuntimeError(
                        "Ingest would mutate an existing Edition's block structure. "
                        f"edition_id={edition_id} block_order={b.order_index} "
                        f"existing_type={existing_block.block_type} new_type={block_type} "
                        f"existing_subtype={existing_block.block_subtype} new_subtype={effective_subtype}. "
                        "Create a new Edition (different source_url) if the substrate changed."
                    )
                if (existing_block.path or None) != (b.path or None):
                    raise RuntimeError(
                        "Ingest would mutate an existing Edition's block path. "
                        f"edition_id={edition_id} block_order={b.order_index} "
                        f"existing_path={existing_block.path!r} new_path={b.path!r}. "
                        "Create a new Edition if parsing changed."
                    )
                block_id = existing_block.block_id
            else:
                text_block = TextBlock(
                    block_id=uuid.uuid4(),
                    edition_id=edition_id,
                    parent_block_id=None,
                    block_type=block_type,
                    block_subtype=effective_subtype,
                    title=b.title,
                    source_url=url,
                    order_index=b.order_index,
                    path=b.path,
                    author_id_override=author_override_id,
                    author_role=None,
                )
                session.add(text_block)
                session.flush()
                block_id = text_block.block_id

            for block_para_index, para_text in enumerate(b.paragraphs):
                normalized = para_text.strip()
                if not normalized:
                    continue
                para_hash = sha256_text(normalized)
                existing_para = existing_paras_by_order.get(global_para_order)
                if existing_para is not None:
                    if existing_para.para_hash != para_hash:
                        raise RuntimeError(
                            "Ingest would mutate an existing Edition's paragraph content. "
                            f"edition_id={edition_id} para_order={global_para_order} "
                            f"existing_hash={existing_para.para_hash} new_hash={para_hash}. "
                            "Create a new Edition if the substrate changed."
                        )
                    if existing_para.block_id != block_id:
                        raise RuntimeError(
                            "Ingest would mutate an existing Edition's paragraph block assignment. "
                            f"edition_id={edition_id} para_order={global_para_order} "
                            f"existing_block_id={existing_para.block_id} new_block_id={block_id}. "
                            "Create a new Edition if parsing changed."
                        )
                    para_id = existing_para.para_id
                else:
                    paragraph = Paragraph(
                        para_id=uuid.uuid4(),
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
                    para_id = paragraph.para_id

                # Only create spans if they are missing for this paragraph (resume-safe).
                if para_id not in existing_para_ids_with_spans:
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
                        created_spans += 1
                    existing_para_ids_with_spans.add(para_id)

                global_para_order += 1

        session.flush()

        if created_spans:
            _relink_spans_for_edition(session, edition_id=edition_id)

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
    root_url = _sanitize_url(root_url)
    discovery = discover_work_urls(root_url, max_pages=max_pages)
    if not discovery.urls:
        raise typer.BadParameter(f"No in-scope URLs discovered from root_url={root_url!r}. Check the URL.")

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
    # Best-effort: parse header metadata from the root snapshot (or first snapshot with metadata).
    header_meta = None
    try:
        for page in manifest["snapshots"][:5]:
            html = Path(page["raw_path"]).read_text(encoding="utf-8", errors="replace")
            header_meta = extract_marxists_header_metadata(html)
            if header_meta:
                break
    except Exception:
        header_meta = None

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
                source_metadata=_normalize_source_metadata(
                    header_meta,
                    source_url=discovery.root_url,
                    raw_object_key=str(manifest_path),
                    raw_sha256=sha256_text(manifest_path.read_text(encoding="utf-8")),
                ),
                ingest_run_id=ingest_run.ingest_run_id,
            )
            session.add(edition)
        else:
            edition.ingest_run_id = ingest_run.ingest_run_id
            if header_meta is not None:
                edition.source_metadata = _merge_source_metadata(
                    edition.source_metadata,
                    _normalize_source_metadata(
                        header_meta,
                        source_url=discovery.root_url,
                        raw_object_key=str(manifest_path),
                        raw_sha256=sha256_text(manifest_path.read_text(encoding="utf-8")),
                    ),
                )

        session.flush()

        existing_blocks_by_order = _load_existing_blocks_by_order(session, edition_id=edition_id)
        existing_paras_by_order = _load_existing_paragraphs_by_order(session, edition_id=edition_id)
        existing_para_ids_with_spans = {
            r[0]
            for r in session.query(SentenceSpan.para_id)
            .filter(SentenceSpan.edition_id == edition_id)
            .distinct()
            .all()
        }

        created_spans = 0
        global_block_order = 0
        global_para_order = 0

        for page_idx, page in enumerate(manifest["snapshots"]):
            url = page["url"]
            html = Path(page["raw_path"]).read_text(encoding="utf-8", errors="replace")
            parsed_blocks = parse_html_to_blocks(html)

            for b in parsed_blocks:
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

                path = f"{page_idx + 1}.{b.order_index + 1}"
                existing_block = existing_blocks_by_order.get(global_block_order)
                effective_subtype = _prefer_subtype(_infer_page_subtype(url), block_subtype)
                if existing_block is not None:
                    if existing_block.block_type != block_type or existing_block.block_subtype != effective_subtype:
                        raise RuntimeError(
                            "Ingest-work would mutate an existing Edition's block structure. "
                            f"edition_id={edition_id} block_order={global_block_order} "
                            f"existing_type={existing_block.block_type} new_type={block_type} "
                            f"existing_subtype={existing_block.block_subtype} new_subtype={effective_subtype}. "
                            "Create a new Edition if parsing changed."
                        )
                    if (existing_block.path or None) != path:
                        raise RuntimeError(
                            "Ingest-work would mutate an existing Edition's block path. "
                            f"edition_id={edition_id} block_order={global_block_order} "
                            f"existing_path={existing_block.path!r} new_path={path!r}. "
                            "Create a new Edition if parsing changed."
                        )
                    block_id = existing_block.block_id
                else:
                    text_block = TextBlock(
                        block_id=uuid.uuid4(),
                        edition_id=edition_id,
                        parent_block_id=None,
                        block_type=block_type,
                        block_subtype=effective_subtype,
                        title=block_title,
                        source_url=url,
                        order_index=global_block_order,
                        path=path,
                        author_id_override=author_override_id,
                        author_role=None,
                    )
                    session.add(text_block)
                    session.flush()
                    block_id = text_block.block_id
                global_block_order += 1

                for para_text in b.paragraphs:
                    normalized = para_text.strip()
                    if not normalized:
                        continue
                    para_hash = sha256_text(normalized)
                    existing_para = existing_paras_by_order.get(global_para_order)
                    if existing_para is not None:
                        if existing_para.para_hash != para_hash:
                            raise RuntimeError(
                                "Ingest-work would mutate an existing Edition's paragraph content. "
                                f"edition_id={edition_id} para_order={global_para_order} "
                                f"existing_hash={existing_para.para_hash} new_hash={para_hash}. "
                                "Create a new Edition if the substrate changed."
                            )
                        if existing_para.block_id != block_id:
                            raise RuntimeError(
                                "Ingest-work would mutate an existing Edition's paragraph block assignment. "
                                f"edition_id={edition_id} para_order={global_para_order} "
                                f"existing_block_id={existing_para.block_id} new_block_id={block_id}. "
                                "Create a new Edition if parsing changed."
                            )
                        para_id = existing_para.para_id
                    else:
                        paragraph = Paragraph(
                            para_id=uuid.uuid4(),
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
                        para_id = paragraph.para_id

                    if para_id not in existing_para_ids_with_spans:
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
                            created_spans += 1
                        existing_para_ids_with_spans.add(para_id)

                    global_para_order += 1

        session.flush()

        if created_spans:
            _relink_spans_for_edition(session, edition_id=edition_id)

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
                title_canonical=canonicalize_title(title),
                work_type=WorkType.other,
                composition_date=None,
                publication_date=None,
                original_language=None,
                source_urls=[],
            )
        )
    else:
        if existing.title_canonical is None:
            existing.title_canonical = canonicalize_title(existing.title)


def _normalize_source_metadata(
    header_meta: dict | None, *, source_url: str, raw_object_key: str, raw_sha256: str
) -> dict | None:
    if header_meta is None:
        return None
    meta = dict(header_meta)
    meta.setdefault("source_url", source_url)
    meta.setdefault("raw_object_key", raw_object_key)
    meta.setdefault("raw_sha256", raw_sha256)
    meta.setdefault("source", "marxists.org")
    return meta


def _merge_source_metadata(existing: dict | None, incoming: dict | None) -> dict | None:
    """
    Best-effort merge: keep existing values, fill in missing keys from incoming.
    Intended to be idempotent and safe when re-ingesting.
    """
    if incoming is None:
        return existing
    if existing is None:
        return incoming

    merged = dict(existing)
    for k, v in incoming.items():
        if k not in merged or merged.get(k) in (None, "", [], {}):
            merged[k] = v
            continue

        if k == "fields" and isinstance(merged.get(k), dict) and isinstance(v, dict):
            fields = dict(merged[k])
            for fk, fv in v.items():
                if fk not in fields or fields.get(fk) in (None, ""):
                    fields[fk] = fv
            merged[k] = fields

    return merged


def _candidate_from_ingested_marxists_html(
    *, raw_object_keys: list[str], max_pages: int, fallback_url: str | None = None
):
    """
    Build a high-confidence publication-date candidate by parsing already-ingested marxists.org HTML.
    This avoids network access and is typically much faster than HTTP-based resolvers.
    """
    from ingest_service.metadata.publication_date_resolver import PublicationDateCandidate

    for raw_object_key in raw_object_keys:
        for source_url, raw_sha256, html in _iter_html_from_raw_object_key(raw_object_key, max_pages=max_pages):
            if not source_url and isinstance(fallback_url, str) and fallback_url:
                source_url = fallback_url
            meta = extract_marxists_header_metadata(html)
            if not meta:
                continue
            fields = meta.get("fields") if isinstance(meta, dict) else None
            dates = meta.get("dates") if isinstance(meta, dict) else None
            if not isinstance(fields, dict) or not isinstance(dates, dict):
                continue

            first_published_raw = fields.get("First Published")
            published_raw = fields.get("Published")
            source_raw = fields.get("Source")

            first_published = dates.get("first_published")
            published = dates.get("published")

            chosen: dict | None = None
            chosen_field: str | None = None
            chosen_raw: str | None = None
            method = ""
            score = 0.0

            if isinstance(first_published, dict) and isinstance(first_published.get("year"), int):
                chosen = first_published
                chosen_field = "First Published"
                chosen_raw = first_published_raw if isinstance(first_published_raw, str) else None
                method = "marxists_header_first_published"
                score = 0.95
            elif isinstance(published, dict) and isinstance(published.get("year"), int):
                # "Published" is ambiguous on marxists.org; accept only when it looks like a genuine first-publication
                # reference (newspaper/journal/book first appearance), and reject Collected Works edition blurbs.
                if _marxists_header_line_is_probably_first_publication(published_raw):
                    chosen = published
                    chosen_field = "Published"
                    chosen_raw = published_raw if isinstance(published_raw, str) else None
                    method = "marxists_header_published"
                    score = 0.92
            else:
                # Many pages omit "First Published" / "Published" but include a detailed "Source" with issue/date.
                # Use it cautiously at the threshold edge.
                if _marxists_header_line_is_probably_first_publication(source_raw):
                    from ingest_service.parse.marxists_header_metadata import parse_dateish

                    parsed = parse_dateish(source_raw if isinstance(source_raw, str) else None)
                    if isinstance(parsed, dict) and isinstance(parsed.get("year"), int):
                        chosen = parsed
                        chosen_field = "Source"
                        chosen_raw = source_raw if isinstance(source_raw, str) else None
                        method = "marxists_header_source"
                        score = 0.90

            if not chosen or not isinstance(chosen.get("year"), int):
                continue

            date = {
                "year": chosen["year"],
                "month": chosen.get("month"),
                "day": chosen.get("day"),
                "precision": chosen.get("precision") or "year",
                "method": method,
            }
            raw_payload = {
                "source": "marxists.org",
                "mode": "ingested_html",
                "source_url": source_url,
                "raw_object_key": raw_object_key,
                "raw_sha256": raw_sha256,
                "header_field": chosen_field,
                "header_value": chosen_raw,
                "header": meta,
            }
            return PublicationDateCandidate(
                date=date,
                score=score,
                source_name="marxists_ingested_html",
                source_locator=source_url,
                raw_payload=raw_payload,
                notes="Parsed from ingested marxists.org header metadata (no HTTP).",
            )

    return None


def _marxists_header_line_is_probably_first_publication(value: str | None) -> bool:
    """
    Decide whether a marxists.org header line ("Published", "Source") likely refers to first-publication,
    rather than a later collected-works edition or an internet-archive statement.
    """
    if not value or not isinstance(value, str):
        return False
    v = value.strip()
    if not v:
        return False
    lower = v.lower()

    # Reject obvious non-publication info.
    if "internet archive" in lower or "marxists internet archive" in lower:
        return False
    if "transcription" in lower or "markup" in lower or "mark-up" in lower or "proof" in lower:
        return False
    if "public domain" in lower or "copyleft" in lower or "creative commons" in lower:
        return False

    # Reject collected-works / anthology edition blurbs (these often contain misleading years).
    collected_markers = [
        "collected works",
        "selected works",
        "progress publishers",
        "foreign languages publishing house",
        "volume",
        "vol.",
        "english edition",
        "mосква",
        "moscow",
    ]
    if any(m in lower for m in collected_markers):
        # Allow periodical sources even if they include "vol." etc; but "Collected Works" etc is a strong reject.
        if "collected works" in lower or "selected works" in lower or "progress publishers" in lower:
            return False

    # Positive signals: periodicals / issue citations.
    positive_markers = [
        "no.",
        "issue",
        "whole no.",
        "vol.",
        "pp.",
        "pravda",
        "iskra",
        "new international",
        "new york",
        "gazette",
        "journal",
        "newspaper",
        "bulletin",
        "review",
    ]
    if any(m in lower for m in positive_markers):
        return True

    # Otherwise: accept only if it contains a concrete date-ish pattern (month/day/year or year).
    # This is conservative and keeps the min_score threshold meaningful.
    return bool(re.search(r"(?<!\d)(1[5-9]\d{2}|20[0-3]\d)(?!\d)", lower))


def _iter_html_from_raw_object_key(raw_object_key: str, *, max_pages: int) -> list[tuple[str, str, str]]:
    """
    Yield (source_url, raw_sha256, html_string) from an ingest_run raw_object_key.
    raw_object_key may be:
      - a single-page snapshot: `.../<sha256>.html`
      - a manifest JSON for multi-page ingest: `.../ingest_run_<uuid>.json`
    """
    import json
    from pathlib import Path

    out: list[tuple[str, str, str]] = []
    path = Path(raw_object_key)
    if not path.exists():
        return out

    if path.suffix.lower() == ".html":
        sha = path.stem
        html = path.read_text(encoding="utf-8", errors="replace")
        out.append(("", sha, html))
        return out

    if path.suffix.lower() == ".json":
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return out
        snapshots = manifest.get("snapshots")
        if not isinstance(snapshots, list):
            return out
        for page in snapshots[: max(1, max_pages)]:
            if not isinstance(page, dict):
                continue
            url = page.get("url") if isinstance(page.get("url"), str) else ""
            raw_path = page.get("raw_path") if isinstance(page.get("raw_path"), str) else None
            sha = page.get("sha256") if isinstance(page.get("sha256"), str) else None
            if not raw_path:
                continue
            try:
                html = Path(raw_path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            out.append((url, sha or "", html))
        return out

    return out


def _persist_edition_source_metadata_from_candidate(session, *, edition_ids: list[uuid.UUID], candidate) -> None:
    raw = getattr(candidate, "raw_payload", None)
    if not isinstance(raw, dict):
        return
    header = raw.get("header")
    if not isinstance(header, dict):
        return
    raw_object_key = raw.get("raw_object_key")
    raw_sha256 = raw.get("raw_sha256")
    if not isinstance(raw_object_key, str) or not isinstance(raw_sha256, str):
        return

    for edition_id in edition_ids:
        edition = session.get(Edition, edition_id)
        if edition is None:
            continue
        edition.source_metadata = _merge_source_metadata(
            edition.source_metadata,
            _normalize_source_metadata(
                header,
                source_url=edition.source_url,
                raw_object_key=raw_object_key,
                raw_sha256=raw_sha256,
            ),
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
        "toc": BlockSubtype.toc,
        "navigation": BlockSubtype.navigation,
        "license": BlockSubtype.license,
        "metadata": BlockSubtype.metadata,
        "study_guide": BlockSubtype.study_guide,
        "other": BlockSubtype.other,
    }
    return mapping.get(value, BlockSubtype.other)


def _prefer_subtype(primary: BlockSubtype | None, secondary: BlockSubtype | None) -> BlockSubtype | None:
    """
    Prefer a more informative subtype. Used to apply page-level signals (e.g., guide/toc pages)
    without overriding strong content signals like preface/afterword.
    """
    if secondary in {BlockSubtype.preface, BlockSubtype.afterword, BlockSubtype.footnote, BlockSubtype.editor_note}:
        return secondary
    return primary or secondary


def _infer_page_subtype(url: str) -> BlockSubtype | None:
    """
    Lightweight, URL-based subtype inference to tag obvious non-content pages.
    This improves downstream filtering without requiring HTML heuristics.
    """
    try:
        path = urlparse(url).path.lower()
    except Exception:
        path = url.lower()

    if path.endswith("/guide.htm"):
        return BlockSubtype.study_guide
    if path.endswith("/index.htm") or path.endswith("/index.html"):
        return BlockSubtype.toc
    return None


def _load_existing_blocks_by_order(session, *, edition_id: uuid.UUID) -> dict[int, TextBlock]:
    blocks = session.query(TextBlock).filter(TextBlock.edition_id == edition_id).all()
    by_order: dict[int, TextBlock] = {}
    dupes: list[int] = []
    for b in blocks:
        if b.order_index in by_order:
            dupes.append(b.order_index)
            continue
        by_order[b.order_index] = b
    if dupes:
        raise RuntimeError(
            f"Edition has duplicate TextBlock.order_index values; cannot ingest idempotently. "
            f"edition_id={edition_id} duplicate_orders={sorted(set(dupes))[:20]!r}. "
            "Use a new Edition (different source_url) or clean the duplicated substrate."
        )
    return by_order


def _load_existing_paragraphs_by_order(session, *, edition_id: uuid.UUID) -> dict[int, Paragraph]:
    paras = session.query(Paragraph).filter(Paragraph.edition_id == edition_id).all()
    by_order: dict[int, Paragraph] = {}
    dupes: list[int] = []
    for p in paras:
        if p.order_index in by_order:
            dupes.append(p.order_index)
            continue
        by_order[p.order_index] = p
    if dupes:
        raise RuntimeError(
            f"Edition has duplicate Paragraph.order_index values; cannot ingest idempotently. "
            f"edition_id={edition_id} duplicate_orders={sorted(set(dupes))[:20]!r}. "
            "Use a new Edition (different source_url) or clean the duplicated substrate."
        )
    return by_order


def _relink_spans_for_edition(session, *, edition_id: uuid.UUID) -> None:
    spans = (
        session.query(SentenceSpan)
        .filter(SentenceSpan.edition_id == edition_id)
        .order_by(SentenceSpan.para_index.asc(), SentenceSpan.sent_index.asc())
        .all()
    )
    for i, span in enumerate(spans):
        prev_id = spans[i - 1].span_id if i > 0 else None
        next_id = spans[i + 1].span_id if i + 1 < len(spans) else None
        span.prev_span_id = prev_id
        span.next_span_id = next_id


@app.command("crawl-discover")
def crawl_discover(
    seed_url: str = typer.Option("https://www.marxists.org/", help="Seed URL to start crawling from"),
    *,
    max_languages: int = typer.Option(1, help="Maximum language areas to discover"),
    max_authors: int = typer.Option(10, help="Maximum authors per language"),
    max_works: int = typer.Option(5, help="Maximum works per author"),
    crawl_delay: float = typer.Option(0.5, help="Delay between requests (seconds)"),
) -> None:
    """
    Discover works from marxists.org and populate the URL catalog.

    This command performs multi-stage discovery:
    1. Seed discovery (language roots)
    2. Author discovery within languages
    3. Work discovery within authors
    4. Page discovery within works
    """
    from grundrisse_core.db.models import CrawlRun
    from ingest_service.crawl.http_client import RateLimitedHttpClient
    from ingest_service.crawl.marxists_org import MarxistsOrgCrawler

    data_dir = Path("data/raw")
    data_dir.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as session:
        # Create crawl run
        crawl_run = CrawlRun(
            pipeline_version="v0.1",
            crawl_scope={
                "seed_url": seed_url,
                "max_languages": max_languages,
                "max_authors": max_authors,
                "max_works": max_works,
            },
            started_at=datetime.utcnow(),
            status="started",
        )
        session.add(crawl_run)
        session.flush()

        typer.echo(f"Starting crawl run: {crawl_run.crawl_run_id}")

        # Create HTTP client and crawler
        with RateLimitedHttpClient(crawl_delay=crawl_delay) as http_client:
            crawler = MarxistsOrgCrawler(
                session=session,
                crawl_run_id=crawl_run.crawl_run_id,
                http_client=http_client,
                data_dir=data_dir,
            )

            try:
                # Stage 1: Discover language roots
                typer.echo("Discovering language roots...")
                language_urls = crawler.discover_seed_urls()
                typer.echo(f"Found {len(language_urls)} language areas")

                for lang_url in language_urls[:max_languages]:
                    typer.echo(f"\nProcessing language: {lang_url}")

                    # Stage 2: Discover authors
                    author_urls = crawler.discover_author_pages(lang_url, max_pages=max_authors)
                    typer.echo(f"Found {len(author_urls)} author pages")

                    for author_url in author_urls[:max_authors]:
                        typer.echo(f"  Processing author: {author_url}")

                        # Stage 3: Discover works
                        works = crawler.discover_work_directories(author_url, max_works=max_works)
                        typer.echo(f"  Found {len(works)} works")

                        for work_meta in works[:max_works]:
                            typer.echo(f"    Discovering pages for: {work_meta['work_title']}")

                            # Stage 4: Discover pages
                            page_urls = crawler.discover_work_pages(
                                work_meta["root_url"],
                                max_pages=100,
                            )

                            # Add work to catalog
                            work_discovery = crawler.work_catalog.add_work(
                                root_url=work_meta["root_url"],
                                author_name=work_meta["author_name"],
                                work_title=work_meta["work_title"],
                                language=work_meta["language"],
                                page_urls=page_urls,
                            )

                            typer.echo(f"    Discovered {len(page_urls)} pages")
                            crawl_run.urls_discovered += len(page_urls)

                            # Add URLs to catalog
                            for url in page_urls:
                                crawler.url_catalog.add_url(
                                    url,
                                    discovered_from_url=work_meta["root_url"],
                                    status="new",
                                )

                        session.commit()

                # Mark crawl run as completed
                crawl_run.status = "completed"
                crawl_run.finished_at = datetime.utcnow()
                session.commit()

                typer.echo(f"\nCrawl completed! Discovered {crawl_run.urls_discovered} URLs")

            except Exception as e:
                crawl_run.status = "failed"
                crawl_run.error_log = str(e)
                crawl_run.finished_at = datetime.utcnow()
                session.commit()
                typer.echo(f"Crawl failed: {e}", err=True)
                raise


@app.command("crawl-ingest")
def crawl_ingest(
    crawl_run_id: str = typer.Argument(..., help="Crawl run ID to ingest works from"),
    *,
    max_works: int = typer.Option(10, help="Maximum works to ingest"),
) -> None:
    """
    Ingest discovered works from a crawl run.

    This command reads the work_discovery table and calls the existing
    `ingest-work` logic for each discovered work.
    """
    from grundrisse_core.db.models import CrawlRun
    from ingest_service.crawl.catalog import WorkCatalog

    crawl_run_uuid = uuid.UUID(crawl_run_id)

    with SessionLocal() as session:
        # Get crawl run
        crawl_run = session.get(CrawlRun, crawl_run_uuid)
        if not crawl_run:
            typer.echo(f"Crawl run not found: {crawl_run_id}", err=True)
            raise typer.Exit(1)

        # Get pending works
        work_catalog = WorkCatalog(session, crawl_run_uuid)
        pending_works = work_catalog.get_pending_works(limit=max_works)

        typer.echo(f"Found {len(pending_works)} pending works to ingest")

        for work in pending_works:
            typer.echo(f"\nIngesting: {work.work_title} by {work.author_name}")

            try:
                # Call ingest-work for this work
                # This reuses the existing ingestion logic
                ingest_work(
                    url=work.root_url,
                    language=work.language,
                    author=work.author_name,
                    title=work.work_title,
                )

                # Mark as ingested
                # Note: We'd need to capture the edition_id from ingest_work to store it
                work_catalog.mark_work_ingested(work.discovery_id, uuid.uuid4())  # Placeholder
                session.commit()

                typer.echo(f"  ✓ Ingested successfully")

            except Exception as e:
                typer.echo(f"  ✗ Failed: {e}", err=True)
                work_catalog.mark_work_failed(work.discovery_id, str(e))
                session.commit()


@app.command("crawl-build-graph")
def crawl_build_graph(
    seed_url: str = typer.Argument("https://www.marxists.org/", help="Seed URL to start crawling from"),
    *,
    max_depth: int = typer.Option(8, help="Maximum depth to crawl"),
    max_urls: int = typer.Option(10000, help="Maximum URLs to discover"),
    crawl_delay: float = typer.Option(0.5, help="Delay between requests (seconds)"),
    content_only: bool = typer.Option(False, help="Skip navigation/index pages, focus on content"),
) -> None:
    """
    Phase 1: Build complete hyperlink graph without classification.

    This is the CHEAP phase - just HTTP requests to discover structure.
    No LLM calls yet. Output is a complete link graph in the database.

    Use --content-only to skip navigation pages and focus on actual work content.

    Example:
        grundrisse-ingest crawl-build-graph https://www.marxists.org/ --max-depth 6 --content-only
    """
    from grundrisse_core.db.models import CrawlRun
    from ingest_service.crawl.http_client import RateLimitedHttpClient
    from ingest_service.crawl.link_graph import LinkGraphBuilder

    data_dir = Path("data/raw")
    data_dir.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as session:
        # Create crawl run
        crawl_run = CrawlRun(
            pipeline_version="v0.2-progressive",
            crawl_scope={
                "seed_url": seed_url,
                "max_depth": max_depth,
                "max_urls": max_urls,
                "phase": "link_graph",
                "content_only": content_only,
            },
            started_at=datetime.utcnow(),
            status="started",
        )
        session.add(crawl_run)
        session.flush()

        typer.echo(f"Starting crawl run: {crawl_run.crawl_run_id}")
        typer.echo(f"Building link graph from {seed_url}...")
        if content_only:
            typer.echo("Using content-only filter (skipping navigation/index pages)")

        # Create HTTP client and graph builder
        from ingest_service.utils.url_canonicalization import is_likely_content_url

        # Use content filter if requested
        scope_filter = None
        if content_only:
            def combined_filter(url):
                from ingest_service.utils.url_canonicalization import is_marxists_org_url
                return is_marxists_org_url(url) and is_likely_content_url(url)
            scope_filter = combined_filter

        with RateLimitedHttpClient(crawl_delay=crawl_delay) as http_client:
            builder = LinkGraphBuilder(
                session=session,
                crawl_run_id=crawl_run.crawl_run_id,
                http_client=http_client,
                data_dir=data_dir,
                scope_filter=scope_filter,
            )

            try:
                stats = builder.build_graph(
                    seed_url=seed_url,
                    max_depth=max_depth,
                    max_urls=max_urls,
                )

                # Update crawl run
                crawl_run.urls_discovered = stats["urls_discovered"]
                crawl_run.urls_fetched = stats["urls_fetched"]
                crawl_run.urls_failed = stats["urls_failed"]
                crawl_run.status = "completed"
                crawl_run.finished_at = datetime.utcnow()
                session.commit()

                typer.echo(f"\n✓ Link graph built successfully!")
                typer.echo(f"  URLs discovered: {stats['urls_discovered']}")
                typer.echo(f"  URLs fetched: {stats['urls_fetched']}")
                typer.echo(f"  URLs failed: {stats['urls_failed']}")
                typer.echo(f"  Max depth reached: {stats['max_depth_reached']}")
                typer.echo(f"\nCrawl run ID: {crawl_run.crawl_run_id}")
                typer.echo(f"\nNext step: Run classification with:")
                typer.echo(f"  grundrisse-ingest crawl-classify {crawl_run.crawl_run_id}")

            except Exception as e:
                crawl_run.status = "failed"
                crawl_run.error_log = str(e)
                crawl_run.finished_at = datetime.utcnow()
                session.commit()
                typer.echo(f"✗ Crawl failed: {e}", err=True)
                raise


@app.command("crawl-resume")
def crawl_resume(
    crawl_run_id: str = typer.Argument(..., help="Crawl run ID to resume"),
    *,
    max_depth: int = typer.Option(8, help="Maximum depth to crawl"),
    max_urls: int = typer.Option(10000, help="Maximum URLs to discover"),
    crawl_delay: float = typer.Option(0.5, help="Delay between requests (seconds)"),
    content_only: bool = typer.Option(False, help="Skip navigation/index pages, focus on content"),
) -> None:
    """
    Resume an incomplete link graph build.

    Use this when a crawl hit the max-urls limit or was interrupted.
    It will continue from where it left off, exploring unfetched child URLs.

    Example:
        grundrisse-ingest crawl-resume 977c931a-be0d-4b53-81ff-ed36d9478566 --max-urls 10000
    """
    from grundrisse_core.db.models import CrawlRun
    from ingest_service.crawl.http_client import RateLimitedHttpClient
    from ingest_service.crawl.link_graph import LinkGraphBuilder

    data_dir = Path("data/raw")
    data_dir.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as session:
        # Get existing crawl run
        crawl_run_uuid = uuid.UUID(crawl_run_id)
        crawl_run = session.get(CrawlRun, crawl_run_uuid)

        if not crawl_run:
            typer.echo(f"✗ Crawl run {crawl_run_id} not found", err=True)
            raise typer.Exit(1)

        typer.echo(f"Resuming crawl run: {crawl_run.crawl_run_id}")
        typer.echo(f"Previous stats:")
        typer.echo(f"  URLs discovered: {crawl_run.urls_discovered}")
        typer.echo(f"  URLs fetched: {crawl_run.urls_fetched}")
        typer.echo(f"  URLs failed: {crawl_run.urls_failed}")
        typer.echo("")

        # Get seed URL from crawl scope
        seed_url = crawl_run.crawl_scope.get("seed_url", "https://www.marxists.org/")

        # Update status
        crawl_run.status = "resumed"

        # Create HTTP client and graph builder
        from ingest_service.utils.url_canonicalization import is_likely_content_url

        # Use content filter if requested
        scope_filter = None
        if content_only:
            def combined_filter(url):
                from ingest_service.utils.url_canonicalization import is_marxists_org_url
                return is_marxists_org_url(url) and is_likely_content_url(url)
            scope_filter = combined_filter
            typer.echo("Using content-only filter (skipping navigation/index pages)")

        with RateLimitedHttpClient(crawl_delay=crawl_delay) as http_client:
            builder = LinkGraphBuilder(
                session=session,
                crawl_run_id=crawl_run.crawl_run_id,
                http_client=http_client,
                data_dir=data_dir,
                scope_filter=scope_filter,
            )

            try:
                stats = builder.build_graph(
                    seed_url=seed_url,
                    max_depth=max_depth,
                    max_urls=max_urls,
                    resume=True,
                )

                # Update crawl run
                crawl_run.urls_discovered = stats["urls_discovered"]
                crawl_run.urls_fetched = stats["urls_fetched"]
                crawl_run.urls_failed = stats["urls_failed"]
                crawl_run.status = "completed"
                crawl_run.finished_at = datetime.utcnow()
                session.commit()

                typer.echo(f"\n✓ Link graph build completed!")
                typer.echo(f"  URLs discovered: {stats['urls_discovered']}")
                typer.echo(f"  URLs fetched: {stats['urls_fetched']}")
                typer.echo(f"  URLs failed: {stats['urls_failed']}")
                typer.echo(f"  Max depth reached: {stats['max_depth_reached']}")
                typer.echo(f"\nCrawl run ID: {crawl_run.crawl_run_id}")
                typer.echo(f"\nNext step: Run classification with:")
                typer.echo(f"  grundrisse-ingest crawl-classify {crawl_run.crawl_run_id}")

            except Exception as e:
                crawl_run.status = "failed"
                crawl_run.error_log = str(e)
                crawl_run.finished_at = datetime.utcnow()
                session.commit()
                typer.echo(f"✗ Crawl resume failed: {e}", err=True)
                raise


@app.command("crawl-classify")
def crawl_classify(
    crawl_run_id: str = typer.Argument(..., help="Crawl run ID from build-graph"),
    *,
    budget_tokens: int = typer.Option(50000, help="Token budget for classification"),
    strategy: str = typer.Option("leaf_to_root", help="Classification strategy"),
    max_nodes_per_call: int = typer.Option(20, help="Base batch size per LLM call (will be 3x at shallow depths)"),
    no_content_samples: bool = typer.Option(False, help="Don't include page content in prompts"),
) -> None:
    """
    Phase 2: Progressive LLM-powered classification with budget control.

    Strategies:
      - leaf_to_root: Start at deepest pages, classify upward (RECOMMENDED)
      - root_to_leaf: Start at root, classify downward (not yet implemented)

    Can be run multiple times with different budgets to continue classification.

    Example:
        grundrisse-ingest crawl-classify abc-123-def --budget-tokens 100000
    """
    from grundrisse_core.db.models import ClassificationRun, CrawlRun
    from ingest_service.crawl.progressive_classifier import ProgressiveClassifier

    crawl_run_uuid = uuid.UUID(crawl_run_id)

    # Import LLM client (adjust this based on your setup)
    try:
        from nlp_pipeline.llm.zai_glm import ZaiGlmClient
        from nlp_pipeline.settings import settings as nlp_settings

        if not nlp_settings.zai_api_key:
            typer.echo("Error: GRUNDRISSE_ZAI_API_KEY not set", err=True)
            raise typer.Exit(1)

        llm_client = ZaiGlmClient(
            api_key=nlp_settings.zai_api_key,
            base_url=nlp_settings.zai_base_url,
            model=nlp_settings.zai_model,
        )
    except ImportError:
        typer.echo("Error: Could not import LLM client. Is nlp_pipeline installed?", err=True)
        raise typer.Exit(1)

    with SessionLocal() as session:
        # Get crawl run
        crawl_run = session.get(CrawlRun, crawl_run_uuid)
        if not crawl_run:
            typer.echo(f"Crawl run not found: {crawl_run_id}", err=True)
            raise typer.Exit(1)

        # Create classification run
        class_run = ClassificationRun(
            crawl_run_id=crawl_run_uuid,
            strategy=strategy,
            budget_tokens=budget_tokens,
            tokens_used=0,
            model_name=nlp_settings.zai_model,
            prompt_version=ProgressiveClassifier.PROMPT_VERSION,
            started_at=datetime.utcnow(),
            status="running",
        )
        session.add(class_run)
        session.flush()

        typer.echo(f"Starting classification run: {class_run.run_id}")
        typer.echo(f"Strategy: {strategy}")
        typer.echo(f"Token budget: {budget_tokens:,}")

        # Create classifier
        classifier = ProgressiveClassifier(
            session=session,
            crawl_run_id=crawl_run_uuid,
            classification_run_id=class_run.run_id,
            llm_client=llm_client,
            budget_tokens=budget_tokens,
            model_name=nlp_settings.zai_model,
        )

        try:
            if strategy == "leaf_to_root":
                stats = classifier.classify_leaf_to_root(
                    max_nodes_per_call=max_nodes_per_call,
                    include_content_samples=not no_content_samples,
                )
            else:
                typer.echo(f"Strategy '{strategy}' not yet implemented", err=True)
                raise typer.Exit(1)

            typer.echo(f"\n✓ Classification completed!")
            typer.echo(f"  URLs classified: {stats['urls_classified']}")
            typer.echo(f"  LLM calls: {stats['llm_calls']}")
            typer.echo(f"  Errors: {stats['errors']}")
            typer.echo(f"  Tokens used: {class_run.tokens_used:,} / {budget_tokens:,}")
            typer.echo(f"  Status: {class_run.status}")

            if class_run.status == "budget_exceeded":
                typer.echo(f"\n⚠ Budget exceeded. Run again with more tokens to continue:")
                typer.echo(f"  grundrisse-ingest crawl-classify {crawl_run_id} --budget-tokens 50000")

            typer.echo(f"\nNext step: Review classifications with:")
            typer.echo(f"  grundrisse-ingest crawl-review {crawl_run_id}")

        except Exception as e:
            class_run.status = "failed"
            class_run.error_log = str(e)
            class_run.finished_at = datetime.utcnow()
            session.commit()
            typer.echo(f"✗ Classification failed: {e}", err=True)
            raise


@app.command("crawl-review")
def crawl_review(
    crawl_run_id: str = typer.Argument(..., help="Crawl run ID to review"),
    *,
    show_limit: int = typer.Option(20, help="Number of classified URLs to show"),
    group_by: str = typer.Option("work", help="Group by: work, author, page_type"),
) -> None:
    """
    Review classified URLs and show summary statistics.

    Example:
        grundrisse-ingest crawl-review abc-123-def --show-limit 50
    """
    from grundrisse_core.db.models import CrawlRun, UrlCatalogEntry
    from sqlalchemy import func, select

    crawl_run_uuid = uuid.UUID(crawl_run_id)

    with SessionLocal() as session:
        # Get crawl run
        crawl_run = session.get(CrawlRun, crawl_run_uuid)
        if not crawl_run:
            typer.echo(f"Crawl run not found: {crawl_run_id}", err=True)
            raise typer.Exit(1)

        # Get classification stats
        total_urls = session.execute(
            select(func.count(UrlCatalogEntry.url_id)).where(UrlCatalogEntry.crawl_run_id == crawl_run_uuid)
        ).scalar()

        classified = session.execute(
            select(func.count(UrlCatalogEntry.url_id))
            .where(UrlCatalogEntry.crawl_run_id == crawl_run_uuid)
            .where(UrlCatalogEntry.classification_status == "classified")
        ).scalar()

        typer.echo(f"Crawl Run: {crawl_run_id}")
        typer.echo(f"Total URLs: {total_urls}")
        typer.echo(f"Classified: {classified} ({classified / total_urls * 100:.1f}%)")
        typer.echo(f"Unclassified: {total_urls - classified}")

        # Get sample of classified URLs
        typer.echo(f"\nSample classifications (limit {show_limit}):")

        classified_urls = session.execute(
            select(UrlCatalogEntry)
            .where(UrlCatalogEntry.crawl_run_id == crawl_run_uuid)
            .where(UrlCatalogEntry.classification_status == "classified")
            .limit(show_limit)
        ).scalars().all()

        # Group by specified field
        from collections import defaultdict

        if group_by == "work":
            groups = defaultdict(list)
            for url in classified_urls:
                work_title = url.classification_result.get("work_title") if url.classification_result else None
                groups[work_title or "Unknown"].append(url)

            for work_title, urls in groups.items():
                typer.echo(f"\n  Work: {work_title}")
                for url in urls[:5]:  # Show max 5 per group
                    cls = url.classification_result or {}
                    typer.echo(f"    - {url.url_canonical}")
                    typer.echo(f"      Type: {cls.get('page_type')}, Author: {cls.get('author')}")

        elif group_by == "author":
            groups = defaultdict(list)
            for url in classified_urls:
                author = url.classification_result.get("author") if url.classification_result else None
                groups[author or "Unknown"].append(url)

            for author, urls in groups.items():
                typer.echo(f"\n  Author: {author}")
                for url in urls[:5]:
                    cls = url.classification_result or {}
                    typer.echo(f"    - {url.url_canonical}")
                    typer.echo(f"      Type: {cls.get('page_type')}, Work: {cls.get('work_title')}")

        else:  # page_type
            groups = defaultdict(list)
            for url in classified_urls:
                page_type = url.classification_result.get("page_type") if url.classification_result else None
                groups[page_type or "unknown"].append(url)

            for page_type, urls in groups.items():
                typer.echo(f"\n  Page Type: {page_type} ({len(urls)})")
                for url in urls[:3]:
                    typer.echo(f"    - {url.url_canonical}")


@app.command("crawl-reset-failed")
def crawl_reset_failed(
    crawl_run_id: str = typer.Argument(..., help="Crawl run ID to reset failed classifications"),
    *,
    reset_all: bool = typer.Option(False, help="Reset ALL classifications (not just failed)"),
) -> None:
    """
    Reset failed classifications back to unclassified status.

    Use this after a classification run fails (e.g., due to bugs) to retry classification.

    Example:
        grundrisse-ingest crawl-reset-failed f9fcd3be-4f8c-4495-9b0b-6ad758fb5a14
        grundrisse-ingest crawl-reset-failed f9fcd3be-4f8c-4495-9b0b-6ad758fb5a14 --reset-all
    """
    from grundrisse_core.db.models import CrawlRun, UrlCatalogEntry
    from sqlalchemy import func, select, update

    crawl_run_uuid = uuid.UUID(crawl_run_id)

    with SessionLocal() as session:
        # Get crawl run
        crawl_run = session.get(CrawlRun, crawl_run_uuid)
        if not crawl_run:
            typer.echo(f"Crawl run not found: {crawl_run_id}", err=True)
            raise typer.Exit(1)

        if reset_all:
            # Count ALL non-unclassified URLs
            count = session.execute(
                select(func.count(UrlCatalogEntry.url_id))
                .where(UrlCatalogEntry.crawl_run_id == crawl_run_uuid)
                .where(UrlCatalogEntry.classification_status != "unclassified")
            ).scalar()

            if count == 0:
                typer.echo("No classifications found to reset.")
                return

            typer.echo(f"Found {count:,} classifications (failed + classified)")
            typer.echo("Resetting ALL to unclassified status...")

            # Reset all to unclassified
            session.execute(
                update(UrlCatalogEntry)
                .where(UrlCatalogEntry.crawl_run_id == crawl_run_uuid)
                .where(UrlCatalogEntry.classification_status != "unclassified")
                .values(
                    classification_status="unclassified",
                    classification_result=None,
                    classification_run_id=None,
                )
            )

            session.commit()

            typer.echo(f"✓ Reset {count:,} URLs to unclassified status")
        else:
            # Count failed URLs only
            failed_count = session.execute(
                select(func.count(UrlCatalogEntry.url_id))
                .where(UrlCatalogEntry.crawl_run_id == crawl_run_uuid)
                .where(UrlCatalogEntry.classification_status == "failed")
            ).scalar()

            if failed_count == 0:
                typer.echo("No failed classifications found.")
                typer.echo("Tip: Use --reset-all to reset all classifications (including 'classified' status)")
                return

            typer.echo(f"Found {failed_count:,} failed classifications")
            typer.echo("Resetting to unclassified status...")

            # Reset failed to unclassified
            session.execute(
                update(UrlCatalogEntry)
                .where(UrlCatalogEntry.crawl_run_id == crawl_run_uuid)
                .where(UrlCatalogEntry.classification_status == "failed")
                .values(
                    classification_status="unclassified",
                    classification_result=None,
                    classification_run_id=None,
                )
            )

            session.commit()

            typer.echo(f"✓ Reset {failed_count:,} URLs to unclassified status")

        typer.echo(f"\nNow run classification again:")
        typer.echo(f"  grundrisse-ingest crawl-classify {crawl_run_id} --budget-tokens 100000")


@app.command("ingest-classified")
def ingest_classified(
    crawl_run_id: str = typer.Argument(..., help="Crawl run ID with classifications"),
    *,
    max_works: int = typer.Option(None, help="Maximum works to ingest (None = all)"),
    min_pages: int = typer.Option(1, help="Minimum pages per work to ingest"),
    test_mode: bool = typer.Option(False, help="Test mode: ingest first 5 works only"),
    skip_existing_check: bool = typer.Option(True, help="Skip checks for existing data (faster for fresh ingestion)"),
) -> None:
    """
    Ingest all classified works from a crawl run.

    This command:
    1. Queries for primary content work pages
    2. Groups by (author, work_title)
    3. Ingests each work into the database
    4. Extracts clean text from HTML

    Example:
        grundrisse-ingest ingest-classified f9fcd3be-4f8c-4495-9b0b-6ad758fb5a14
        grundrisse-ingest ingest-classified f9fcd3be-4f8c-4495-9b0b-6ad758fb5a14 --test-mode
    """
    from collections import defaultdict
    from grundrisse_core.db.models import UrlCatalogEntry
    from pathlib import Path

    crawl_run_uuid = uuid.UUID(crawl_run_id)

    with SessionLocal() as session:
        typer.echo(f"Loading classified URLs from crawl run {crawl_run_id}...")

        # Get all classified URLs
        classified_urls = session.execute(
            select(UrlCatalogEntry)
            .where(UrlCatalogEntry.crawl_run_id == crawl_run_uuid)
            .where(UrlCatalogEntry.classification_status == "classified")
        ).scalars().all()

        typer.echo(f"Found {len(classified_urls):,} classified URLs")

        # Filter for primary content work pages
        work_pages = []
        for url in classified_urls:
            result = url.classification_result or {}
            if result.get("is_primary_content") and result.get("page_type") == "work_page":
                work_pages.append(url)

        typer.echo(f"Filtered to {len(work_pages):,} primary content work pages")

        # Group by (author, work_title)
        works = defaultdict(list)
        for url in work_pages:
            result = url.classification_result
            author = result.get("author") or "Unknown"
            work_title = result.get("work_title") or "Untitled"
            language = result.get("language", "en")

            # Store with metadata
            works[(author, work_title, language)].append(url)

        # Filter by min_pages
        works = {k: v for k, v in works.items() if len(v) >= min_pages}

        typer.echo(f"Grouped into {len(works):,} unique works")
        typer.echo("")

        if test_mode:
            typer.echo("🧪 TEST MODE: Ingesting first 5 works only")
            works = dict(list(works.items())[:5])

        if max_works:
            works = dict(list(works.items())[:max_works])
            typer.echo(f"Limited to {len(works)} works (--max-works)")

        # Sort by page count (largest first) for better progress visibility
        sorted_works = sorted(works.items(), key=lambda x: len(x[1]), reverse=True)

        # Statistics
        stats = {
            "works_attempted": 0,
            "works_succeeded": 0,
            "works_failed": 0,
            "pages_ingested": 0,
        }

        typer.echo("=" * 80)
        typer.echo("STARTING INGESTION")
        typer.echo("=" * 80)
        typer.echo("")

        for (author, work_title, language), urls in sorted_works:
            stats["works_attempted"] += 1

            # Show progress
            typer.echo(f"[{stats['works_attempted']}/{len(sorted_works)}] {author} - {work_title} ({len(urls)} pages)")

            try:
                # Sort URLs for consistent ordering
                sorted_urls = sorted(urls, key=lambda u: u.url_canonical)

                # Ingest this work using existing logic
                # We'll adapt the ingest_work logic here
                started = datetime.utcnow()
                ingest_run_id = uuid.uuid4()

                # Build manifest
                manifest = {
                    "root_url": sorted_urls[0].url_canonical,
                    "urls": [u.url_canonical for u in sorted_urls],
                    "snapshots": [],
                    "started_at": started.isoformat(),
                }

                # Load snapshots from existing raw files
                for url_entry in sorted_urls:
                    if url_entry.raw_path and Path(url_entry.raw_path).exists():
                        raw_path = Path(url_entry.raw_path)
                        manifest["snapshots"].append({
                            "url": url_entry.url_canonical,
                            "sha256": url_entry.content_sha256,
                            "raw_path": str(raw_path),
                            "meta_path": None,
                            "content_type": url_entry.content_type or "text/html",
                        })

                if not manifest["snapshots"]:
                    typer.echo(f"  ⚠️  No raw HTML files found, skipping")
                    stats["works_failed"] += 1
                    continue

                manifest["finished_at"] = datetime.utcnow().isoformat()

                # Save manifest
                raw_dir = ingest_settings.data_dir / "raw"
                raw_dir.mkdir(parents=True, exist_ok=True)
                manifest_path = raw_dir / f"ingest_run_{ingest_run_id}.json"
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

                # Create database entries (using ingest_work logic)
                author_id = author_id_for(author)
                work_id = work_id_for(author_id=author_id, title=work_title)
                edition_id = edition_id_for(work_id=work_id, language=language, source_url=manifest["root_url"])

                _upsert_author(session, author_id=author_id, name_canonical=author)
                _upsert_work(session, work_id=work_id, author_id=author_id, title=work_title)

                ingest_run = IngestRun(
                    ingest_run_id=ingest_run_id,
                    pipeline_version="v0-classified",
                    git_commit_hash=None,
                    source_url=manifest["root_url"],
                    raw_object_key=str(manifest_path),
                    raw_checksum=sha256_text(manifest_path.read_text(encoding="utf-8")),
                    started_at=started,
                    finished_at=datetime.utcnow(),
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
                        source_url=manifest["root_url"],
                        ingest_run_id=ingest_run.ingest_run_id,
                    )
                    session.add(edition)
                else:
                    edition.ingest_run_id=ingest_run.ingest_run_id

                session.flush()

                # Load existing blocks/paragraphs (skip if fresh ingestion)
                if skip_existing_check:
                    existing_blocks_by_order = {}
                    existing_paras_by_order = {}
                    existing_para_ids_with_spans = set()
                else:
                    existing_blocks_by_order = _load_existing_blocks_by_order(session, edition_id=edition_id)
                    existing_paras_by_order = _load_existing_paragraphs_by_order(session, edition_id=edition_id)
                    existing_para_ids_with_spans = {
                        r[0]
                        for r in session.query(SentenceSpan.para_id)
                        .filter(SentenceSpan.edition_id == edition_id)
                        .distinct()
                        .all()
                    }

                created_spans = 0
                global_block_order = 0
                global_para_order = 0

                # Process each page
                for page_idx, page in enumerate(manifest["snapshots"]):
                    url = page["url"]
                    html = Path(page["raw_path"]).read_text(encoding="utf-8", errors="replace")
                    if edition.source_metadata is None and page_idx < 5:
                        header_meta = extract_marxists_header_metadata(html)
                        if header_meta is not None:
                            edition.source_metadata = _normalize_source_metadata(
                                header_meta,
                                source_url=manifest["root_url"],
                                raw_object_key=str(manifest_path),
                                raw_sha256=sha256_text(manifest_path.read_text(encoding="utf-8")),
                            )
                    parsed_blocks = parse_html_to_blocks(html)

                    for b in parsed_blocks:
                        block_type = _map_block_type(b.block_type)
                        block_subtype = _map_block_subtype(b.block_subtype)

                        author_override_id = None
                        if b.author_override_name:
                            author_override_id = author_id_for(b.author_override_name)
                            _upsert_author(session, author_id=author_override_id, name_canonical=b.author_override_name)

                        block_title = b.title
                        if block_title is None:
                            block_title = f"Page {page_idx + 1}"

                        path = f"{page_idx + 1}.{b.order_index + 1}"
                        existing_block = existing_blocks_by_order.get(global_block_order)
                        effective_subtype = _prefer_subtype(_infer_page_subtype(url), block_subtype)

                        if existing_block is not None:
                            block_id = existing_block.block_id
                        else:
                            text_block = TextBlock(
                                block_id=uuid.uuid4(),
                                edition_id=edition_id,
                                parent_block_id=None,
                                block_type=block_type,
                                block_subtype=effective_subtype,
                                title=block_title,
                                source_url=url,
                                order_index=global_block_order,
                                path=path,
                                author_id_override=author_override_id,
                                author_role=None,
                            )
                            session.add(text_block)
                            session.flush()
                            block_id = text_block.block_id

                        global_block_order += 1

                        for para_text in b.paragraphs:
                            normalized = para_text.strip()
                            if not normalized:
                                continue

                            para_hash = sha256_text(normalized)
                            existing_para = existing_paras_by_order.get(global_para_order)

                            if existing_para is not None:
                                para_id = existing_para.para_id
                            else:
                                paragraph = Paragraph(
                                    para_id=uuid.uuid4(),
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
                                para_id = paragraph.para_id

                            if para_id not in existing_para_ids_with_spans:
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
                                    created_spans += 1
                                existing_para_ids_with_spans.add(para_id)

                            global_para_order += 1

                session.flush()

                if created_spans:
                    _relink_spans_for_edition(session, edition_id=edition_id)

                ingest_run.status = "succeeded"

                # Don't commit yet - batch commits for performance
                stats["works_succeeded"] += 1
                stats["pages_ingested"] += len(manifest["snapshots"])

                typer.echo(f"  ✓ Success: {len(manifest['snapshots'])} pages, {created_spans} sentences")

            except Exception as e:
                stats["works_failed"] += 1
                typer.echo(f"  ✗ Failed: {str(e)[:100]}")
                session.rollback()
                continue

            # Batch commits every 50 works for performance
            if stats["works_attempted"] % 50 == 0:
                session.commit()
                typer.echo("")
                typer.echo(f"💾 Committed batch | Progress: {stats['works_succeeded']}/{stats['works_attempted']} works, {stats['pages_ingested']} pages")
                typer.echo("")
            # Progress update every 10 works
            elif stats["works_attempted"] % 10 == 0:
                typer.echo("")
                typer.echo(f"Progress: {stats['works_succeeded']}/{stats['works_attempted']} works, {stats['pages_ingested']} pages")
                typer.echo("")

        # Final commit for any remaining works
        if stats["works_succeeded"] % 50 != 0:
            session.commit()
            typer.echo("")
            typer.echo(f"💾 Final commit complete")

        # Final summary
        typer.echo("")
        typer.echo("=" * 80)
        typer.echo("INGESTION COMPLETE")
        typer.echo("=" * 80)
        typer.echo(f"Works attempted: {stats['works_attempted']}")
        typer.echo(f"Works succeeded: {stats['works_succeeded']}")
        typer.echo(f"Works failed: {stats['works_failed']}")
        typer.echo(f"Pages ingested: {stats['pages_ingested']}")
        typer.echo("")

        if stats["works_succeeded"] > 0:
            typer.echo("✓ Data is now in the database and ready for querying/export!")
        if stats["works_failed"] > 0:
            typer.echo(f"⚠️  {stats['works_failed']} works failed - check logs above")


@app.command("author-deduplicate")
def author_deduplicate(
    *,
    manual_only: bool = typer.Option(False, help="Only apply manual mappings"),
    llm_threshold: float = typer.Option(0.85, help="Similarity threshold for LLM clustering (0.0-1.0)"),
    dry_run: bool = typer.Option(False, help="Show proposed changes without applying them"),
    apply: bool = typer.Option(False, help="Apply the deduplication changes to the database"),
) -> None:
    """
    Deduplicate author names using manual mappings and LLM.

    Phase 1: Apply manual mappings from data/author_mappings_manual.yaml
    Phase 2: Use LLM to deduplicate remaining similar names

    Example:
        # Preview changes
        grundrisse-ingest author-deduplicate --dry-run

        # Apply manual mappings only
        grundrisse-ingest author-deduplicate --manual-only --apply

        # Apply both manual and LLM deduplication
        grundrisse-ingest author-deduplicate --apply
    """
    import yaml
    from pathlib import Path
    from collections import defaultdict
    from grundrisse_core.db.models import Author, Work
    from grundrisse_core.identity import author_id_for
    from nlp_pipeline.llm.zai_glm import ZaiGlmClient
    from nlp_pipeline.settings import settings as nlp_settings
    from ingest_service.author_dedup.clustering import cluster_similar_names
    from ingest_service.author_dedup.llm_dedup import LLMAuthorDeduplicator

    with SessionLocal() as session:
        typer.echo("=" * 80)
        typer.echo("AUTHOR DEDUPLICATION")
        typer.echo("=" * 80)
        typer.echo("")

        # Load all authors with work counts
        authors_with_counts = session.execute(
            select(Author.name_canonical, func.count(Work.work_id).label("work_count"))
            .join(Work, Author.author_id == Work.author_id)
            .group_by(Author.name_canonical)
            .order_by(func.count(Work.work_id).desc())
        ).all()

        author_names = [name for name, _ in authors_with_counts]
        work_counts = {name: count for name, count in authors_with_counts}

        typer.echo(f"Total unique authors: {len(author_names)}")
        typer.echo("")

        # Phase 1: Manual mappings
        mappings_file = Path("data/author_mappings_manual.yaml")
        manual_mappings = {}

        if mappings_file.exists():
            typer.echo("Phase 1: Loading manual mappings...")
            with open(mappings_file) as f:
                manual_data = yaml.safe_load(f) or {}

            for canonical, variants in manual_data.items():
                if variants:  # Skip if variants list is None/empty
                    for variant in variants:
                        manual_mappings[variant] = canonical

            typer.echo(f"  Loaded {len(manual_mappings)} manual mappings")
            typer.echo("")

        # Phase 2: LLM-based deduplication
        llm_mappings = {}

        if not manual_only:
            typer.echo("Phase 2: LLM-based clustering...")

            # Get names not already in manual mappings
            remaining_names = [
                name for name in author_names
                if name not in manual_mappings and name not in manual_mappings.values()
            ]

            typer.echo(f"  Clustering {len(remaining_names)} remaining authors...")
            clusters = cluster_similar_names(remaining_names, threshold=llm_threshold)

            typer.echo(f"  Found {len(clusters)} clusters to deduplicate")
            typer.echo("")

            if clusters:
                typer.echo("  Calling LLM to pick canonical forms...")
                llm_client = ZaiGlmClient(
                    api_key=nlp_settings.zai_api_key,
                    base_url=nlp_settings.zai_base_url,
                    model=nlp_settings.zai_model,
                )
                deduplicator = LLMAuthorDeduplicator(llm_client)

                llm_mappings = deduplicator.deduplicate_batch(clusters, show_progress=True)
                typer.echo(f"  Generated {len(llm_mappings)} LLM mappings")
                typer.echo("")

        # Combine mappings
        all_mappings = {**manual_mappings, **llm_mappings}

        if not all_mappings:
            typer.echo("No deduplication needed!")
            return

        # Show proposed changes
        typer.echo("=" * 80)
        typer.echo("PROPOSED CHANGES")
        typer.echo("=" * 80)
        typer.echo("")

        # Group by canonical name
        by_canonical = defaultdict(list)
        for variant, canonical in all_mappings.items():
            by_canonical[canonical].append(variant)

        total_works_affected = 0
        for canonical, variants in sorted(by_canonical.items(), key=lambda x: sum(work_counts.get(v, 0) for v in x[1]), reverse=True)[:50]:
            variant_works = sum(work_counts.get(v, 0) for v in variants)
            canonical_works = work_counts.get(canonical, 0)
            total_works = variant_works + canonical_works

            typer.echo(f"{canonical} ({total_works} works total)")
            for variant in variants:
                count = work_counts.get(variant, 0)
                typer.echo(f"  ← {variant} ({count} works)")
            typer.echo("")

            total_works_affected += variant_works

        typer.echo(f"Total mappings: {len(all_mappings)}")
        typer.echo(f"Total works affected: {total_works_affected}")
        typer.echo("")

        # Apply changes
        if apply and not dry_run:
            typer.echo("=" * 80)
            typer.echo("APPLYING CHANGES")
            typer.echo("=" * 80)
            typer.echo("")

            changes_applied = 0

            for variant, canonical in all_mappings.items():
                # Get or create canonical author
                canonical_author_id = author_id_for(canonical)
                canonical_author = session.get(Author, canonical_author_id)

                if canonical_author is None:
                    # Create canonical author
                    canonical_author = Author(
                        author_id=canonical_author_id,
                        name_canonical=canonical,
                    )
                    session.add(canonical_author)
                    session.flush()

                # Get variant author
                variant_author_id = author_id_for(variant)
                variant_author = session.get(Author, variant_author_id)

                if variant_author:
                    # Update all works to point to canonical author
                    session.execute(
                        Work.__table__.update()
                        .where(Work.author_id == variant_author_id)
                        .values(author_id=canonical_author_id)
                    )

                    # Delete variant author (now unused)
                    session.delete(variant_author)
                    changes_applied += 1

            session.commit()

            typer.echo(f"✓ Applied {changes_applied} author merges")
            typer.echo("")
            typer.echo("Deduplication complete!")

        elif dry_run:
            typer.echo("DRY RUN - No changes applied")
            typer.echo("Run with --apply to apply these changes")

        else:
            typer.echo("Add --apply flag to apply these changes")
            typer.echo("Add --dry-run flag to see full proposed changes")


@app.command("author-apply-mappings")
def author_apply_mappings(
    mapping_file: str = typer.Argument("data/author_mappings_comprehensive.yaml", help="Path to YAML mapping file"),
    *,
    dry_run: bool = typer.Option(False, help="Show proposed changes without applying"),
) -> None:
    """
    Apply author name mappings with full legal names and aliases.

    This command:
    1. Reads canonical names, display names, and aliases from YAML
    2. Creates/updates Author records with proper names
    3. Creates AuthorAlias entries for all variants
    4. Merges works from variant authors to canonical author
    5. Preserves all name variants for searching

    Example:
        grundrisse-ingest author-apply-mappings --dry-run
        grundrisse-ingest author-apply-mappings
    """
    import yaml
    from pathlib import Path
    from grundrisse_core.db.models import Author, AuthorAlias, Work
    from grundrisse_core.identity import author_id_for

    mapping_path = Path(mapping_file)
    if not mapping_path.exists():
        typer.echo(f"Error: Mapping file not found: {mapping_file}")
        raise typer.Exit(1)

    with open(mapping_path) as f:
        mappings = yaml.safe_load(f) or {}

    with SessionLocal() as session:
        typer.echo("=" * 80)
        typer.echo("AUTHOR MAPPINGS APPLICATION")
        typer.echo("=" * 80)
        typer.echo("")
        typer.echo(f"Loading mappings from: {mapping_file}")
        typer.echo(f"Found {len(mappings)} canonical authors")
        typer.echo("")

        stats = {
            "authors_updated": 0,
            "authors_merged": 0,
            "aliases_created": 0,
            "works_reassigned": 0,
        }

        for canonical_name, config in mappings.items():
            display_name = config.get("display", canonical_name)
            aliases = config.get("aliases", [])

            typer.echo(f"Processing: {canonical_name}")
            typer.echo(f"  Display: {display_name}")
            typer.echo(f"  Aliases: {len(aliases)}")

            if not dry_run:
                # Create sort name (Last, First Middle)
                name_parts = canonical_name.strip().split()
                if len(name_parts) > 1:
                    name_sort = f"{name_parts[-1]}, {' '.join(name_parts[:-1])}"
                else:
                    name_sort = canonical_name

                # Get or create canonical author
                canonical_author_id = author_id_for(canonical_name)
                canonical_author = session.get(Author, canonical_author_id)

                if canonical_author is None:
                    # Create new author
                    canonical_author = Author(
                        author_id=canonical_author_id,
                        name_canonical=canonical_name,
                        name_display=display_name,
                        name_sort=name_sort,
                    )
                    session.add(canonical_author)
                    stats["authors_updated"] += 1
                else:
                    # Update existing author
                    canonical_author.name_canonical = canonical_name
                    canonical_author.name_display = display_name
                    canonical_author.name_sort = name_sort
                    stats["authors_updated"] += 1

                session.flush()

                # If display name is different from canonical, treat it as an alias too
                all_aliases = list(aliases)
                if display_name != canonical_name and display_name not in all_aliases:
                    all_aliases.append(display_name)

                # Process each alias
                for alias in all_aliases:
                    # Check if this alias exists as a separate author
                    alias_author_id = author_id_for(alias)
                    alias_author = session.get(Author, alias_author_id)

                    if alias_author and alias_author_id != canonical_author_id:
                        # Merge: Reassign all works to canonical author
                        works_to_reassign = session.execute(
                            select(Work).where(Work.author_id == alias_author_id)
                        ).scalars().all()

                        for work in works_to_reassign:
                            work.author_id = canonical_author_id
                            stats["works_reassigned"] += 1

                        # Also update text_block.author_id_override references
                        from grundrisse_core.db.models import TextBlock
                        session.execute(
                            TextBlock.__table__.update()
                            .where(TextBlock.author_id_override == alias_author_id)
                            .values(author_id_override=canonical_author_id)
                        )

                        # Delete old author entry
                        session.delete(alias_author)
                        stats["authors_merged"] += 1

                    # Create alias entry
                    # Check if alias already exists
                    existing_alias = session.execute(
                        select(AuthorAlias)
                        .where(AuthorAlias.author_id == canonical_author_id)
                        .where(AuthorAlias.name_variant == alias)
                    ).scalars().first()

                    if not existing_alias:
                        # Determine variant type
                        variant_type = "abbreviation"
                        if "." in alias and len(alias.split()) <= 3:
                            variant_type = "initials"
                        elif alias != canonical_name and alias in canonical_name:
                            variant_type = "short_form"

                        alias_entry = AuthorAlias(
                            author_id=canonical_author_id,
                            name_variant=alias,
                            variant_type=variant_type,
                            source="manual_mapping",
                        )
                        session.add(alias_entry)
                        stats["aliases_created"] += 1

                session.commit()

            typer.echo("")

        typer.echo("=" * 80)
        typer.echo("SUMMARY")
        typer.echo("=" * 80)
        typer.echo(f"Authors updated: {stats['authors_updated']}")
        typer.echo(f"Authors merged: {stats['authors_merged']}")
        typer.echo(f"Aliases created: {stats['aliases_created']}")
        typer.echo(f"Works reassigned: {stats['works_reassigned']}")
        typer.echo("")

        if dry_run:
            typer.echo("DRY RUN - No changes applied")
        else:
            typer.echo("✓ Mappings applied successfully!")


@app.command("extract-publication-years")
def extract_publication_years(
    *,
    dry_run: bool = typer.Option(False, help="Show proposed changes without applying"),
    skip_if_finalized: bool = typer.Option(True, help="Skip works that already have a frozen first-publication date."),
) -> None:
    """
    Extract publication years from text_block source URLs and populate work.publication_date.

    Uses the year pattern /YYYY/ found in marxists.org URLs.
    Takes the minimum year across all editions of a work as the publication year.
    """
    import re

    year_pattern = re.compile(r"/(\d{4})/")

    with SessionLocal() as session:
        # Get all works with their text_block source URLs
        result = session.execute(
            select(
                Work.work_id,
                Work.title,
                func.array_agg(TextBlock.source_url.distinct()).label("urls"),
            )
            .select_from(Work)
            .join(Edition, Edition.work_id == Work.work_id)
            .join(TextBlock, TextBlock.edition_id == Edition.edition_id)
            .where(TextBlock.source_url.isnot(None))
            .group_by(Work.work_id, Work.title)
        )

        updated = 0
        skipped = 0
        no_year = 0

        for row in result:
            work_id = row.work_id
            title = row.title
            urls = row.urls or []

            # Extract all years from URLs
            years = set()
            for url in urls:
                if url:
                    match = year_pattern.search(url)
                    if match:
                        year = int(match.group(1))
                        # Sanity check: year should be reasonable (1500-2030)
                        if 1500 <= year <= 2030:
                            years.add(year)

            if not years:
                no_year += 1
                continue

            # Use minimum year (earliest publication)
            pub_year = min(years)

            # Update work
            work = session.get(Work, work_id)
            if work:
                if skip_if_finalized and session.get(WorkDateFinal, work_id) is not None:
                    skipped += 1
                    continue
                current = work.publication_date
                if current and current.get("year") == pub_year and current.get("method") == "heuristic_url_year":
                    skipped += 1
                    continue

                if not dry_run:
                    work.publication_date = {
                        "year": pub_year,
                        "precision": "year",
                        "method": "heuristic_url_year",
                        "confidence": 0.2,
                    }

                updated += 1
                if updated <= 20:
                    typer.echo(f"  {title[:50]}: {pub_year}")

        if not dry_run:
            session.commit()

        typer.echo("")
        typer.echo("=" * 60)
        typer.echo(f"Works updated: {updated}")
        typer.echo(f"Works skipped (already set): {skipped}")
        typer.echo(f"Works without extractable year: {no_year}")

        if dry_run:
            typer.echo("\nDRY RUN - No changes applied")


@app.command("resolve-publication-dates")
def resolve_publication_dates(
    *,
    limit: int = typer.Option(200, help="Max works to process."),
    title_contains: str | None = typer.Option(None, help="Only process works whose title contains this substring."),
    author_contains: str | None = typer.Option(None, help="Only process works whose author contains this substring."),
    work_id: str | None = typer.Option(None, help="Only process a specific work_id (UUID)."),
    only_missing: bool = typer.Option(True, help="Only process works with no publication_date.year set."),
    min_score: float = typer.Option(0.75, help="Minimum candidate score required to write publication_date."),
    force: bool = typer.Option(False, help="Overwrite existing publication_date.year if set."),
    upgrade_heuristic: bool = typer.Option(
        False,
        help="Process works whose publication_date.year is set but method is heuristic/unknown, and upgrade when confidence improves.",
    ),
    min_improvement: float = typer.Option(
        0.10,
        help="When upgrading an existing heuristic year, require at least this confidence improvement to overwrite (unless the year changes).",
    ),
    dry_run: bool = typer.Option(False, help="Show proposed updates without writing to DB."),
    sources: str = typer.Option(
        "marxists,wikidata,openlibrary",
        help="Comma-separated sources: marxists,wikidata,openlibrary.",
    ),
    crawl_delay_s: float = typer.Option(0.6, help="Delay between HTTP requests (seconds)."),
    max_cache_age_s: float = typer.Option(
        7 * 24 * 3600, help="Max cache age (seconds) before refetching."
    ),
    prefer_ingested_html: bool = typer.Option(
        True,
        help="For marxists.org sources, prefer already-ingested snapshots in `data/raw/` via Edition.ingest_run.raw_object_key (no HTTP).",
    ),
    ingested_html_max_pages: int = typer.Option(
        5, help="When reading a multi-page ingest manifest, scan up to N pages for a marxists header."
    ),
    persist_edition_source_metadata: bool = typer.Option(
        False, help="Persist extracted marxists header fields into edition.source_metadata (writes to DB)."
    ),
    progress_every: int = typer.Option(25, help="Print progress every N scanned works (0 disables)."),
) -> None:
    """
    Resolve Work publication dates using multiple online sources and store provenance evidence.

    Notes:
    - Requires network access at runtime for Wikidata/OpenLibrary/marxists.org HTML fetches.
    - Uses a disk cache under `data/cache/publication_dates/` to avoid repeat lookups.
    - Title mismatches are handled by generating title variants and scoring candidates.
    """
    import json
    from pathlib import Path

    from ingest_service.metadata.http_cached import CachedHttpClient
    from ingest_service.metadata.publication_date_resolver import PublicationDateCandidate, PublicationDateResolver

    _ = core_settings.database_url
    source_list = [s.strip() for s in sources.split(",") if s.strip()]
    cache_dir = Path(ingest_settings.data_dir) / "cache" / "publication_dates"

    run_id = uuid.uuid4()
    started = datetime.utcnow()
    run = WorkMetadataRun(
        run_id=run_id,
        pipeline_version="v0",
        git_commit_hash=None,
        strategy="publication_date_resolver_v1",
        params={
            "limit": limit,
            "only_missing": only_missing,
            "min_score": min_score,
            "force": force,
            "dry_run": dry_run,
            "crawl_delay_s": crawl_delay_s,
            "max_cache_age_s": max_cache_age_s,
        },
        sources=source_list,
        started_at=started,
        finished_at=None,
        status="started",
        error_log=None,
        works_scanned=0,
        works_updated=0,
        works_skipped=0,
        works_failed=0,
    )

    with SessionLocal() as session, CachedHttpClient(
        cache_dir=cache_dir,
        user_agent=ingest_settings.user_agent,
        timeout_s=ingest_settings.request_timeout_s,
        delay_s=crawl_delay_s,
        max_cache_age_s=max_cache_age_s,
    ) as http:
        session.add(run)
        # Commit early so `work_metadata_run` is durable: per-work error handling does `session.rollback()`,
        # and we never want that rollback to remove the run row (which evidence rows FK to).
        session.commit()

        # Pull candidate works with URLs for hinting.
        q = (
            select(
                Work.work_id,
                Work.title,
                Work.author_id,
                Author.name_canonical,
                Author.birth_year,
                Author.death_year,
                func.array_agg(TextBlock.source_url.distinct()).label("block_urls"),
                func.array_agg(Edition.source_url.distinct()).label("edition_urls"),
                func.array_agg(Edition.language.distinct()).label("languages"),
                func.array_agg(Edition.edition_id.distinct()).label("edition_ids"),
                func.array_agg(IngestRun.raw_object_key.distinct()).label("raw_object_keys"),
                func.array_agg(IngestRun.raw_checksum.distinct()).label("raw_checksums"),
            )
            .select_from(Work)
            .join(Author, Author.author_id == Work.author_id)
            .join(Edition, Edition.work_id == Work.work_id)
            .join(IngestRun, IngestRun.ingest_run_id == Edition.ingest_run_id)
            .join(TextBlock, TextBlock.edition_id == Edition.edition_id)
            .where(TextBlock.source_url.isnot(None))
            # Avoid grouping on JSON columns (publication_date) because Postgres JSON lacks equality.
            .group_by(Work.work_id, Work.title, Work.author_id, Author.name_canonical, Author.birth_year, Author.death_year)
        )
        if title_contains:
            q = q.where(Work.title.ilike(f"%{title_contains}%"))
        if author_contains:
            q = q.where(Author.name_canonical.ilike(f"%{author_contains}%"))
        if work_id:
            try:
                w_uuid = uuid.UUID(work_id)
            except Exception:
                raise typer.BadParameter(f"Invalid work_id UUID: {work_id!r}")
            q = q.where(Work.work_id == w_uuid)
        rows = session.execute(q.limit(limit)).all()

        work_ids = [r.work_id for r in rows]
        work_by_id = {
            w.work_id: w for w in session.scalars(select(Work).where(Work.work_id.in_(work_ids))).all()
        }

        resolver = PublicationDateResolver(http=http)

        updated = 0
        would_update = 0
        skipped = 0
        failed = 0
        scanned = 0

        for row in rows:
            scanned += 1
            if progress_every > 0 and (scanned == 1 or scanned % progress_every == 0):
                if dry_run:
                    typer.echo(
                        f"[pubdates] scanned={scanned} would_update={would_update} skipped={skipped} failed={failed}"
                    )
                else:
                    typer.echo(f"[pubdates] scanned={scanned} updated={updated} skipped={skipped} failed={failed}")
            work_id = row.work_id
            title = row.title
            author_name = row.name_canonical
            birth_year = row.birth_year
            death_year = row.death_year
            work_obj = work_by_id.get(work_id)
            current_pub = (work_obj.publication_date if work_obj else None) or {}
            current_year = current_pub.get("year") if isinstance(current_pub, dict) else None
            current_conf = current_pub.get("confidence") if isinstance(current_pub, dict) else None
            current_conf_f = float(current_conf) if isinstance(current_conf, (int, float)) else 0.0
            current_method = current_pub.get("method") if isinstance(current_pub, dict) else None
            current_method_norm = str(current_method or "").strip().lower()

            if not force:
                if upgrade_heuristic:
                    # If a year exists, only consider upgrading when the current value is heuristic/unknown.
                    if current_year is not None and current_method_norm not in {"", "heuristic_url_year"}:
                        skipped += 1
                        continue
                    # Otherwise: allow processing (missing year OR heuristic year).
                else:
                    # Backwards-compatible behavior: without --force, only process works missing a year.
                    if current_year is not None:
                        skipped += 1
                        continue
                    if only_missing and current_year is not None:
                        skipped += 1
                        continue

            urls = [u for u in (row.edition_urls or []) if u] + [u for u in (row.block_urls or []) if u]
            languages = [l for l in (row.languages or []) if l]
            language = languages[0] if languages else None

            author_alias_rows = session.execute(
                select(AuthorAlias.name_variant).where(AuthorAlias.author_id == row.author_id)
            ).all()
            author_aliases = [r[0] for r in author_alias_rows if isinstance(r[0], str)]

            # Prefer canonical display title for matching if present, but do not change work identity.
            display_title = title
            if work_obj and work_obj.title_canonical:
                display_title = work_obj.title_canonical

            title_variants = PublicationDateResolver.title_variants(title=display_title, url_hints=urls[:8])
            # Isolate per-work errors so transient HTTP failures don't abort long runs.
            try:
                with session.begin_nested():
                    local_candidate: PublicationDateCandidate | None = None
                    effective_sources = list(source_list)
                    if prefer_ingested_html and "marxists" in set(source_list):
                        local_candidate = _candidate_from_ingested_marxists_html(
                            raw_object_keys=[k for k in (row.raw_object_keys or []) if isinstance(k, str) and k],
                            max_pages=ingested_html_max_pages,
                            fallback_url=(urls[0] if urls else None),
                        )
                        # When enabled, never perform HTTP fetches for marxists; use snapshots only.
                        effective_sources = [s for s in effective_sources if s != "marxists"]

                    candidates = resolver.resolve(
                        author_name=author_name,
                        author_aliases=author_aliases,
                        author_birth_year=birth_year if isinstance(birth_year, int) else None,
                        author_death_year=death_year if isinstance(death_year, int) else None,
                        title=display_title,
                        title_variants=title_variants,
                        language=language,
                        source_urls=urls[:8],
                        sources=effective_sources,
                        max_candidates=8,
                    )
                    if local_candidate is not None:
                        candidates = [local_candidate, *candidates]

                    if persist_edition_source_metadata and local_candidate is not None:
                        _persist_edition_source_metadata_from_candidate(
                            session,
                            edition_ids=[eid for eid in (row.edition_ids or []) if isinstance(eid, uuid.UUID)],
                            candidate=local_candidate,
                        )

                    # Persist evidence for audit, even if we don't write back.
                    for cand in candidates[:8]:
                        raw_sha = None
                        if cand.raw_payload is not None:
                            raw_sha = sha256_text(json.dumps(cand.raw_payload, sort_keys=True))
                        session.add(
                            WorkMetadataEvidence(
                                evidence_id=uuid.uuid4(),
                                run_id=run_id,
                                work_id=work_id,
                                source_name=cand.source_name,
                                source_locator=cand.source_locator,
                                retrieved_at=datetime.utcnow(),
                                raw_payload=cand.raw_payload,
                                raw_sha256=raw_sha,
                                extracted=cand.date,
                                score=cand.score,
                                notes=cand.notes,
                            )
                        )

                    def source_rank(source_name: str) -> int:
                        s = str(source_name or "").strip().lower()
                        if s in {"marxists", "marxists_ingested_html"}:
                            return 0
                        if s == "wikidata":
                            return 1
                        if s == "openlibrary":
                            return 2
                        if s == "heuristic_url_year":
                            return 3
                        return 9

                    # Choose best candidate by source priority (marxists>wikidata>openlibrary), then score.
                    best: tuple[float, object] | None = None
                    for src_rank in (0, 1, 2, 3):
                        best_in_src: tuple[float, object] | None = None
                        for cand in candidates:
                            if source_rank(cand.source_name) != src_rank:
                                continue
                            if cand.score < min_score:
                                continue
                            if best_in_src is None or cand.score > best_in_src[0]:
                                best_in_src = (cand.score, cand)
                        if best_in_src is not None:
                            best = best_in_src
                            break

                    if best is None:
                        skipped += 1
                        continue

                    if dry_run:
                        cand = best[1]
                        proposed_year = cand.date.get("year")
                        should_write = True
                        if not force and current_year is not None:
                            # Upgrade path: only overwrite if better, or year differs.
                            if proposed_year == current_year:
                                should_write = best[0] >= current_conf_f + min_improvement
                            else:
                                should_write = True
                        if should_write:
                            typer.echo(
                                f'{author_name} — "{display_title[:70]}": {proposed_year} '
                                f'(score={best[0]:.2f}, source={cand.source_name}, method={cand.date.get("method")})'
                            )
                            would_update += 1
                        else:
                            skipped += 1
                        continue

                    work = session.get(Work, work_id)
                    if work is None:
                        skipped += 1
                        continue
                    cand = best[1]
                    new_pub = dict(cand.date)
                    new_pub["confidence"] = best[0]
                    new_pub["sources"] = source_list
                    proposed_year = new_pub.get("year")

                    should_write = True
                    if not force and current_year is not None:
                        if proposed_year == current_year:
                            should_write = best[0] >= current_conf_f + min_improvement
                        else:
                            should_write = True

                    if not should_write:
                        skipped += 1
                        continue

                    work.publication_date = new_pub
                    updated += 1
                    if updated <= 30 or (progress_every > 0 and updated % progress_every == 0):
                        typer.echo(
                            f'{author_name} — "{display_title[:70]}": {new_pub.get("year")} '
                            f'(score={best[0]:.2f}, source={cand.source_name}, method={new_pub.get("method")})'
                        )
            except Exception as exc:
                failed += 1
                # Persist a minimal error evidence record for audit/debug; keep run resumable.
                session.rollback()
                if session.get(WorkMetadataRun, run_id) is not None:
                    with session.begin_nested():
                        session.add(
                            WorkMetadataEvidence(
                                evidence_id=uuid.uuid4(),
                                run_id=run_id,
                                work_id=work_id,
                                source_name="resolver_error",
                                source_locator=None,
                                retrieved_at=datetime.utcnow(),
                                raw_payload={"error": str(exc)},
                                raw_sha256=sha256_text(str(exc)),
                                extracted={"error": str(exc)},
                                score=0.0,
                                notes="resolver exception (continuing)",
                            )
                        )
                typer.echo(f"[pubdates] ERROR work_id={work_id} title={title[:40]!r}: {exc}")

            if scanned % 25 == 0:
                session.commit()

        session.commit()

        run = session.get(WorkMetadataRun, run_id)
        if run is not None:
            run.finished_at = datetime.utcnow()
            run.status = "succeeded"
            run.works_scanned = scanned
            run.works_updated = updated
            run.works_skipped = skipped
            run.works_failed = failed
            # Keep the DB columns stable; store dry-run would-update count in params for audit.
            if isinstance(run.params, dict):
                run.params["dry_run_would_update"] = would_update
            session.commit()

        typer.echo("")
        typer.echo("=" * 60)
        typer.echo(f"Works scanned:  {scanned}")
        if dry_run:
            typer.echo(f"Works would update: {would_update}")
        else:
            typer.echo(f"Works updated:  {updated}")
        typer.echo(f"Works skipped:  {skipped}")
        typer.echo(f"Works failed:   {failed}")


@app.command("extract-marxists-source-metadata")
def extract_marxists_source_metadata(
    *,
    limit: int = typer.Option(2000, help="Max editions to scan."),
    only_missing: bool = typer.Option(True, help="Only process editions with NULL edition.source_metadata."),
    overwrite: bool = typer.Option(False, help="Overwrite existing edition.source_metadata."),
    max_pages: int = typer.Option(5, help="When reading a manifest, scan up to N pages for a header."),
    dry_run: bool = typer.Option(False, help="Show proposed updates without writing to DB."),
    progress_every: int = typer.Option(200, help="Print progress every N scanned editions (0 disables)."),
) -> None:
    """
    Backfill `edition.source_metadata` by parsing already-ingested marxists.org HTML snapshots in `data/raw/`.

    This is designed to be safe and fast:
    - No network calls.
    - Reads raw HTML/manifest paths referenced by `ingest_run.raw_object_key`.
    """
    _ = core_settings.database_url

    scanned = 0
    updated = 0
    skipped = 0
    failed = 0

    with SessionLocal() as session:
        q = (
            select(
                Edition.edition_id,
                Edition.source_url,
                Edition.source_metadata,
                IngestRun.raw_object_key,
            )
            .select_from(Edition)
            .join(IngestRun, IngestRun.ingest_run_id == Edition.ingest_run_id)
            .where(Edition.source_url.ilike("%marxists.org%"))
        )
        if only_missing and not overwrite:
            q = q.where(Edition.source_metadata.is_(None))

        rows = session.execute(q.limit(limit)).all()

        for row in rows:
            scanned += 1
            if progress_every > 0 and (scanned == 1 or scanned % progress_every == 0):
                typer.echo(
                    f"[marxists-meta] scanned={scanned} updated={updated} skipped={skipped} failed={failed}"
                )

            edition_id = row.edition_id
            source_url = row.source_url
            raw_object_key = row.raw_object_key

            try:
                header_meta = None
                chosen_sha = ""
                for page_url, sha, html in _iter_html_from_raw_object_key(raw_object_key, max_pages=max_pages):
                    header_meta = extract_marxists_header_metadata(html)
                    if header_meta:
                        chosen_sha = sha
                        break

                if not header_meta:
                    skipped += 1
                    continue

                if dry_run:
                    fields = header_meta.get("fields") if isinstance(header_meta, dict) else None
                    first_pub = None
                    if isinstance(fields, dict):
                        first_pub = fields.get("First Published") or fields.get("Published")
                    typer.echo(f"[marxists-meta] would_update edition_id={edition_id} url={source_url} first={first_pub!r}")
                    updated += 1
                    continue

                edition = session.get(Edition, edition_id)
                if edition is None:
                    skipped += 1
                    continue

                if edition.source_metadata is not None and not overwrite:
                    skipped += 1
                    continue

                edition.source_metadata = _merge_source_metadata(
                    None if overwrite else edition.source_metadata,
                    _normalize_source_metadata(
                        header_meta,
                        source_url=str(source_url),
                        raw_object_key=str(raw_object_key),
                        raw_sha256=str(chosen_sha),
                    ),
                )
                updated += 1

                if scanned % 200 == 0:
                    session.commit()
            except Exception:
                session.rollback()
                failed += 1

        session.commit()

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo(f"Editions scanned:  {scanned}")
    if dry_run:
        typer.echo(f"Editions would update: {updated}")
    else:
        typer.echo(f"Editions updated:  {updated}")
    typer.echo(f"Editions skipped:  {skipped}")
    typer.echo(f"Editions failed:   {failed}")


@app.command("materialize-marxists-header")
def materialize_marxists_header(
    *,
    limit: int = typer.Option(200000, help="Max editions to scan."),
    only_missing: bool = typer.Option(True, help="Only process editions with no edition_source_header row."),
    force: bool = typer.Option(False, help="Overwrite existing edition_source_header rows."),
    dry_run: bool = typer.Option(False, help="Show proposed writes without writing to DB."),
    progress_every: int = typer.Option(500, help="Print progress every N scanned editions (0 disables)."),
) -> None:
    """
    Materialize a normalized `edition_source_header` row from `edition.source_metadata` (no network).

    This provides a clean, query-friendly representation of marxists.org header fields (Written/Source/First Published/etc.)
    while keeping the raw fields/dates for provenance.
    """
    _ = core_settings.database_url

    from datetime import timezone

    scanned = 0
    updated = 0
    skipped = 0
    failed = 0

    with SessionLocal() as session:
        q = (
            select(Edition.edition_id, Edition.source_url, Edition.source_metadata)
            .where(Edition.source_url.ilike("%marxists.org%"))
            .order_by(Edition.edition_id)
        )
        rows = session.execute(q.limit(limit)).all()

        for row in rows:
            scanned += 1
            if progress_every > 0 and (scanned == 1 or scanned % progress_every == 0):
                msg = "would_update" if dry_run else "updated"
                typer.echo(f"[marxists-header] scanned={scanned} {msg}={updated} skipped={skipped} failed={failed}")

            edition_id = row.edition_id
            meta = row.source_metadata if isinstance(row.source_metadata, dict) else None
            if not meta:
                skipped += 1
                continue

            try:
                with session.begin_nested():
                    existing = session.get(EditionSourceHeader, edition_id)
                    if existing is not None and not force:
                        if only_missing:
                            skipped += 1
                            continue
                        skipped += 1
                        continue

                    # Only materialize for metadata that looks like the marxists extractor output.
                    source = meta.get("source")
                    if isinstance(source, str) and "marxists" not in source.lower():
                        skipped += 1
                        continue

                    fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
                    dates = meta.get("dates") if isinstance(meta.get("dates"), dict) else None
                    editorial_intro = meta.get("editorial_intro")

                    extracted_at = datetime.utcnow().replace(tzinfo=timezone.utc)
                    extracted_at_raw = meta.get("extracted_at")
                    if isinstance(extracted_at_raw, str):
                        try:
                            extracted_at = datetime.fromisoformat(extracted_at_raw.replace("Z", "+00:00"))
                        except Exception:
                            extracted_at = datetime.utcnow().replace(tzinfo=timezone.utc)

                    row_obj = existing or EditionSourceHeader(edition_id=edition_id)
                    row_obj.source_name = "marxists"
                    row_obj.extracted_at = extracted_at
                    row_obj.raw_object_key = meta.get("raw_object_key") if isinstance(meta.get("raw_object_key"), str) else None
                    row_obj.raw_sha256 = meta.get("raw_sha256") if isinstance(meta.get("raw_sha256"), str) else None
                    row_obj.raw_fields = fields if isinstance(fields, dict) else {}
                    row_obj.raw_dates = dates if isinstance(dates, dict) else None
                    row_obj.editorial_intro = editorial_intro if isinstance(editorial_intro, (dict, list)) else None

                    def _date_or_none(key: str) -> dict | None:
                        if not isinstance(dates, dict):
                            return None
                        d = dates.get(key)
                        if not isinstance(d, dict):
                            return None
                        # Only persist structured dates that actually have a year.
                        # This keeps DB-level nullability meaningful (count(col) reflects "has date").
                        if not isinstance(d.get("year"), int):
                            return None
                        return d

                    row_obj.written_date = _date_or_none("written")
                    row_obj.first_published_date = _date_or_none("first_published")
                    row_obj.published_date = _date_or_none("published")

                    row_obj.source_citation_raw = fields.get("Source") if isinstance(fields.get("Source"), str) else None
                    row_obj.translated_raw = fields.get("Translated") if isinstance(fields.get("Translated"), str) else None
                    row_obj.transcription_markup_raw = fields.get("Transcription/Markup") if isinstance(fields.get("Transcription/Markup"), str) else None
                    row_obj.public_domain_raw = fields.get("Public Domain") if isinstance(fields.get("Public Domain"), str) else None

                    if dry_run:
                        updated += 1
                        continue

                    session.add(row_obj)
                    updated += 1

            except Exception as exc:
                session.rollback()
                failed += 1
                typer.echo(f"[marxists-header] ERROR edition_id={edition_id}: {exc}")

        if not dry_run:
            session.commit()

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo(f"Editions scanned:  {scanned}")
    if dry_run:
        typer.echo(f"Editions would update: {updated}")
    else:
        typer.echo(f"Editions updated:  {updated}")
    typer.echo(f"Editions skipped:  {skipped}")
    typer.echo(f"Editions failed:   {failed}")


@app.command("derive-work-dates")
def derive_work_dates(
    *,
    limit: int = typer.Option(20000, help="Max works to scan."),
    only_missing: bool = typer.Option(True, help="Only process works with no work_date_derived row."),
    force: bool = typer.Option(False, help="Overwrite existing work_date_derived rows."),
    dry_run: bool = typer.Option(False, help="Show proposed derived rows without writing to DB."),
    progress_every: int = typer.Option(250, help="Print progress every N scanned works (0 disables)."),
) -> None:
    """
    Deterministically derive a multi-date bundle for each work from stored evidence only:
    - edition.source_metadata (ingested HTML header fields)
    - work_metadata_evidence (Wikidata/OpenLibrary/heuristics previously fetched)

    This command performs NO network access and can be safely re-run whenever the derivation policy changes.

    Display date policy:
    - prefer `first_publication_date`
    - else fall back to `written_date`
    The chosen field is stored as `work_date_derived.display_date_field`.
    """
    _ = core_settings.database_url

    from ingest_service.metadata.work_date_deriver import (
        adjust_candidates_for_author_lifespan,
        best_candidate,
        build_candidates_from_edition_source_metadata,
        build_candidates_from_work_metadata_evidence_row,
        derive_display_date,
    )

    run_id = uuid.uuid4()
    started = datetime.utcnow()
    run = WorkDateDerivationRun(
        run_id=run_id,
        pipeline_version="v0",
        git_commit_hash=None,
        strategy="derive_work_dates_v1",
        params={"limit": limit, "only_missing": only_missing, "force": force, "dry_run": dry_run},
        started_at=started,
        finished_at=None,
        status="started",
        error_log=None,
        works_scanned=0,
        works_derived=0,
        works_skipped=0,
        works_failed=0,
    )

    scanned = 0
    derived = 0
    skipped = 0
    failed = 0

    with SessionLocal() as session:
        session.add(run)
        session.commit()

        q = (
            select(
                Work.work_id,
                Work.title,
                Work.title_canonical,
                Work.author_id,
                Author.name_canonical,
                Author.birth_year,
                Author.death_year,
            )
            .select_from(Work)
            .join(Author, Author.author_id == Work.author_id)
            .order_by(Author.name_canonical, Work.title)
        )
        rows = session.execute(q.limit(limit)).all()

        for row in rows:
            scanned += 1
            if progress_every > 0 and (scanned == 1 or scanned % progress_every == 0):
                typer.echo(f"[derive-dates] scanned={scanned} derived={derived} skipped={skipped} failed={failed}")

            work_id = row.work_id
            title = row.title_canonical or row.title
            author_name = row.name_canonical
            birth_year = row.birth_year if isinstance(row.birth_year, int) else None
            death_year = row.death_year if isinstance(row.death_year, int) else None

            try:
                with session.begin_nested():
                    existing = session.get(WorkDateDerived, work_id)
                    if existing is not None and not force:
                        if only_missing:
                            skipped += 1
                            continue
                        # If not only-missing, we still skip unless force.
                        skipped += 1
                        continue

                    edition_rows = session.execute(
                        select(Edition.edition_id, Edition.source_url, Edition.source_metadata).where(
                            Edition.work_id == work_id
                        )
                    ).all()

                    all_candidates = []
                    for ed in edition_rows:
                        ed_id = str(ed.edition_id)
                        ed_url = ed.source_url
                        ed_meta = ed.source_metadata if isinstance(ed.source_metadata, dict) else None
                        for c in build_candidates_from_edition_source_metadata(
                            edition_id=ed_id, source_url=ed_url, source_metadata=ed_meta
                        ):
                            all_candidates.append(c)

                    evidence_rows = session.execute(
                        select(
                            WorkMetadataEvidence.source_name,
                            WorkMetadataEvidence.score,
                            WorkMetadataEvidence.extracted,
                            WorkMetadataEvidence.raw_payload,
                            WorkMetadataEvidence.source_locator,
                        ).where(WorkMetadataEvidence.work_id == work_id)
                    ).all()
                    for ev in evidence_rows:
                        src = ev.source_name
                        score = ev.score
                        extracted = ev.extracted if isinstance(ev.extracted, dict) else None
                        raw_payload = ev.raw_payload if isinstance(ev.raw_payload, dict) else None
                        locator = ev.source_locator
                        for c in build_candidates_from_work_metadata_evidence_row(
                            source_name=src,
                            score=score,
                            extracted=extracted,
                            raw_payload=raw_payload,
                            source_locator=locator,
                        ):
                            all_candidates.append(c)

                    all_candidates = adjust_candidates_for_author_lifespan(
                        candidates=all_candidates,
                        birth_year=birth_year,
                        death_year=death_year,
                    )

                    candidates_by_role: dict[str, list] = {}
                    for c in all_candidates:
                        candidates_by_role.setdefault(c.role, []).append(c)

                    def pack(role: str) -> dict | None:
                        best = best_candidate(candidates_by_role.get(role, []))
                        if best is None:
                            return None
                        return {
                            "date": best.date,
                            "confidence": best.confidence,
                            "source": best.source_name,
                            "source_locator": best.source_locator,
                            "provenance": best.provenance,
                            "notes": best.notes,
                        }

                    bundle: dict = {
                        "first_publication_date": pack("first_publication_date"),
                        "written_date": pack("written_date"),
                        "edition_publication_date": pack("edition_publication_date"),
                        "heuristic_publication_year": pack("heuristic_publication_year"),
                        "ingest_upload_year": pack("ingest_upload_year"),
                    }

                    # Attach quick plausibility flags (do not reject; just record).
                    flags: dict[str, list[str]] = {"warnings": []}
                    fp = bundle.get("first_publication_date")
                    fp_year = None
                    if isinstance(fp, dict):
                        d = fp.get("date")
                        if isinstance(d, dict) and isinstance(d.get("year"), int):
                            fp_year = d["year"]
                    if fp_year is not None and death_year is not None and fp_year > death_year + 5:
                        flags["warnings"].append("first_publication_after_death")
                    if fp_year is not None and birth_year is not None and fp_year < birth_year - 10:
                        flags["warnings"].append("first_publication_before_birth")
                    if flags["warnings"]:
                        bundle["flags"] = flags

                    display_date, display_field, display_year = derive_display_date(bundle=bundle)

                    if dry_run:
                        typer.echo(
                            f'{author_name} — "{title[:70]}": '
                            f'{(display_date or {}).get("year")} (display={display_field})'
                        )
                        derived += 1
                        continue

                    row_obj = existing or WorkDateDerived(work_id=work_id)
                    row_obj.dates = bundle
                    row_obj.display_date = display_date
                    row_obj.display_date_field = display_field
                    row_obj.display_year = display_year
                    row_obj.derived_run_id = run_id
                    row_obj.derived_at = datetime.utcnow()
                    session.add(row_obj)
                    derived += 1

                if scanned % 500 == 0 and not dry_run:
                    session.commit()
            except Exception as exc:
                session.rollback()
                failed += 1
                typer.echo(f"[derive-dates] ERROR work_id={work_id} title={title[:40]!r}: {exc}")

        if not dry_run:
            session.commit()

        run = session.get(WorkDateDerivationRun, run_id)
        if run is not None:
            run.finished_at = datetime.utcnow()
            run.status = "succeeded"
            run.works_scanned = scanned
            run.works_derived = derived
            run.works_skipped = skipped
            run.works_failed = failed
            session.commit()

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo(f"Works scanned:  {scanned}")
    if dry_run:
        typer.echo(f"Works would derive: {derived}")
    else:
        typer.echo(f"Works derived:  {derived}")
    typer.echo(f"Works skipped:  {skipped}")
    typer.echo(f"Works failed:   {failed}")


@app.command("finalize-first-publication-dates")
def finalize_first_publication_dates(
    *,
    limit: int = typer.Option(2000, help="Max works to process."),
    min_score: float = typer.Option(0.85, help="Minimum candidate score required to finalize."),
    allow_heuristic: bool = typer.Option(
        False, help="Allow finalization from heuristic URL year if no better evidence exists."
    ),
    force: bool = typer.Option(False, help="Overwrite existing frozen dates (not recommended)."),
    dry_run: bool = typer.Option(False, help="Show proposed finalizations without writing."),
    confirm: bool = typer.Option(False, help="Required for non-dry-run; acknowledges this writes to the DB."),
    mirror_to_work: bool = typer.Option(
        False,
        help="Mirror finalized dates into work.publication_date (recommended only after validating WorkDateFinal output).",
    ),
    use_existing_evidence: bool = typer.Option(
        True,
        help="Finalize from existing work_metadata_evidence rows (fast, no network). Disable to refetch online sources.",
    ),
    crawl_delay_s: float = typer.Option(0.6, help="Delay between HTTP requests (seconds)."),
    progress_every: int = typer.Option(200, help="Print progress every N scanned works (0 disables)."),
    finalize_unknown: bool = typer.Option(
        False,
        help="Create WorkDateFinal rows with status=unknown when no evidence meets threshold (recommended for one-and-done runs).",
    ),
) -> None:
    """
    One-time finalizer for first-publication dates.

    Design:
    - Collect evidence candidates (marxists headers + verified catalog sources).
    - Finalize ONLY when confidence is high.
    - Persist results into `work_date_final`; optionally mirror into `work.publication_date` with method='final_first_publication'.
    - Never touch finalized rows unless --force.
    """
    import json
    from contextlib import nullcontext
    from pathlib import Path

    from ingest_service.metadata.http_cached import CachedHttpClient
    from ingest_service.metadata.publication_date_resolver import PublicationDateCandidate, PublicationDateResolver

    if not dry_run and not confirm:
        raise typer.BadParameter("Refusing to write without --confirm (use --dry-run first to inspect outputs).")

    _ = core_settings.database_url
    cache_dir = Path(ingest_settings.data_dir) / "cache" / "publication_dates"
    run_id = uuid.uuid4()
    started = datetime.utcnow()

    http_cm = (
        CachedHttpClient(
            cache_dir=cache_dir,
            user_agent=ingest_settings.user_agent,
            timeout_s=ingest_settings.request_timeout_s,
            delay_s=crawl_delay_s,
            max_cache_age_s=7 * 24 * 3600,
        )
        if not use_existing_evidence
        else None
    )

    with SessionLocal() as session, (http_cm or nullcontext()) as http:
        run = WorkMetadataRun(
            run_id=run_id,
            pipeline_version="v0",
            git_commit_hash=None,
            strategy="finalize_first_publication_v1",
            params={
                "limit": limit,
                "min_score": min_score,
                "allow_heuristic": allow_heuristic,
                "force": force,
                "dry_run": dry_run,
                "mirror_to_work": mirror_to_work,
                "use_existing_evidence": use_existing_evidence,
            },
            sources=["marxists", "wikidata", "openlibrary", "heuristic_url_year"],
            started_at=started,
            finished_at=None,
            status="started",
            error_log=None,
            works_scanned=0,
            works_updated=0,
            works_skipped=0,
            works_failed=0,
        )
        session.add(run)
        session.flush()

        resolver = PublicationDateResolver(http=http) if not use_existing_evidence else None

        # Load works with URLs.
        rows = session.execute(
            select(
                Work.work_id,
                Work.title,
                Work.author_id,
                Author.name_canonical,
                func.array_agg(Edition.source_url.distinct()).label("edition_urls"),
                func.array_agg(TextBlock.source_url.distinct()).label("block_urls"),
                func.array_agg(Edition.language.distinct()).label("languages"),
            )
            .select_from(Work)
            .join(Author, Author.author_id == Work.author_id)
            .join(Edition, Edition.work_id == Work.work_id)
            .join(TextBlock, TextBlock.edition_id == Edition.edition_id)
            .where(TextBlock.source_url.isnot(None))
            .group_by(Work.work_id, Work.title, Work.author_id, Author.name_canonical)
            .limit(limit)
        ).all()

        work_ids = [r.work_id for r in rows]
        work_by_id = {w.work_id: w for w in session.scalars(select(Work).where(Work.work_id.in_(work_ids))).all()}

        finalized_rows = 0
        finalized_with_date = 0
        finalized_unknown = 0
        would_finalize_rows = 0
        would_finalize_with_date = 0
        would_finalize_unknown = 0
        skipped = 0
        skipped_existing_non_unknown = 0
        skipped_no_candidate = 0
        failed = 0
        scanned = 0
        allowed_marxists_types = {"first_published", "publication_date", "published"}

        def derive_date_type(*, source_name: str, extracted: dict | None, notes: str | None) -> str | None:
            if source_name != "marxists":
                return None
            if isinstance(extracted, dict):
                dt = extracted.get("date_type")
                if isinstance(dt, str) and dt:
                    return dt
            # Back-compat: older runs stored tag prefixes in notes like "first_published:...".
            if isinstance(notes, str) and ":" in notes:
                prefix = notes.split(":", 1)[0].strip()
                if prefix:
                    return prefix
            return None

        def best_candidate_from_existing_evidence(*, work_id: uuid.UUID) -> tuple[PublicationDateCandidate | None, uuid.UUID | None]:
            ev_rows = session.execute(
                select(
                    WorkMetadataEvidence.evidence_id,
                    WorkMetadataEvidence.source_name,
                    WorkMetadataEvidence.source_locator,
                    WorkMetadataEvidence.extracted,
                    WorkMetadataEvidence.raw_payload,
                    WorkMetadataEvidence.score,
                    WorkMetadataEvidence.notes,
                )
                .where(WorkMetadataEvidence.work_id == work_id)
                .where(WorkMetadataEvidence.score.isnot(None))
                .order_by(WorkMetadataEvidence.score.desc())
                .limit(30)
            ).all()
            candidates: list[tuple[int, PublicationDateCandidate, uuid.UUID]] = []
            for ev in ev_rows:
                extracted = ev.extracted if isinstance(ev.extracted, dict) else None
                year = extracted.get("year") if extracted else None
                if not isinstance(year, int) or not (1500 <= year <= 2030):
                    continue
                date_type = derive_date_type(source_name=ev.source_name, extracted=extracted, notes=ev.notes)
                cand = PublicationDateCandidate(
                    date=dict(extracted or {}),
                    score=float(ev.score or 0.0),
                    source_name=ev.source_name,
                    source_locator=ev.source_locator,
                    raw_payload=ev.raw_payload if isinstance(ev.raw_payload, dict) else None,
                    notes=ev.notes,
                )
                # Apply finalization-time constraints for marxists candidates.
                if cand.source_name == "marxists":
                    if date_type not in allowed_marxists_types:
                        continue
                    cand.date["date_type"] = date_type
                candidates.append((source_rank(cand), cand, ev.evidence_id))

            if not candidates:
                return None, None

            # Prefer marxists > wikidata > openlibrary > heuristic; then by score.
            candidates.sort(key=lambda t: (t[0], -t[1].score))
            for _, cand, ev_id in candidates:
                if cand.source_name == "heuristic_url_year" and not allow_heuristic:
                    continue
                if cand.score >= min_score:
                    return cand, ev_id
            return None, None

        def source_rank(c: PublicationDateCandidate) -> int:
            if c.source_name in {"marxists", "marxists_ingested_html"}:
                return 0
            if c.source_name == "wikidata":
                return 1
            if c.source_name == "openlibrary":
                return 2
            if c.source_name == "heuristic_url_year":
                return 3
            return 9

        for row in rows:
            scanned += 1
            if progress_every > 0 and (scanned == 1 or scanned % progress_every == 0):
                typer.echo(
                    f"[finalize] scanned={scanned} finalized={finalized_with_date} unknown={finalized_unknown} "
                    f"skipped={skipped} failed={failed}"
                )

            work_id = row.work_id
            title = row.title
            author_name = row.name_canonical
            work_obj = work_by_id.get(work_id)

            # Isolate per-work errors so a single bad page/evidence flush doesn't abort the full run.
            try:
                with session.begin_nested():
                    existing_final = session.get(WorkDateFinal, work_id)
                    if existing_final is not None and not force:
                        # Allow upgrading placeholder unknown rows without requiring --force.
                        status_norm = str(getattr(existing_final, "status", "") or "").strip().lower()
                        if status_norm not in {"unknown", "heuristic"}:
                            skipped += 1
                            skipped_existing_non_unknown += 1
                            continue
                        # Continue processing so we can replace unknown with a finalized/heuristic date if possible.

                    urls = [u for u in (row.edition_urls or []) if u] + [u for u in (row.block_urls or []) if u]
                    language = (row.languages or [None])[0]

                    display_title = work_obj.title_canonical if (work_obj and work_obj.title_canonical) else title
                    best: PublicationDateCandidate | None = None
                    best_evidence_id: uuid.UUID | None = None

                    if use_existing_evidence:
                        best, best_evidence_id = best_candidate_from_existing_evidence(work_id=work_id)
                        # Optional fallback: use already-populated heuristic URL-year as a low-confidence "done" value.
                        if best is None and allow_heuristic and work_obj and isinstance(work_obj.publication_date, dict):
                            h_year = work_obj.publication_date.get("year")
                            h_method = work_obj.publication_date.get("method")
                            # Some historical runs stored the URL-derived year without a method marker; treat these as
                            # heuristic if we don't have better evidence.
                            method_norm = str(h_method or "").strip().lower()
                            if isinstance(h_year, int) and 1500 <= h_year <= 2030 and method_norm in {"", "heuristic_url_year"}:
                                best = PublicationDateCandidate(
                                    date={
                                        "year": h_year,
                                        "precision": "year",
                                        "method": "heuristic_url_year",
                                        "retrieved_at": datetime.utcnow().isoformat(),
                                    },
                                    score=0.20,
                                    source_name="heuristic_url_year",
                                    source_locator=None,
                                    raw_payload={"year": h_year, "method": h_method},
                                    notes="Fallback from existing work.publication_date (heuristic_url_year).",
                                )
                                best_evidence_id = None
                    else:
                        if resolver is None:
                            raise RuntimeError("Internal error: resolver not initialized.")

                        # Evidence candidates from resolver.
                        author_alias_rows = session.execute(
                            select(AuthorAlias.name_variant).where(AuthorAlias.author_id == row.author_id)
                        ).all()
                        author_aliases = [r[0] for r in author_alias_rows if isinstance(r[0], str)]

                        title_variants = PublicationDateResolver.title_variants(title=display_title, url_hints=urls[:8])

                        candidates = resolver.resolve(
                            author_name=author_name,
                            author_aliases=author_aliases,
                            title=display_title,
                            title_variants=title_variants,
                            language=language,
                            source_urls=urls[:8],
                            sources=["marxists", "wikidata", "openlibrary"],
                            max_candidates=8,
                        )

                        # Add heuristic candidate from existing year (usually URL-derived) as evidence only.
                        heuristic_year = None
                        if work_obj and isinstance(work_obj.publication_date, dict):
                            heuristic_year = work_obj.publication_date.get("year")
                        if isinstance(heuristic_year, int) and 1500 <= heuristic_year <= 2030:
                            candidates.append(
                                PublicationDateCandidate(
                                    date={
                                        "year": heuristic_year,
                                        "precision": "year",
                                        "method": "heuristic_url_year",
                                        "retrieved_at": datetime.utcnow().isoformat(),
                                    },
                                    score=0.20,
                                    source_name="heuristic_url_year",
                                    source_locator=None,
                                    raw_payload={"year": heuristic_year},
                                    notes="Existing work.publication_date.year without provenance (treated as heuristic).",
                                )
                            )

                        # Persist evidence rows for this run.
                        evidence_for_cand: dict[int, uuid.UUID] = {}
                        for cand in candidates[:8]:
                            raw_sha = None
                            if cand.raw_payload is not None:
                                raw_sha = sha256_text(json.dumps(cand.raw_payload, sort_keys=True))
                            ev_id = uuid.uuid4()
                            evidence_for_cand[id(cand)] = ev_id
                            session.add(
                                WorkMetadataEvidence(
                                    evidence_id=ev_id,
                                    run_id=run_id,
                                    work_id=work_id,
                                    source_name=cand.source_name,
                                    source_locator=cand.source_locator,
                                    retrieved_at=datetime.utcnow(),
                                    raw_payload=cand.raw_payload,
                                    raw_sha256=raw_sha,
                                    extracted=cand.date,
                                    score=cand.score,
                                    notes=cand.notes,
                                )
                            )

                        session.flush()

                        # Pick best from the candidates we just created.
                        for cand in candidates:
                            if (
                                cand.source_name == "marxists"
                                and cand.score >= min_score
                                and cand.date.get("date_type") in allowed_marxists_types
                            ):
                                best = cand
                                best_evidence_id = evidence_for_cand.get(id(cand))
                                break
                        if best is None:
                            for cand in candidates:
                                if cand.source_name == "wikidata" and cand.score >= min_score:
                                    best = cand
                                    best_evidence_id = evidence_for_cand.get(id(cand))
                                    break
                        if best is None:
                            for cand in candidates:
                                if cand.source_name == "openlibrary" and cand.score >= min_score:
                                    best = cand
                                    best_evidence_id = evidence_for_cand.get(id(cand))
                                    break
                        if best is None and allow_heuristic:
                            for cand in candidates:
                                if cand.source_name == "heuristic_url_year":
                                    best = cand
                                    best_evidence_id = evidence_for_cand.get(id(cand))
                                    break

                    if best is None and not finalize_unknown:
                        skipped += 1
                        skipped_no_candidate += 1
                        continue

                    if dry_run:
                        if best is not None:
                            typer.echo(
                                f'{author_name} — "{display_title[:70]}": {best.date.get("year")} '
                                f'(score={best.score:.2f}, source={best.source_name}, type={best.date.get("date_type")})'
                            )
                            would_finalize_rows += 1
                            would_finalize_with_date += 1
                        elif finalize_unknown:
                            would_finalize_rows += 1
                            would_finalize_unknown += 1
                        else:
                            skipped_no_candidate += 1
                        continue

                    # Write frozen row (and optionally mirror to work.publication_date).
                    final_row = existing_final or WorkDateFinal(work_id=work_id)
                    if best is None:
                        final_row.first_publication_date = None
                        final_row.precision = None
                        final_row.method = None
                        final_row.confidence = None
                        final_row.final_evidence_id = None
                        final_row.status = "unknown"
                        final_row.notes = "No evidence met threshold for first-publication date."
                        finalized_unknown += 1
                    else:
                        final_row.first_publication_date = {
                            "year": best.date.get("year"),
                            "month": best.date.get("month"),
                            "day": best.date.get("day"),
                        }
                        final_row.precision = best.date.get("precision") or "year"
                        final_row.method = best.date.get("method")
                        final_row.confidence = best.score
                        final_row.final_evidence_id = best_evidence_id
                        final_row.status = "finalized" if best.source_name != "heuristic_url_year" else "heuristic"
                        finalized_with_date += 1
                    final_row.finalized_run_id = run_id
                    final_row.finalized_at = datetime.utcnow()
                    session.add(final_row)

                    if mirror_to_work and work_obj is not None and best is not None:
                        work_obj.publication_date = {
                            "year": best.date.get("year"),
                            "precision": best.date.get("precision") or "year",
                            "method": "final_first_publication",
                            "confidence": best.score,
                            "finalized_run_id": str(run_id),
                            "final_evidence_id": str(best_evidence_id) if best_evidence_id else None,
                        }

                    finalized_rows += 1
                    if best is not None and (
                        finalized_with_date <= 30 or (progress_every > 0 and finalized_with_date % progress_every == 0)
                    ):
                        typer.echo(
                            f'[finalize] {author_name} — "{display_title[:70]}" → {best.date.get("year")} '
                            f"(source={best.source_name}, score={best.score:.2f})"
                        )
            except Exception as exc:
                failed += 1
                session.rollback()
                typer.echo(f"[finalize] ERROR work_id={work_id} title={title[:40]!r}: {exc}")

            if scanned % 100 == 0:
                session.commit()

        run.finished_at = datetime.utcnow()
        run.status = "succeeded"
        run.works_scanned = scanned
        run.works_updated = finalized_rows
        run.works_skipped = skipped
        run.works_failed = failed
        if isinstance(run.params, dict):
            run.params["finalized_with_date"] = finalized_with_date
            run.params["finalized_unknown"] = finalized_unknown
        session.commit()

        typer.echo("")
        typer.echo("=" * 60)
        typer.echo(f"Works scanned: {scanned}")
        if dry_run:
            typer.echo(f"Works would finalize (any): {would_finalize_rows}")
            typer.echo(f"Works would finalize (with date): {would_finalize_with_date}")
            typer.echo(f"Works would finalize (unknown): {would_finalize_unknown}")
        else:
            typer.echo(f"Works finalized (any): {finalized_rows}")
            typer.echo(f"Works finalized (with date): {finalized_with_date}")
            typer.echo(f"Works finalized (unknown): {finalized_unknown}")
        typer.echo(f"Works skipped: {skipped}")
        typer.echo(f"  skipped_existing_non_unknown: {skipped_existing_non_unknown}")
        typer.echo(f"  skipped_no_candidate: {skipped_no_candidate}")
        typer.echo(f"Works failed:  {failed}")

@app.command("resolve-author-lifespans")
def resolve_author_lifespans(
    *,
    limit: int = typer.Option(500, help="Max authors to process."),
    name_contains: str | None = typer.Option(None, help="Only process authors whose canonical name contains this substring."),
    author_id: str | None = typer.Option(None, help="Only process a specific author_id (UUID)."),
    only_missing: bool = typer.Option(True, help="Only process authors missing birth_year or death_year."),
    min_score: float = typer.Option(0.85, help="Minimum candidate score required to write years."),
    force: bool = typer.Option(False, help="Overwrite existing birth/death years if set."),
    dry_run: bool = typer.Option(False, help="Show proposed updates without writing to DB."),
    sources: str = typer.Option("wikidata", help="Comma-separated sources (currently: wikidata)."),
    crawl_delay_s: float = typer.Option(0.6, help="Delay between HTTP requests (seconds)."),
    max_cache_age_s: float = typer.Option(30 * 24 * 3600, help="Max cache age (seconds) before refetching."),
    progress_every: int = typer.Option(25, help="Print progress every N scanned authors (0 disables)."),
    max_year_conflict: int = typer.Option(
        25,
        help="If an existing year differs from the candidate by more than this, treat as a conflict and skip (unless --force).",
    ),
) -> None:
    """
    Resolve author birth/death years (lifespan) from online sources.

    This is used to improve plausibility checks for work publication-date resolution.
    """
    import json
    from pathlib import Path

    from ingest_service.metadata.author_lifespan_resolver import AuthorLifespanResolver
    from ingest_service.metadata.http_cached import CachedHttpClient

    _ = core_settings.database_url
    source_list = [s.strip() for s in sources.split(",") if s.strip()]
    cache_dir = Path(ingest_settings.data_dir) / "cache" / "author_lifespans"

    run_id = uuid.uuid4()
    started = datetime.utcnow()
    run = AuthorMetadataRun(
        run_id=run_id,
        pipeline_version="v0",
        git_commit_hash=None,
        strategy="author_lifespan_resolver_v1",
        params={
            "limit": limit,
            "only_missing": only_missing,
            "min_score": min_score,
            "force": force,
            "dry_run": dry_run,
            "crawl_delay_s": crawl_delay_s,
            "max_cache_age_s": max_cache_age_s,
        },
        sources=source_list,
        started_at=started,
        finished_at=None,
        status="started",
        error_log=None,
        authors_scanned=0,
        authors_updated=0,
        authors_skipped=0,
        authors_failed=0,
    )

    with SessionLocal() as session, CachedHttpClient(
        cache_dir=cache_dir,
        user_agent=ingest_settings.user_agent,
        timeout_s=ingest_settings.request_timeout_s,
        delay_s=crawl_delay_s,
        max_cache_age_s=max_cache_age_s,
    ) as http:
        session.add(run)
        session.flush()

        q = select(Author.author_id, Author.name_canonical, Author.birth_year, Author.death_year)
        if author_id:
            try:
                author_uuid = uuid.UUID(author_id)
            except Exception:
                raise typer.BadParameter(f"Invalid author_id UUID: {author_id!r}")
            q = q.where(Author.author_id == author_uuid)
        if name_contains:
            q = q.where(Author.name_canonical.ilike(f"%{name_contains}%"))
        authors = session.execute(q.limit(limit)).all()

        resolver = AuthorLifespanResolver(http=http)
        updated = 0
        would_update = 0
        skipped = 0
        failed = 0
        scanned = 0

        for row in authors:
            scanned += 1
            if progress_every > 0 and (scanned == 1 or scanned % progress_every == 0):
                typer.echo(f"[lifespans] scanned={scanned} updated={updated} skipped={skipped} failed={failed}")
            author_id = row.author_id
            name = row.name_canonical
            birth_year = row.birth_year
            death_year = row.death_year

            if only_missing and birth_year is not None and death_year is not None and not force:
                skipped += 1
                continue
            if not force and (birth_year is not None or death_year is not None) and not only_missing:
                skipped += 1
                continue

            alias_rows = session.execute(
                select(AuthorAlias.name_variant).where(AuthorAlias.author_id == author_id)
            ).all()
            aliases = [r[0] for r in alias_rows if isinstance(r[0], str)]

            candidates = resolver.resolve(
                author_name=name,
                author_aliases=aliases,
                sources=source_list,
                max_candidates=6,
            )

            for cand in candidates[:6]:
                raw_sha = None
                if cand.raw_payload is not None:
                    raw_sha = sha256_text(json.dumps(cand.raw_payload, sort_keys=True))
                session.add(
                    AuthorMetadataEvidence(
                        evidence_id=uuid.uuid4(),
                        run_id=run_id,
                        author_id=author_id,
                        source_name=cand.source_name,
                        source_locator=cand.source_locator,
                        retrieved_at=datetime.utcnow(),
                        raw_payload=cand.raw_payload,
                        raw_sha256=raw_sha,
                        extracted={
                            "birth_year": cand.birth_year,
                            "death_year": cand.death_year,
                            "retrieved_at": datetime.utcnow().isoformat(),
                            "method": "wikidata_p569_p570",
                        },
                        score=cand.score,
                        notes=cand.notes,
                    )
                )

            best = candidates[0] if candidates else None
            if best is None or best.score < min_score:
                skipped += 1
                continue

            # If we already have years and the candidate conflicts strongly, do not overwrite implicitly.
            if not force:
                if birth_year is not None and best.birth_year is not None:
                    if abs(int(birth_year) - int(best.birth_year)) > max_year_conflict:
                        skipped += 1
                        continue
                if death_year is not None and best.death_year is not None:
                    if abs(int(death_year) - int(best.death_year)) > max_year_conflict:
                        skipped += 1
                        continue

            if dry_run:
                typer.echo(f"{name}: {best.birth_year}-{best.death_year} (score={best.score:.2f})")
                would_update += 1
                continue

            try:
                a = session.get(Author, author_id)
                if a is None:
                    skipped += 1
                    continue
                changed = False
                if force or a.birth_year is None:
                    if best.birth_year is not None and a.birth_year != best.birth_year:
                        a.birth_year = best.birth_year
                        changed = True
                if force or a.death_year is None:
                    if best.death_year is not None and a.death_year != best.death_year:
                        a.death_year = best.death_year
                        changed = True
                if changed:
                    updated += 1
                else:
                    skipped += 1
                if updated <= 30 or (progress_every > 0 and updated % progress_every == 0):
                    typer.echo(f"{name}: {best.birth_year}-{best.death_year} (score={best.score:.2f})")
            except Exception as exc:
                failed += 1
                typer.echo(f"ERROR author_id={author_id}: {exc}")

            if scanned % 25 == 0:
                session.commit()

        session.commit()

        run = session.get(AuthorMetadataRun, run_id)
        if run is not None:
            run.finished_at = datetime.utcnow()
            run.status = "succeeded"
            run.authors_scanned = scanned
            run.authors_updated = updated
            run.authors_skipped = skipped
            run.authors_failed = failed
            if isinstance(run.params, dict):
                run.params["dry_run_would_update"] = would_update
            session.commit()

        typer.echo("")
        typer.echo("=" * 60)
        typer.echo(f"Authors scanned:  {scanned}")
        if dry_run:
            typer.echo(f"Authors would update: {would_update}")
        else:
            typer.echo(f"Authors updated:  {updated}")
        typer.echo(f"Authors skipped:  {skipped}")
        typer.echo(f"Authors failed:   {failed}")


@app.command("canonicalize-work-titles")
def canonicalize_work_titles(
    *,
    limit: int = typer.Option(5000, help="Max works to scan."),
    only_missing: bool = typer.Option(True, help="Only fill title_canonical when it is NULL."),
    dry_run: bool = typer.Option(False, help="Show proposed changes without writing."),
    progress_every: int = typer.Option(500, help="Print progress every N scanned works (0 disables)."),
) -> None:
    """
    Populate `work.title_canonical` for display/search without changing Work identity.

    This is safe because work_id generation uses `work.title` (raw).
    """
    _ = core_settings.database_url
    with SessionLocal() as session:
        rows = session.execute(select(Work).limit(limit)).scalars().all()
        scanned = 0
        filled = 0
        changed = 0
        skipped = 0
        for w in rows:
            scanned += 1
            if progress_every > 0 and (scanned == 1 or scanned % progress_every == 0):
                typer.echo(f"[titles] scanned={scanned} filled={filled} changed={changed} skipped={skipped}")

            if only_missing and w.title_canonical is not None:
                skipped += 1
                continue
            was_missing = w.title_canonical is None
            canon = canonicalize_title(w.title)
            if canon == (w.title_canonical or ""):
                skipped += 1
                continue
            if dry_run:
                typer.echo(f"{w.title[:60]} -> {canon[:60]}")
                if was_missing:
                    filled += 1
                else:
                    changed += 1
                continue
            w.title_canonical = canon
            if was_missing:
                filled += 1
            else:
                changed += 1
            if scanned % 500 == 0:
                session.commit()
        if not dry_run:
            session.commit()
        typer.echo("")
        typer.echo("=" * 60)
        typer.echo(f"Works scanned: {scanned}")
        if dry_run:
            typer.echo(f"Works would fill: {filled}")
            typer.echo(f"Works would change: {changed}")
        else:
            typer.echo(f"Works filled: {filled}")
            typer.echo(f"Works changed: {changed}")
        typer.echo(f"Works skipped: {skipped}")
