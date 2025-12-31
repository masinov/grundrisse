from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

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
) -> None:
    """
    Phase 1: Build complete hyperlink graph without classification.

    This is the CHEAP phase - just HTTP requests to discover structure.
    No LLM calls yet. Output is a complete link graph in the database.
    
    Example:
        grundrisse-ingest crawl-build-graph https://www.marxists.org/ --max-depth 6
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
            },
            started_at=datetime.utcnow(),
            status="started",
        )
        session.add(crawl_run)
        session.flush()

        typer.echo(f"Starting crawl run: {crawl_run.crawl_run_id}")
        typer.echo(f"Building link graph from {seed_url}...")

        # Create HTTP client and graph builder
        with RateLimitedHttpClient(crawl_delay=crawl_delay) as http_client:
            builder = LinkGraphBuilder(
                session=session,
                crawl_run_id=crawl_run.crawl_run_id,
                http_client=http_client,
                data_dir=data_dir,
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


@app.command("crawl-classify")
def crawl_classify(
    crawl_run_id: str = typer.Argument(..., help="Crawl run ID from build-graph"),
    *,
    budget_tokens: int = typer.Option(50000, help="Token budget for classification"),
    strategy: str = typer.Option("leaf_to_root", help="Classification strategy"),
    max_nodes_per_call: int = typer.Option(15, help="Max nodes to classify per LLM call"),
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
