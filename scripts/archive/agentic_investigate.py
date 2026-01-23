#!/usr/bin/env python3
"""
Agentic publication date investigation using GLM with optional web search.

Flow per work:
  1) Planner model suggests search queries.
  2) Collect evidence from local DB, URL patterns, and external resolvers.
  3) Solver model produces a date decision with evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# Add repo packages to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "pipelines/nlp_pipeline/src"))
sys.path.insert(0, str(REPO_ROOT / "services/ingest_service/src"))

from nlp_pipeline.llm.zai_glm import ZaiGlmClient
from ingest_service.metadata.publication_date_resolver import PublicationDateResolver
from ingest_service.metadata.http_cached import CachedHttpClient
from ingest_service.settings import settings as ingest_settings
from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import Work, Author, Edition, Paragraph, WorkDateDerived
from sqlalchemy import select


PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "search_queries": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["search_queries"],
}

SOLVER_SCHEMA = {
    "type": "object",
    "properties": {
        "correct_date": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "source": {"type": "string"},
        "evidence": {"type": "string"},
        "precision": {"type": ["string", "null"]},
        "reasoning": {"type": "string"},
    },
    "required": ["correct_date", "confidence", "source", "evidence"],
}


PLANNER_PROMPT_TEMPLATE = """You are a research planner for publication date investigation.

WORK DETAILS:
Title: {title}
Author: {author}
URL: {url}

SOURCE METADATA (raw):
{source_metadata}

FIRST PARAGRAPHS:
{paragraphs}

TASK:
Propose up to 3 web search queries that are likely to surface the original publication date.
Keep queries concise and specific. If no web search is needed, return an empty list.

OUTPUT JSON:
{{
  "search_queries": ["..."],
  "notes": "optional"
}}
"""

SOLVER_PROMPT_TEMPLATE = """You are investigating the publication date for a Marxist text.

WORK DETAILS:
Title: {title}
Author: {author}
URL: {url}

SOURCE METADATA:
{source_metadata}

URL DATE EXTRACTION:
{url_date}

LOCAL HEADER DATES:
{source_dates}

FIRST PARAGRAPHS:
{paragraphs}

WIKIDATA/OPENLIBRARY/MARXISTS CANDIDATES:
{resolver_candidates}

WEB SEARCH RESULTS:
{search_results}

TASK:
Extract the ORIGINAL publication date (not collection/reprint/edition dates).

Rules:
- Prefer first publication or delivery date for speeches and articles.
- For letters, prefer written date over later collection publication dates.
- If only a year is available, return the year with year precision.
- Provide a short evidence snippet and cite where it came from (metadata, URL, text, resolver, or web search).

OUTPUT JSON:
{{
  "correct_date": "YYYY-MM-DD or YYYY-MM or YYYY or null",
  "confidence": "high or medium or low",
  "source": "where you found it",
  "evidence": "exact text snippet",
  "precision": "day or month or year or null",
  "reasoning": "brief explanation"
}}
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agentic date investigation with GLM")
    parser.add_argument("--sample-file", type=str, default="sample_100_works.json")
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--work-ids", type=str, default="")
    parser.add_argument("--output", type=str, default="agentic_investigation_results.jsonl")
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument("--planner-model", type=str, default="glm-4.7-flash")
    parser.add_argument("--solver-model", type=str, default="glm-4.7-flash")
    parser.add_argument("--search-results", type=int, default=5)
    parser.add_argument("--sources", type=str, default="marxists,wikidata,openlibrary")
    parser.add_argument("--disable-web-search", action="store_true")
    return parser.parse_args()


def extract_url_date(url: str | None) -> dict[str, str] | None:
    if not url:
        return None

    match = re.search(r"/(\d{4})/(\d{2})/(\d{2})", url)
    if match:
        return {"date": f"{match.group(1)}-{match.group(2)}-{match.group(3)}", "precision": "day"}

    match = re.search(r"/(\d{4})/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", url, re.I)
    if match:
        months = {
            "jan": "01",
            "feb": "02",
            "mar": "03",
            "apr": "04",
            "may": "05",
            "jun": "06",
            "jul": "07",
            "aug": "08",
            "sep": "09",
            "oct": "10",
            "nov": "11",
            "dec": "12",
        }
        return {"date": f"{match.group(1)}-{months[match.group(2).lower()]}", "precision": "month"}

    match = re.search(r"/(\d{4})/(\d{2})/", url)
    if match:
        return {"date": f"{match.group(1)}-{match.group(2)}", "precision": "month"}

    match = re.search(r"/(\d{4})/", url)
    if match:
        return {"date": match.group(1), "precision": "year"}

    return None


def extract_from_source_fields(source_metadata: dict[str, Any] | None) -> list[dict[str, str]]:
    if not source_metadata or "fields" not in source_metadata:
        return []

    findings: list[dict[str, str]] = []
    fields = source_metadata["fields"]

    for key in ["First Published", "First published", "first published", "Published", "Delivered", "Written"]:
        if key in fields:
            text = fields[key]
            match = re.search(
                r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
                text,
                re.I,
            )
            if match:
                month_map = {
                    "january": "01",
                    "february": "02",
                    "march": "03",
                    "april": "04",
                    "may": "05",
                    "june": "06",
                    "july": "07",
                    "august": "08",
                    "september": "09",
                    "october": "10",
                    "november": "11",
                    "december": "12",
                }
                month_num = month_map[match.group(1).lower()]
                day = match.group(2).zfill(2)
                year = match.group(3)
                findings.append({"date": f"{year}-{month_num}-{day}", "precision": "day", "source": key})
            match = re.search(r"\b(1[7-9]\d{2}|20\d{2})\b", text)
            if match:
                findings.append({"date": match.group(1), "precision": "year", "source": key})

    if "Source" in fields:
        text = fields["Source"]
        match = re.search(
            r"Volume\s+\d+,\s*no\s+\d+,\s*(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
            text,
            re.I,
        )
        if match:
            month_map = {
                "january": "01",
                "february": "02",
                "march": "03",
                "april": "04",
                "may": "05",
                "june": "06",
                "july": "07",
                "august": "08",
                "september": "09",
                "october": "10",
                "november": "11",
                "december": "12",
            }
            day = match.group(1).zfill(2)
            month_num = month_map[match.group(2).lower()]
            year = match.group(3)
            findings.append({"date": f"{year}-{month_num}-{day}", "precision": "day", "source": "Source"})

    return findings


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class BingSearchClient:
    def __init__(self, *, http: CachedHttpClient, api_key: str, endpoint: str) -> None:
        self.http = http
        self.api_key = api_key
        self.endpoint = endpoint

    def search(self, query: str, *, count: int = 5) -> list[SearchResult]:
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        resp = self.http.get(
            self.endpoint,
            params={"q": query, "count": count},
            accept="application/json",
            headers=headers,
        )
        if resp.status_code != 200 or not resp.text:
            return []
        try:
            data = json.loads(resp.text)
        except Exception:
            return []
        items = (data.get("webPages") or {}).get("value") or []
        out: list[SearchResult] = []
        for item in items[:count]:
            title = item.get("name") if isinstance(item.get("name"), str) else ""
            url = item.get("url") if isinstance(item.get("url"), str) else ""
            snippet = item.get("snippet") if isinstance(item.get("snippet"), str) else ""
            if url:
                out.append(SearchResult(title=title, url=url, snippet=snippet))
        return out


def load_work_details(work_id: str, *, paragraph_limit: int = 3) -> dict[str, Any] | None:
    with SessionLocal() as session:
        work = session.get(Work, work_id)
        if not work:
            return None

        author = session.get(Author, work.author_id)
        edition = session.execute(select(Edition).where(Edition.work_id == work_id).limit(1)).scalar_one_or_none()
        derived = session.get(WorkDateDerived, work_id)

        paragraphs: list[str] = []
        if edition:
            paras = (
                session.execute(
                    select(Paragraph)
                    .where(Paragraph.edition_id == edition.edition_id)
                    .limit(paragraph_limit)
                )
                .scalars()
                .all()
            )
            paragraphs = [p.text_normalized[:500] for p in paras]

        return {
            "work_id": work_id,
            "title": work.title,
            "author": author.name_canonical if author else "Unknown",
            "author_birth_year": author.birth_year if author else None,
            "author_death_year": author.death_year if author else None,
            "url": edition.source_url if edition else None,
            "source_metadata": edition.source_metadata if edition else None,
            "paragraphs": paragraphs,
            "display_date_field": derived.display_date_field if derived else "unknown",
            "display_date": derived.display_date if derived else None,
        }


def _format_paragraphs(paragraphs: list[str]) -> str:
    return "\n\n".join(f"[Para {i + 1}] {p}" for i, p in enumerate(paragraphs))


def plan_queries(api_key: str, base_url: str, model: str, details: dict[str, Any]) -> dict[str, Any]:
    prompt = PLANNER_PROMPT_TEMPLATE.format(
        title=details["title"],
        author=details["author"],
        url=details.get("url") or "null",
        source_metadata=json.dumps(details.get("source_metadata"), indent=2) if details.get("source_metadata") else "null",
        paragraphs=_format_paragraphs(details.get("paragraphs") or []),
    )
    with ZaiGlmClient(api_key=api_key, base_url=base_url, model=model) as planner_client:
        response = planner_client.complete_json(prompt=prompt, schema=PLANNER_SCHEMA)
    return response.json or {"search_queries": []}


def solve_date(
    api_key: str,
    base_url: str,
    model: str,
    details: dict[str, Any],
    *,
    url_date: dict[str, str] | None,
    source_dates: list[dict[str, str]],
    resolver_candidates: list[dict[str, Any]],
    search_results: list[SearchResult],
) -> dict[str, Any]:
    prompt = SOLVER_PROMPT_TEMPLATE.format(
        title=details["title"],
        author=details["author"],
        url=details.get("url") or "null",
        source_metadata=json.dumps(details.get("source_metadata"), indent=2) if details.get("source_metadata") else "null",
        url_date=json.dumps(url_date, indent=2) if url_date else "null",
        source_dates=json.dumps(source_dates, indent=2) if source_dates else "null",
        paragraphs=_format_paragraphs(details.get("paragraphs") or []),
        resolver_candidates=json.dumps(resolver_candidates, indent=2) if resolver_candidates else "null",
        search_results=json.dumps(
            [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in search_results], indent=2
        )
        if search_results
        else "null",
    )
    with ZaiGlmClient(api_key=api_key, base_url=base_url, model=model) as solver_client:
        response = solver_client.complete_json(prompt=prompt, schema=SOLVER_SCHEMA)
    return response.json or {}


def investigate_one(
    work_id: str,
    *,
    planner_model: str,
    solver_model: str,
    search_results_count: int,
    sources: list[str],
    disable_web_search: bool,
) -> dict[str, Any]:
    started_at = time.time()
    details = load_work_details(work_id)
    if not details:
        return {"work_id": work_id, "error": "work_not_found"}

    url_date = extract_url_date(details.get("url"))
    source_dates = extract_from_source_fields(details.get("source_metadata"))

    zai_api_key = os.environ.get("GRUNDRISSE_ZAI_API_KEY", "")
    base_url = os.environ.get("GRUNDRISSE_ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4")

    cache_dir = Path(ingest_settings.data_dir) / "cache" / "publication_dates"
    resolver_candidates: list[dict[str, Any]] = []

    with CachedHttpClient(
        cache_dir=cache_dir,
        user_agent=ingest_settings.user_agent,
        timeout_s=ingest_settings.request_timeout_s,
        delay_s=0.8,
        max_cache_age_s=7 * 24 * 3600,
    ) as http:
        resolver = PublicationDateResolver(http=http)
        title_variants = PublicationDateResolver.title_variants(
            title=details["title"], url_hints=[details["url"]] if details.get("url") else None
        )
        resolver_candidates = [
            {
                "date": c.date,
                "score": c.score,
                "source_name": c.source_name,
                "source_locator": c.source_locator,
                "notes": c.notes,
                "raw_payload": c.raw_payload,
            }
            for c in resolver.resolve(
                author_name=details["author"],
                author_aliases=[],
                author_birth_year=details.get("author_birth_year"),
                author_death_year=details.get("author_death_year"),
                title=details["title"],
                title_variants=title_variants,
                language=None,
                source_urls=[details["url"]] if details.get("url") else [],
                sources=sources,
                max_candidates=5,
            )
        ]

        search_results: list[SearchResult] = []
        planner_response: dict[str, Any] = {"search_queries": []}
        if not disable_web_search:
            search_api_key = os.environ.get("GRUNDRISSE_SEARCH_API_KEY")
            endpoint = os.environ.get("GRUNDRISSE_SEARCH_API_URL", "https://api.bing.microsoft.com/v7.0/search")
            if search_api_key:
                planner_response = plan_queries(zai_api_key, base_url, planner_model, details)
                searcher = BingSearchClient(http=http, api_key=search_api_key, endpoint=endpoint)
                queries = planner_response.get("search_queries") or []
                for q in queries[:3]:
                    search_results.extend(searcher.search(q, count=search_results_count))
            else:
                planner_response = {"search_queries": [], "notes": "GRUNDRISSE_SEARCH_API_KEY not set"}

    solver_response = solve_date(
        zai_api_key,
        base_url,
        solver_model,
        details,
        url_date=url_date,
        source_dates=source_dates,
        resolver_candidates=resolver_candidates,
        search_results=search_results,
    )

    elapsed = time.time() - started_at
    return {
        "work_id": work_id,
        "title": details["title"],
        "author": details["author"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "planner_model": planner_model,
        "solver_model": solver_model,
        "plan": planner_response,
        "evidence": {
            "url_date": url_date,
            "source_dates": source_dates,
            "resolver_candidates": resolver_candidates,
            "search_results": [
                {"title": r.title, "url": r.url, "snippet": r.snippet} for r in search_results
            ],
        },
        "result": solver_response,
        "timing_s": elapsed,
    }


def main() -> None:
    args = _parse_args()
    api_key = os.environ.get("GRUNDRISSE_ZAI_API_KEY")
    if not api_key:
        print("ERROR: GRUNDRISSE_ZAI_API_KEY not set")
        return

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    work_ids: list[str] = []
    if args.work_ids.strip():
        work_ids = [w.strip() for w in args.work_ids.split(",") if w.strip()]
    else:
        try:
            with open(args.sample_file, "r") as f:
                sample = json.load(f)
            work_ids = [w["work_id"] for w in sample[: args.sample_size]]
        except Exception as exc:
            print(f"ERROR: Failed to load sample works: {exc}")
            return

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = [
            executor.submit(
                investigate_one,
                wid,
                planner_model=args.planner_model,
                solver_model=args.solver_model,
                search_results_count=args.search_results,
                sources=sources,
                disable_web_search=args.disable_web_search,
            )
            for wid in work_ids
        ]

        with out_path.open("w", encoding="utf-8") as f:
            for future in as_completed(futures):
                result = future.result()
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

    print(f"Done. Wrote results to {out_path}")


if __name__ == "__main__":
    main()
