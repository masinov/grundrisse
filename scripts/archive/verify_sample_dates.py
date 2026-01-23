#!/usr/bin/env python3
"""
Manual verification of sample dates by fetching and checking actual content.
"""
import re
from pathlib import Path

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import Work, Edition
from ingest_service.parse.marxists_header_metadata import extract_marxists_header_metadata
from sqlalchemy import select

# Sample works to verify manually
SAMPLE_URLS = [
    "https://www.marxists.org/archive/bhagat-singh/1928/12/18.htm",
    "https://www.marxists.org/archive/kollonta/1917/lenin-smolny.htm",
    "https://www.marxists.org/archive/lozovsky/1923/04/victory.html",
    "https://www.marxists.org/archive/zetkin/1920/lenin/zetkin1.htm",
]

def check_cached_html(url: str) -> dict:
    """Check if we have cached HTML and extract metadata."""
    # Try to find edition with this URL
    with SessionLocal() as session:
        edition = session.execute(
            select(Edition).where(Edition.source_url == url)
        ).scalar_one_or_none()

        if not edition:
            return {"error": "No edition found"}

        # Try to find cached HTML
        from grundrisse_core.db.session import engine
        import os

        # Check data/raw directory
        data_dir = Path("/mnt/c/Users/Datision/Documents/grundrisse/data/raw")
        if not data_dir.exists():
            return {"error": "No data directory"}

        # Look for HTML files
        html_files = list(data_dir.glob("*.html"))
        if not html_files:
            return {"error": "No cached HTML found"}

        # Try to parse first HTML file for demo
        sample_html = html_files[0].read_text(encoding="utf-8", errors="ignore")
        metadata = extract_marxists_header_metadata(sample_html)

        return {
            "edition_id": str(edition.edition_id),
            "source_metadata": edition.source_metadata,
            "sample_metadata": metadata,
            "work_id": str(edition.work_id)
        }


def main():
    print("="*80)
    print("MANUAL VERIFICATION OF SAMPLE DATES")
    print("="*80)

    for url in SAMPLE_URLS:
        print(f"\nURL: {url}")

        # Extract date from URL
        m = re.search(r'/(\d{4})/(\d{2})/(\d{2})', url)
        if m:
            print(f"  URL extracted date: {m.group(1)}-{m.group(2)}-{m.group(3)}")
        else:
            m = re.search(r'/(\d{4})/(\d{2})', url)
            if m:
                print(f"  URL extracted date: {m.group(1)}-{m.group(2)}")
            else:
                m = re.search(r'/(\d{4})/', url)
                if m:
                    print(f"  URL extracted date: {m.group(1)}")

        # Check database for metadata
        with SessionLocal() as session:
            edition = session.execute(
                select(Edition).where(Edition.source_url == url)
            ).scalar_one_or_none()

            if edition and edition.source_metadata:
                fields = edition.source_metadata.get("fields", {})
                dates = edition.source_metadata.get("dates", {})

                print(f"  Database source_metadata fields:")
                for k, v in list(fields.items())[:5]:
                    print(f"    {k}: {v[:80]}")
                print(f"  Database source_metadata dates:")
                for k, v in dates.items():
                    if v and isinstance(v, dict):
                        print(f"    {k}: {v}")
            else:
                print(f"  No source_metadata in database")

if __name__ == "__main__":
    main()
