#!/usr/bin/env python3
"""
Auto-investigation script - attempts to extract dates from available data
"""
import json
import re
import sys
from datetime import datetime
from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import Work, Author, Edition, Paragraph, WorkDateDerived
from sqlalchemy import select

def extract_url_date(url):
    """Extract date from URL path"""
    if not url:
        return None

    # Pattern: /YYYY/MM/DD.htm or /YYYY/MM/DD/
    match = re.search(r'/(\d{4})/(\d{2})/(\d{2})', url)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}", "day"

    # Pattern: /YYYY/MM/ or /YYYY/month_name/
    match = re.search(r'/(\d{4})/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', url, re.I)
    if match:
        months = {'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
                  'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'}
        return f"{match.group(1)}-{months[match.group(2).lower()]}", "month"

    match = re.search(r'/(\d{4})/(\d{2})/', url)
    if match:
        return f"{match.group(1)}-{match.group(2)}", "month"

    # Pattern: /YYYY/
    match = re.search(r'/(\d{4})/', url)
    if match:
        return match.group(1), "year"

    return None

def extract_from_source_fields(source_metadata):
    """Extract dates from source metadata fields"""
    if not source_metadata or 'fields' not in source_metadata:
        return []

    findings = []
    fields = source_metadata['fields']

    # Check for "First Published", "First published", "Published"
    for key in ['First Published', 'First published', 'first published', 'Published', 'Delivered', 'Written']:
        if key in fields:
            text = fields[key]
            # Look for date patterns
            # Pattern: Month DD, YYYY
            match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})', text, re.I)
            if match:
                month_map = {'january': '01', 'february': '02', 'march': '03', 'april': '04',
                           'may': '05', 'june': '06', 'july': '07', 'august': '08',
                           'september': '09', 'october': '10', 'november': '11', 'december': '12'}
                month_num = month_map[match.group(1).lower()]
                day = match.group(2).zfill(2)
                year = match.group(3)
                findings.append((f"{year}-{month_num}-{day}", "day", f"{key} field"))

            # Pattern: YYYY
            match = re.search(r'\b(1[7-9]\d{2}|20\d{2})\b', text)
            if match:
                findings.append((match.group(1), "year", f"{key} field"))

    # Check Source field for periodical citations
    if 'Source' in fields:
        text = fields['Source']
        # Pattern: Volume X, no Y, Date
        match = re.search(r'Volume\s+\d+,\s*no\s+\d+,\s*(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', text, re.I)
        if match:
            month_map = {'january': '01', 'february': '02', 'march': '03', 'april': '04',
                       'may': '05', 'june': '06', 'july': '07', 'august': '08',
                       'september': '09', 'october': '10', 'november': '11', 'december': '12'}
            day = match.group(1).zfill(2)
            month_num = month_map[match.group(2).lower()]
            year = match.group(3)
            findings.append((f"{year}-{month_num}-{day}", "day", "Source periodical"))

    return findings

def auto_investigate(work_id):
    """Automatically investigate work and return findings"""
    with SessionLocal() as session:
        work = session.get(Work, work_id)
        if not work:
            return None

        author = session.get(Author, work.author_id)
        edition = session.execute(
            select(Edition).where(Edition.work_id == work_id).limit(1)
        ).scalar_one_or_none()

        findings = {
            "work_id": work_id,
            "title": work.title,
            "author": author.name_canonical if author else "Unknown",
            "url_date": None,
            "source_metadata_dates": [],
            "work_pub_date": work.publication_date
        }

        # Extract from URL
        if edition:
            url_result = extract_url_date(edition.source_url)
            if url_result:
                findings["url_date"] = {"date": url_result[0], "precision": url_result[1]}

            # Extract from source metadata
            meta_dates = extract_from_source_fields(edition.source_metadata)
            findings["source_metadata_dates"] = [
                {"date": d[0], "precision": d[1], "source": d[2]}
                for d in meta_dates
            ]

        return findings

if __name__ == '__main__':
    # Process all unknown works from sample_100_works.json
    with open('/mnt/c/Users/Datision/Documents/grundrisse/sample_100_works.json', 'r') as f:
        works = json.load(f)

    # Skip first 5 (already done) and process 6-100
    for work in works[5:]:
        result = auto_investigate(work['work_id'])
        if result:
            print(json.dumps(result, ensure_ascii=False))
