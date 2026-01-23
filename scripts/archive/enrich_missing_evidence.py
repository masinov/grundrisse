#!/usr/bin/env python3
"""
Targeted enrichment: query Wikidata/OpenLibrary for works lacking work_metadata_evidence.
Writes evidence rows without modifying work.publication_date.
"""
import time
import uuid
from datetime import datetime
from pathlib import Path

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import Work, Author, WorkMetadataRun, WorkMetadataEvidence, WorkDateDerived
from ingest_service.metadata.publication_date_resolver import PublicationDateResolver
from ingest_service.metadata.http_cached import CachedHttpClient
from ingest_service.settings import settings as ingest_settings
from sqlalchemy import select

def enrich_works_without_evidence(
    author_name_contains: str | None = None,
    limit: int = 100,
    sources: list[str] = None,
    crawl_delay_s: float = 0.8,
    dry_run: bool = False
):
    """
    Query external sources for works that have no work_metadata_evidence.
    
    Args:
        author_name_contains: Filter to author names containing this string
        limit: Max works to process
        sources: List of sources (wikidata, openlibrary)
        crawl_delay_s: Delay between HTTP requests
        dry_run: If True, don't write to database
    """
    if sources is None:
        sources = ['wikidata', 'openlibrary']
    
    cache_dir = Path(ingest_settings.data_dir) / "cache" / "publication_dates"
    
    # Create run record
    run_id = uuid.uuid4()
    run = WorkMetadataRun(
        run_id=run_id,
        pipeline_version="targeted_enrichment_v1",
        strategy="enrich_missing_evidence",
        params={
            "author_name_contains": author_name_contains,
            "limit": limit,
            "sources": sources,
            "crawl_delay_s": crawl_delay_s,
            "dry_run": dry_run,
        },
        sources=sources,
        started_at=datetime.utcnow(),
        status="started",
        works_scanned=0,
        works_updated=0,
        works_skipped=0,
        works_failed=0,
    )
    
    with SessionLocal() as session:
        if not dry_run:
            session.add(run)
            session.commit()
        
        # Find works without work_metadata_evidence
        stmt = (
            select(Work.work_id, Work.title, Author.name_canonical)
            .join(Author, Author.author_id == Work.author_id)
            .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
            .outerjoin(WorkMetadataEvidence, WorkMetadataEvidence.work_id == Work.work_id)
            .where(WorkDateDerived.display_date_field == 'unknown')
            .where(WorkMetadataEvidence.work_id.is_(None))
        )
        
        if author_name_contains:
            stmt = stmt.where(Author.name_canonical.like(f'%{author_name_contains}%'))
        
        stmt = stmt.limit(limit)
        
        works = session.execute(stmt).all()
        
        print(f"Found {len(works)} works without evidence")
        if dry_run:
            print("[DRY RUN MODE]")
        
        with CachedHttpClient(
            cache_dir=cache_dir,
            user_agent=ingest_settings.user_agent,
            timeout_s=ingest_settings.request_timeout_s,
            delay_s=crawl_delay_s,
            max_cache_age_s=7 * 24 * 3600,
        ) as http:
            resolver = PublicationDateResolver(http_client=http)
            
            for i, (work_id, title, author_name) in enumerate(works, 1):
                try:
                    print(f"\n[{i}/{len(works)}] {author_name}: {title[:50]}...")
                    
                    # Query sources
                    candidates = resolver.resolve_publication_date(
                        author_name=author_name,
                        title=title,
                        source_url_hint=None,
                        sources=sources,
                    )
                    
                    if not candidates:
                        print(f"  No candidates found")
                        run.works_scanned += 1
                        run.works_skipped += 1
                        continue
                    
                    print(f"  Found {len(candidates)} candidates")
                    
                    # Write evidence rows
                    if not dry_run:
                        for cand in candidates:
                            evidence = WorkMetadataEvidence(
                                evidence_id=uuid.uuid4(),
                                run_id=run_id,
                                work_id=work_id,
                                source_name=cand.source_name,
                                source_locator=cand.source_locator,
                                retrieved_at=datetime.utcnow(),
                                raw_payload=cand.provenance,
                                extracted={
                                    "year": cand.year,
                                    "precision": "year",
                                    "method": cand.method,
                                },
                                score=cand.score,
                                notes=f"Enrichment run: {run_id}",
                            )
                            session.add(evidence)
                        
                        session.commit()
                        print(f"  ✓ Wrote {len(candidates)} evidence rows")
                    else:
                        for cand in candidates:
                            print(f"    [{cand.source_name}] year={cand.year}, score={cand.score:.2f}")
                    
                    run.works_scanned += 1
                    run.works_updated += 1
                    
                except Exception as e:
                    print(f"  ERROR: {e}")
                    run.works_scanned += 1
                    run.works_failed += 1
                    if not dry_run:
                        session.rollback()
                    continue
        
        # Finalize run
        run.finished_at = datetime.utcnow()
        run.status = "completed"
        
        if not dry_run:
            session.commit()
        
        print(f"\n{'='*60}")
        print(f"Works scanned: {run.works_scanned}")
        print(f"Works with new evidence: {run.works_updated}")
        print(f"Works skipped (no candidates): {run.works_skipped}")
        print(f"Works failed: {run.works_failed}")


if __name__ == '__main__':
    import sys
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--author-contains', type=str, default=None)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--sources', type=str, default='wikidata,openlibrary')
    parser.add_argument('--crawl-delay-s', type=float, default=0.8)
    parser.add_argument('--dry-run', action='store_true')
    
    args = parser.parse_args()
    
    sources = [s.strip() for s in args.sources.split(',')]
    
    enrich_works_without_evidence(
        author_name_contains=args.author_contains,
        limit=args.limit,
        sources=sources,
        crawl_delay_s=args.crawl_delay_s,
        dry_run=args.dry_run,
    )
