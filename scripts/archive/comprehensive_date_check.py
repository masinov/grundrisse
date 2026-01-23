#!/usr/bin/env python3
"""
Comprehensive date verification for 100 unknown works.
Checks all available sources: URL, source_metadata, text content, external APIs.
"""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import Work, Author, Edition, Paragraph, WorkDateDerived
from grundrisse_core.db.models import WorkMetadataEvidence
from ingest_service.metadata.publication_date_resolver import PublicationDateResolver
from ingest_service.metadata.http_cached import CachedHttpClient
from ingest_service.parse.marxists_header_metadata import parse_dateish
from ingest_service.settings import settings as ingest_settings
from sqlalchemy import select
from bs4 import BeautifulSoup


def extract_date_from_url(url: str) -> dict | None:
    """Extract date from URL path with full precision."""
    if not url:
        return None

    # Pattern: /YYYY/MM/DD.htm or /YYYY/MM/DD/
    m = re.search(r'/(\d{4})/(\d{2})/(\d{2})(?:\.htm|/)', url)
    if m:
        return {
            "year": int(m.group(1)),
            "month": int(m.group(2)),
            "day": int(m.group(3)),
            "precision": "day",
            "source": "url_path",
            "raw": url
        }

    # Pattern: /YYYY/MM/ or /YYYY/month_abbrev/
    m = re.search(r'/(\d{4})/(\d{2})(?:\.htm|/)', url)
    if m:
        return {
            "year": int(m.group(1)),
            "month": int(m.group(2)),
            "day": None,
            "precision": "month",
            "source": "url_path",
            "raw": url
        }

    # Pattern: /YYYY/
    m = re.search(r'/(\d{4})(?:\.htm|/)', url)
    if m:
        return {
            "year": int(m.group(1)),
            "month": None,
            "day": None,
            "precision": "year",
            "source": "url_path",
            "raw": url
        }

    return None


def extract_from_source_metadata(source_metadata: dict) -> list[dict]:
    """Extract all dates from source_metadata fields."""
    if not source_metadata or not isinstance(source_metadata, dict):
        return []

    findings = []
    fields = source_metadata.get("fields", {})
    dates = source_metadata.get("dates", {})

    # Check pre-parsed dates
    for role in ["written", "first_published", "published", "title_date"]:
        if dates.get(role):
            d = dates[role]
            if isinstance(d, dict) and d.get("year"):
                findings.append({
                    **d,
                    "source": f"source_metadata.{role}",
                    "precision": d.get("precision", "year")
                })

    # Check raw fields for missed dates (case-insensitive)
    field_variants = {
        "First Published": ["First Published", "First published", "first published", "First Pubished", "First pubished"],
        "Published": ["Published", "published"],
        "Written": ["Written", "written"],
        "Delivered": ["Delivered", "delivered"],
        "Source": ["Source", "source"]
    }

    for canonical, variants in field_variants.items():
        value = None
        for v in variants:
            if v in fields:
                value = fields[v]
                break

        if value:
            parsed = parse_dateish(value)
            if parsed and parsed.get("year"):
                findings.append({
                    **parsed,
                    "source": f"source_metadata.fields.{canonical.lower()}",
                    "field_value": value
                })

    # Check periodical citations in Source field
    source_val = fields.get("Source") or fields.get("source")
    if source_val:
        # "Volume X, no Y, Month DD, YYYY"
        m = re.search(
            r'Volume\s+\d+,\s*no\s+\d+,\s*'
            r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})',
            source_val, re.IGNORECASE
        )
        if m:
            months = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
                      "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
            findings.append({
                "year": int(m.group(3)),
                "month": months[m.group(2).lower()],
                "day": int(m.group(1)),
                "precision": "day",
                "source": "source_metadata.periodical_citation",
                "raw": source_val
            })

    return findings


def search_text_for_dates(edition_id: str, session) -> list[dict]:
    """Search paragraph text for publication clues."""
    # Get first 20 paragraphs for context
    paras = session.execute(
        select(Paragraph).where(Paragraph.edition_id == edition_id).order_by(Paragraph.order_index).limit(30)
    ).scalars().all()

    findings = []
    text_sample = " ".join([p.text_normalized for p in paras[:20]])

    # Look for common date patterns in text
    # "First published in..." or "Written in..."
    patterns = [
        r'(?:first published|published)\s+(?:in|on)\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})',
        r'(?:written|composed)\s+(?:in|on)\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})',
        r'(?:first published|published)\s+in\s+(\d{4})',
    ]

    for pat in patterns:
        matches = re.findall(pat, text_sample, re.IGNORECASE)
        for match in matches[:2]:  # Max 2 per pattern
            parsed = parse_dateish(match)
            if parsed:
                findings.append({
                    **parsed,
                    "source": "text_content_search",
                    "match": match[:100]
                })
                break

    return findings


def check_external_sources(work_id: str, title: str, author_name: str, urls: list) -> list[dict]:
    """Check Wikidata and OpenLibrary."""
    findings = []

    cache_dir = Path(ingest_settings.data_dir) / "cache" / "publication_dates"

    try:
        with CachedHttpClient(
            cache_dir=cache_dir,
            user_agent=ingest_settings.user_agent,
            timeout_s=10.0,
            delay_s=0.5,
            max_cache_age_s=7 * 24 * 3600,
        ) as http:
            resolver = PublicationDateResolver(http=http)

            candidates = resolver.resolve(
                author_name=author_name,
                author_aliases=[],
                title=title,
                title_variants=[],
                language="en",
                source_urls=urls,
                sources=["wikidata", "openlibrary"],
                max_candidates=3
            )

            for cand in candidates:
                findings.append({
                    "year": cand.date.get("year"),
                    "month": cand.date.get("month"),
                    "day": cand.date.get("day"),
                    "precision": cand.date.get("precision", "year"),
                    "source": f"external_{cand.source_name}",
                    "score": cand.score,
                    "locator": cand.source_locator
                })
    except Exception as e:
        findings.append({"error": str(e), "source": "external_api_failed"})

    return findings


def investigate_work(work_id: str, session) -> dict:
    """Comprehensive investigation of a single work."""
    work = session.get(Work, work_id)
    if not work:
        return {"error": "Work not found"}

    author = session.get(Author, work.author_id)
    derived = session.get(WorkDateDerived, work_id)

    editions = session.execute(
        select(Edition).where(Edition.work_id == work_id)
    ).scalars().all()

    # Check existing external evidence
    existing_evidence = session.execute(
        select(WorkMetadataEvidence).where(WorkMetadataEvidence.work_id == work_id)
    ).scalars().all()

    result = {
        "work_id": str(work_id),
        "title": work.title_canonical or work.title,
        "author": author.name_canonical if author else "Unknown",
        "birth_year": author.birth_year if author else None,
        "death_year": author.death_year if author else None,
        "current_status": {
            "display_date_field": derived.display_date_field if derived else None,
            "display_year": derived.display_year if derived else None,
        },
        "findings": {
            "url_dates": [],
            "source_metadata_dates": [],
            "text_dates": [],
            "external_dates": [],
            "existing_evidence": []
        }
    }

    # Collect all URLs
    all_urls = []
    for ed in editions:
        if ed.source_url:
            all_urls.append(ed.source_url)

    # Check URL dates
    for url in all_urls:
        url_date = extract_date_from_url(url)
        if url_date:
            result["findings"]["url_dates"].append(url_date)

    # Check source_metadata
    for ed in editions:
        if ed.source_metadata:
            meta_dates = extract_from_source_metadata(ed.source_metadata)
            result["findings"]["source_metadata_dates"].extend(meta_dates)

    # Check text content
    if editions:
        text_dates = search_text_for_dates(editions[0].edition_id, session)
        result["findings"]["text_dates"].extend(text_dates)

    # Check existing external evidence
    for ev in existing_evidence:
        if ev.extracted and ev.extracted.get("year"):
            result["findings"]["existing_evidence"].append({
                "year": ev.extracted.get("year"),
                "source": ev.source_name,
                "score": ev.score,
                "extracted": ev.extracted
            })

    # Try external sources if no dates found yet
    if not result["findings"]["url_dates"] and not result["findings"]["source_metadata_dates"]:
        external_dates = check_external_sources(
            work_id, result["title"], result["author"], all_urls
        )
        result["findings"]["external_dates"] = external_dates

    return result


def main():
    with open("/mnt/c/Users/Datision/Documents/grundrisse/sample_unknown_100.json") as f:
        sample = json.load(f)

    results = []

    with SessionLocal() as session:
        for i, item in enumerate(sample, 1):
            print(f"[{i}/100] {item['author']}: {item['title'][:60]}...")
            result = investigate_work(item["work_id"], session)
            results.append(result)

            # Quick summary
            total_dates = (
                len(result["findings"]["url_dates"]) +
                len(result["findings"]["source_metadata_dates"]) +
                len(result["findings"]["text_dates"]) +
                len(result["findings"]["external_dates"]) +
                len(result["findings"]["existing_evidence"])
            )
            print(f"  Found {total_dates} date candidates")

    # Save results
    out_path = Path("/mnt/c/Users/Datision/Documents/grundrisse/date_verification_100.json")
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nSaved results to {out_path}")

    # Summary statistics
    url_date_found = sum(1 for r in results if r["findings"]["url_dates"])
    meta_date_found = sum(1 for r in results if r["findings"]["source_metadata_dates"])
    text_date_found = sum(1 for r in results if r["findings"]["text_dates"])
    external_date_found = sum(1 for r in results if r["findings"]["external_dates"])
    any_date_found = sum(1 for r in results if (
        r["findings"]["url_dates"] or r["findings"]["source_metadata_dates"] or
        r["findings"]["text_dates"] or
        any(d.get("year") for d in r["findings"]["external_dates"] if not d.get("error"))
    ))

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"URL dates found: {url_date_found}/100")
    print(f"Source metadata dates found: {meta_date_found}/100")
    print(f"Text content dates found: {text_date_found}/100")
    print(f"External API dates found: {external_date_found}/100")
    print(f"Any date found: {any_date_found}/100 ({any_date_found}%)")
    print(f"No date found: {100-any_date_found}/100")


if __name__ == "__main__":
    main()
