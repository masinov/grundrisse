#!/usr/bin/env python3
"""
Batch investigation script - processes multiple works
"""
import json
import sys
from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import Work, Author, Edition, Paragraph, WorkDateDerived
from sqlalchemy import select

def investigate_work_brief(work_id: str):
    """Get brief summary of work for investigation"""
    with SessionLocal() as session:
        work = session.get(Work, work_id)
        if not work:
            return None

        author = session.get(Author, work.author_id)
        edition = session.execute(
            select(Edition).where(Edition.work_id == work_id).limit(1)
        ).scalar_one_or_none()

        derived = session.get(WorkDateDerived, work_id)

        # Get first 3 paragraphs
        paragraphs = session.execute(
            select(Paragraph)
            .where(Paragraph.edition_id == edition.edition_id if edition else None)
            .limit(3)
        ).scalars().all() if edition else []

        result = {
            "work_id": work_id,
            "title": work.title,
            "author": author.name_canonical if author else "Unknown",
            "author_death": author.death_year if author else None,
            "url": edition.source_url if edition else None,
            "work_pub_date": work.publication_date,
            "source_metadata": edition.source_metadata if edition else None,
            "paragraphs": [p.text_normalized[:300] for p in paragraphs[:3]]
        }

        return result

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python batch_investigate.py <work_id>")
        sys.exit(1)

    result = investigate_work_brief(sys.argv[1])
    if result:
        print(json.dumps(result, indent=2))
    else:
        print(f"Work {sys.argv[1]} not found")
