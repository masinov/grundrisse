#!/usr/bin/env python3
"""
Generate a representative stratified sample of 100 works with unknown dates.
Stratified by author to ensure diversity (max 3-5 works per author).
"""
import json
import uuid
from pathlib import Path

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import Work, Author, WorkDateDerived, Edition
from sqlalchemy import select, func


def generate_stratified_sample(limit: int = 100, max_per_author: int = 5) -> list:
    """
    Generate a stratified sample of works with unknown dates, ensuring:
    - No more than max_per_author works from any single author
    - Include different work types where possible
    - Include both short and long titles
    """
    with SessionLocal() as session:
        # Get all works with unknown dates
        stmt = (
            select(
                Work.work_id,
                Work.title,
                Work.title_canonical,
                Work.work_type,
                Author.author_id,
                Author.name_canonical,
                Author.birth_year,
                Author.death_year,
                func.array_agg(Edition.source_url).label("urls"),
            )
            .select_from(Work)
            .join(Author, Author.author_id == Work.author_id)
            .join(WorkDateDerived, WorkDateDerived.work_id == Work.work_id)
            .outerjoin(Edition, Edition.work_id == Work.work_id)
            .where(WorkDateDerived.display_date_field == "unknown")
            .group_by(
                Work.work_id,
                Work.title,
                Work.title_canonical,
                Work.work_type,
                Author.author_id,
                Author.name_canonical,
                Author.birth_year,
                Author.death_year,
            )
            .order_by(Author.name_canonical, Work.title)
        )

        all_unknown = session.execute(stmt).all()

        # Stratify by author
        author_counts: dict[str, int] = {}
        author_works: dict[str, list] = {}

        for row in all_unknown:
            author = row.name_canonical
            if author not in author_works:
                author_works[author] = []
                author_counts[author] = 0

            if author_counts[author] < max_per_author:
                author_works[author].append(row)
                author_counts[author] += 1

        # Flatten to final sample, ensuring author diversity
        sample = []
        authors_sorted = sorted(author_works.keys(), key=lambda a: len(author_works[a]), reverse=True)

        # Round-robin from authors to ensure diversity
        idx = 0
        while len(sample) < limit and idx < max(len(author_works[a]) for a in authors_sorted):
            for author in authors_sorted:
                if len(sample) >= limit:
                    break
                works = author_works[author]
                if idx < len(works):
                    sample.append(works[idx])
            idx += 1

        return sample[:limit]


def main():
    sample = generate_stratified_sample(limit=100, max_per_author=5)

    output = []
    for row in sample:
        urls = [u for u in (row.urls or []) if u]
        output.append({
            "work_id": str(row.work_id),
            "title": row.title_canonical or row.title,
            "author": row.name_canonical,
            "work_type": row.work_type,
            "birth_year": row.birth_year,
            "death_year": row.death_year,
            "sample_urls": urls[:3] if urls else [],
        })

    # Output sample file
    out_path = Path("/mnt/c/Users/Datision/Documents/grundrisse/sample_unknown_100.json")
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    print(f"Generated sample of {len(output)} works")
    print(f"Output: {out_path}")

    # Summary statistics
    authors = {}
    work_types = {}
    for w in output:
        authors[w["author"]] = authors.get(w["author"], 0) + 1
        work_types[w["work_type"]] = work_types.get(w["work_type"], 0) + 1

    print(f"\nUnique authors: {len(authors)}")
    print(f"Top authors by count:")
    for a, c in sorted(authors.items(), key=lambda x: -x[1])[:10]:
        print(f"  {a}: {c}")

    print(f"\nWork types:")
    for wt, c in sorted(work_types.items(), key=lambda x: -x[1]):
        print(f"  {wt}: {c}")


if __name__ == "__main__":
    main()
