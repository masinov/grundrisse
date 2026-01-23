#!/usr/bin/env python3
"""
Investigation helper - loads work details for manual research
"""
import json
import sys
from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import Work, Author, Edition, Paragraph, WorkDateDerived
from sqlalchemy import select

def investigate_work(work_id: str):
    """Load all details for a work to aid manual investigation"""
    with SessionLocal() as session:
        # Get work
        work = session.get(Work, work_id)
        if not work:
            print(f"Work {work_id} not found")
            return

        # Get author
        author = session.get(Author, work.author_id)

        # Get edition
        edition = session.execute(
            select(Edition).where(Edition.work_id == work_id).limit(1)
        ).scalar_one_or_none()

        # Get derived date
        derived = session.get(WorkDateDerived, work_id)

        # Get first few paragraphs of text
        paragraphs = session.execute(
            select(Paragraph)
            .where(Paragraph.edition_id == edition.edition_id if edition else None)
            .limit(5)
        ).scalars().all() if edition else []

        print("="*80)
        print(f"WORK: {work.title}")
        print("="*80)
        print(f"Work ID: {work_id}")
        print(f"Author: {author.name_canonical if author else 'Unknown'}")
        if author:
            print(f"  Birth: {author.birth_year}, Death: {author.death_year}")
        print(f"Work Type: {work.work_type}")
        print()

        if edition:
            print(f"Edition URL: {edition.source_url}")
            print()

            if edition.source_metadata:
                print("SOURCE METADATA:")
                print(json.dumps(edition.source_metadata, indent=2))
                print()

        if derived:
            print("DERIVED DATE INFO:")
            print(f"  display_date_field: {derived.display_date_field}")
            if derived.display_date:
                print(f"  display_date: {json.dumps(derived.display_date, indent=2)}")
            print(f"  dates bundle keys: {list(derived.dates.keys() if derived.dates else [])}")
            print()

        if work.publication_date:
            print("WORK.PUBLICATION_DATE:")
            print(json.dumps(work.publication_date, indent=2))
            print()

        if paragraphs:
            print("FIRST 5 PARAGRAPHS (text snippets):")
            for i, para in enumerate(paragraphs, 1):
                text = para.text_normalized[:200] + "..." if len(para.text_normalized) > 200 else para.text_normalized
                print(f"\n[Para {i}]")
                print(text)
            print()

        print("="*80)
        print("INVESTIGATION NOTES:")
        print("[ ] Check source_metadata for date clues")
        print("[ ] Read text for internal date references")
        print("[ ] Web search: Author + Title + 'publication date'")
        print("[ ] Check marxists.org URL for year hint")
        print("[ ] Record findings below")
        print("="*80)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python investigate_work.py <work_id>")
        sys.exit(1)

    investigate_work(sys.argv[1])
