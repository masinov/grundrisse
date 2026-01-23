#!/usr/bin/env python3
"""
Comprehensive corpus intelligence gathering.
Complete picture of metadata status across all 19,098 works.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Work, Author, Edition, WorkDateDerived, WorkMetadataEvidence,
    EditionSourceHeader, Paragraph, TextBlock
)
from sqlalchemy import select, func


def gather_corpus_intelligence():
    """Gather complete intelligence on the corpus metadata status."""

    with SessionLocal() as session:
        # Basic counts
        total_works = session.execute(select(func.count(Work.work_id))).scalar()
        total_authors = session.execute(select(func.count(Author.author_id))).scalar()
        total_editions = session.execute(select(func.count(Edition.edition_id))).scalar()

        # Derived date status
        derived_status = session.execute(
            select(
                WorkDateDerived.display_date_field,
                func.count(WorkDateDerived.work_id)
            ).group_by(WorkDateDerived.display_date_field)
        ).all()

        # Note: precision and confidence computed in Python to avoid SQL JSON issues

        # Author lifespan coverage
        author_lifespan = session.execute(
            select(
                func.count(Author.author_id),
                func.count(Author.birth_year),
                func.count(Author.death_year)
            )
        ).one()

        # Source metadata coverage
        metadata_coverage = session.execute(
            select(
                func.count(Edition.edition_id),
                func.count(Edition.source_metadata)
            ).select_from(Edition)
        ).one()

        # External evidence coverage
        evidence_coverage = session.execute(
            select(
                func.count(WorkMetadataEvidence.work_id.distinct())
            )
        ).scalar()

        # Works by author (for top authors)
        works_by_author = session.execute(
            select(
                Author.name_canonical,
                func.count(Work.work_id)
            ).join(Work)
            .group_by(Author.name_canonical)
            .order_by(func.count(Work.work_id).desc())
            .limit(20)
        ).all()

        # Unknown works by author
        unknown_by_author = session.execute(
            select(
                Author.name_canonical,
                func.count(Work.work_id)
            ).join(Work)
            .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
            .where(WorkDateDerived.display_date_field == "unknown")
            .group_by(Author.name_canonical)
            .order_by(func.count(Work.work_id).desc())
            .limit(20)
        ).all()

        # EditionSourceHeader coverage
        header_coverage = session.execute(
            select(
                func.count(EditionSourceHeader.edition_id),
                func.count(EditionSourceHeader.written_date),
                func.count(EditionSourceHeader.first_published_date),
                func.count(EditionSourceHeader.published_date)
            )
        ).one()

        # URL pattern analysis
        url_patterns = session.execute(
            select(
                TextBlock.source_url,
                func.count(TextBlock.block_id)
            )
            .where(TextBlock.source_url.isnot(None))
            .group_by(TextBlock.source_url)
            .limit(5)
        ).all()

        return {
            "total_works": total_works,
            "total_authors": total_authors,
            "total_editions": total_editions,
            "derived_date_status": dict(derived_status),
            "author_lifespan": {
                "total": author_lifespan[0],
                "with_birth": author_lifespan[1],
                "with_death": author_lifespan[2]
            },
            "metadata_coverage": {
                "total_editions": metadata_coverage[0],
                "with_metadata": metadata_coverage[1],
                "percentage": (metadata_coverage[1] / metadata_coverage[0] * 100) if metadata_coverage[0] > 0 else 0
            },
            "evidence_coverage": evidence_coverage,
            "works_by_top_author": dict(works_by_author),
            "unknown_by_author": dict(unknown_by_author),
            "header_coverage": {
                "total_headers": header_coverage[0],
                "with_written": header_coverage[1],
                "with_first_published": header_coverage[2],
                "with_published": header_coverage[3]
            },
            "sample_urls": [u[0] for u in url_patterns]
        }


def analyze_data_gaps():
    """Deep dive into specific data gaps."""
    import re

    with SessionLocal() as session:
        # Works with URL dates but marked unknown
        url_pattern_works = session.execute(
            select(
                Work.work_id,
                Work.title,
                Author.name_canonical,
                func.array_agg(TextBlock.source_url.distinct()).label("urls")
            )
            .select_from(Work)
            .join(Author)
            .join(Edition, Edition.work_id == Work.work_id)
            .join(TextBlock, TextBlock.edition_id == Edition.edition_id)
            .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
            .where(WorkDateDerived.display_date_field == "unknown")
            .where(TextBlock.source_url.op("~")(r"/\d{4}/"))
            .group_by(Work.work_id, Work.title, Author.name_canonical)
            .limit(20)
        ).all()

        # Works with source_metadata but no derived date
        meta_no_derived = session.execute(
            select(
                Work.work_id,
                Work.title,
                Author.name_canonical
            )
            .select_from(Work)
            .join(Author)
            .join(Edition, Edition.work_id == Work.work_id)
            .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
            .where(WorkDateDerived.display_date_field == "unknown")
            .where(Edition.source_metadata.isnot(None))
            .limit(20)
        ).all()

        # Works without external evidence
        no_external_evidence = session.execute(
            select(
                func.count(Work.work_id)
            )
            .select_from(Work)
            .outerjoin(WorkMetadataEvidence, WorkMetadataEvidence.work_id == Work.work_id)
            .where(WorkMetadataEvidence.evidence_id.is_(None))
        ).scalar()

        # Chapter-like URLs (likely missing metadata)
        chapter_urls = session.execute(
            select(
                func.count(TextBlock.block_id)
            )
            .where(TextBlock.source_url.op("~*")(r"(ch\d+|chapter|app\d+|pr\d+)"))
        ).scalar()

        return {
            "url_pattern_unknown_count": len(url_pattern_works),
            "url_pattern_unknown_sample": [
                {"title": r.title, "author": r.name_canonical, "urls": r.urls[:2]}
                for r in url_pattern_works[:10]
            ],
            "metadata_no_derived_sample": [
                {"title": r.title, "author": r.name_canonical}
                for r in meta_no_derived[:10]
            ],
            "works_without_external_evidence": no_external_evidence,
            "chapter_like_urls": chapter_urls
        }


def main():
    print("Gathering corpus intelligence...")
    intelligence = gather_corpus_intelligence()
    gaps = analyze_data_gaps()

    report = {
        "corpus_overview": intelligence,
        "data_gaps": gaps
    }

    out_path = Path("/mnt/c/Users/Datision/Documents/grundrisse/corpus_intelligence.json")
    out_path.write_text(json.dumps(report, indent=2, default=str))

    print(f"\n{'='*80}")
    print("CORPUS INTELLIGENCE REPORT")
    print(f"{'='*80}")
    print(f"\nTotal works: {intelligence['total_works']:,}")
    print(f"Total authors: {intelligence['total_authors']:,}")
    print(f"Total editions: {intelligence['total_editions']:,}")

    print(f"\nDerived Date Status:")
    for status, count in intelligence['derived_date_status'].items():
        pct = count / intelligence['total_works'] * 100
        print(f"  {status}: {count:,} ({pct:.1f}%)")

    print(f"\nAuthor Lifespan Coverage:")
    al = intelligence['author_lifespan']
    print(f"  Total authors: {al['total']:,}")
    print(f"  With birth year: {al['with_birth']:,} ({al['with_birth']/al['total']*100:.1f}%)")
    print(f"  With death year: {al['with_death']:,} ({al['with_death']/al['total']*100:.1f}%)")

    print(f"\nMetadata Coverage:")
    mc = intelligence['metadata_coverage']
    print(f"  Editions with source_metadata: {mc['with_metadata']:,}/{mc['total_editions']:,} ({mc['percentage']:.1f}%)")

    print(f"\nTop Authors with Unknown Dates:")
    for author, count in list(intelligence['unknown_by_author'].items())[:10]:
        print(f"  {author}: {count}")

    print(f"\nData Gaps:")
    print(f"  Works with URL dates but marked unknown: ~{gaps['url_pattern_unknown_count']:,}")
    print(f"  Works without external evidence: {gaps['works_without_external_evidence']:,}")
    print(f"  Chapter-like URLs: {gaps['chapter_like_urls']:,}")

    print(f"\nSaved full report to: {out_path}")


if __name__ == "__main__":
    main()
