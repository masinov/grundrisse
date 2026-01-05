from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from hashlib import sha256
from typing import Any, Iterable

from bs4 import BeautifulSoup

from ingest_service.metadata.http_cached import CachedHttpClient


@dataclass(frozen=True)
class PublicationDateCandidate:
    date: dict[str, Any]
    score: float
    source_name: str
    source_locator: str | None
    raw_payload: dict[str, Any] | None
    notes: str | None = None


class PublicationDateResolver:
    """
    Resolve publication date candidates for a work using multiple strategies.
    """

    def __init__(self, *, http: CachedHttpClient) -> None:
        self.http = http

    def resolve(
        self,
        *,
        author_name: str,
        author_aliases: list[str],
        author_birth_year: int | None = None,
        author_death_year: int | None = None,
        title: str,
        title_variants: list[str],
        language: str | None,
        source_urls: list[str],
        sources: list[str],
        max_candidates: int = 5,
    ) -> list[PublicationDateCandidate]:
        candidates: list[PublicationDateCandidate] = []

        src = set(sources)
        if "marxists" in src:
            candidates.extend(
                self._from_marxists_pages(
                    source_urls=source_urls,
                    title_variants=title_variants,
                    max_candidates=max_candidates,
                )
            )
        if "wikidata" in src:
            candidates.extend(
                self._from_wikidata(
                    author_name=author_name,
                    author_aliases=author_aliases,
                    title=title,
                    title_variants=title_variants,
                    language=language,
                    max_candidates=max_candidates,
                )
            )
        if "openlibrary" in src:
            candidates.extend(
                self._from_openlibrary(
                    author_name=author_name,
                    author_aliases=author_aliases,
                    title=title,
                    title_variants=title_variants,
                    max_candidates=max_candidates,
                )
            )

        # Apply lifespan plausibility penalties centrally so all call sites benefit (CLI, finalizer, etc.).
        candidates = _apply_author_lifespan_penalties(
            candidates,
            birth_year=author_birth_year,
            death_year=author_death_year,
        )

        # sort high-to-low score; stable tiebreaker by source then hash
        return sorted(
            candidates,
            key=lambda c: (-c.score, c.source_name, sha256(str(c.date).encode("utf-8")).hexdigest()),
        )

    @staticmethod
    def title_variants(*, title: str, url_hints: list[str] | None = None) -> list[str]:
        variants: list[str] = []
        if title.strip():
            variants.append(title.strip())
        for v in _generate_title_variants(title):
            if v not in variants:
                variants.append(v)
        if url_hints:
            for hint in url_hints:
                for v in _title_variants_from_url(hint):
                    if v not in variants:
                        variants.append(v)
        return variants

    def _from_marxists_pages(
        self, *, source_urls: list[str], title_variants: list[str], max_candidates: int
    ) -> list[PublicationDateCandidate]:
        out: list[PublicationDateCandidate] = []
        # Prefer likely work root pages first (index/preface) and HTML only.
        urls = _prioritize_marxists_urls(source_urls)
        for url in urls[:12]:
            resp = self.http.get(url, accept="text/html", as_bytes=True)
            if resp.status_code != 200 or not resp.content:
                continue
            try:
                soup = BeautifulSoup(resp.content, "lxml")
            except Exception:
                continue

            candidates = _extract_publication_year_candidates_from_marxists_html(soup)
            for year, score, date_type, excerpt in candidates:
                out.append(
                    PublicationDateCandidate(
                        date={
                            "year": year,
                            "precision": "year",
                            "method": "marxists_page",
                            "date_type": date_type,
                            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        },
                        score=score,
                        source_name="marxists",
                        source_locator=url,
                        raw_payload={"year": year, "date_type": date_type, "excerpt": excerpt},
                        notes=f"{date_type}:{excerpt}",
                    )
                )
                if len(out) >= max_candidates:
                    return out
        return out

    def _from_openlibrary(
        self,
        *,
        author_name: str,
        author_aliases: list[str],
        title: str,
        title_variants: list[str],
        max_candidates: int,
    ) -> list[PublicationDateCandidate]:
        out: list[PublicationDateCandidate] = []
        # Try a few combinations; OpenLibrary is relatively forgiving.
        author_queries = [author_name] + [a for a in author_aliases if a != author_name][:3]
        for t in title_variants[:5]:
            for a in author_queries[:3]:
                params = {"title": t, "author": a, "limit": 5}
                resp = self.http.get("https://openlibrary.org/search.json", params=params, accept="application/json")
                if resp.status_code != 200 or not resp.text:
                    continue
                try:
                    data = _json_loads(resp.text)
                except Exception:
                    continue
                docs = data.get("docs") if isinstance(data, dict) else None
                if not isinstance(docs, list):
                    continue

                for doc in docs[:5]:
                    year = doc.get("first_publish_year")
                    if not isinstance(year, int) or not (1500 <= year <= 2030):
                        continue
                    label = doc.get("title") if isinstance(doc.get("title"), str) else None
                    doc_authors = doc.get("author_name")
                    author_ok = True
                    author_score = 0.0
                    if isinstance(doc_authors, list):
                        author_score = _best_author_similarity(doc_authors, [author_name] + author_aliases)
                        author_ok = author_score >= 0.70

                    # Strongly prefer candidates whose listed authors match our author identity.
                    if not author_ok:
                        continue

                    s = 0.45
                    if label:
                        s += 0.4 * _best_title_similarity(label, title_variants)
                    s += 0.15 * author_score
                    out.append(
                        PublicationDateCandidate(
                            date={
                                "year": year,
                                "precision": "year",
                                "method": "openlibrary_first_publish_year",
                                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            },
                            score=min(0.95, s),
                            source_name="openlibrary",
                            source_locator=doc.get("key") if isinstance(doc.get("key"), str) else None,
                            raw_payload={"doc": doc},
                            notes="OpenLibrary first_publish_year candidate",
                        )
                    )
                    if len(out) >= max_candidates:
                        return out
        return out

    def _from_wikidata(
        self,
        *,
        author_name: str,
        author_aliases: list[str],
        title: str,
        title_variants: list[str],
        language: str | None,
        max_candidates: int,
    ) -> list[PublicationDateCandidate]:
        out: list[PublicationDateCandidate] = []

        # Wikidata search is language-sensitive; use English by default but allow per-edition language hints.
        search_languages = ["en"]
        if language and language not in search_languages:
            search_languages.insert(0, language)

        queries = _wikidata_query_variants(title=title, author=author_name, title_variants=title_variants)
        for lang in search_languages[:2]:
            for q in queries[:8]:
                search = self.http.get(
                    "https://www.wikidata.org/w/api.php",
                    params={
                        "action": "wbsearchentities",
                        "search": q,
                        "language": lang,
                        "format": "json",
                        "limit": 8,
                    },
                    accept="application/json",
                )
                if search.status_code != 200 or not search.text:
                    continue
                try:
                    sdata = _json_loads(search.text)
                except Exception:
                    continue
                results = sdata.get("search") if isinstance(sdata, dict) else None
                if not isinstance(results, list):
                    continue

                qids = [r.get("id") for r in results if isinstance(r, dict) and isinstance(r.get("id"), str)]
                for qid in qids[:8]:
                    ent = self.http.get(
                        f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json",
                        accept="application/json",
                    )
                    if ent.status_code != 200 or not ent.text:
                        continue
                    try:
                        edata = _json_loads(ent.text)
                    except Exception:
                        continue
                    candidate = _extract_publication_year_from_wikidata_entity(edata, qid=qid)
                    if candidate is None:
                        continue

                    label = _wikidata_best_label(edata, qid=qid, languages=[lang, "en"])
                    sim = _best_title_similarity(label or "", title_variants) if label else 0.0
                    base = 0.55 + 0.35 * sim

                    # Hardening: verify entity is a written work and (when available) that its author/creator matches.
                    instance_qids = _wikidata_extract_item_qids(edata, qid=qid, prop="P31")
                    author_qids = (
                        _wikidata_extract_item_qids(edata, qid=qid, prop="P50")
                        + _wikidata_extract_item_qids(edata, qid=qid, prop="P170")
                    )

                    # If we can't establish authorship, skip to avoid high-rate false positives for generic titles.
                    if not author_qids:
                        continue

                    id_labels = self._wikidata_fetch_labels(list(dict.fromkeys(instance_qids + author_qids)), lang=lang)
                    instance_labels = [id_labels.get(i) for i in instance_qids if id_labels.get(i)]
                    author_labels = [id_labels.get(i) for i in author_qids if id_labels.get(i)]

                    if not _is_likely_written_work(instance_labels):
                        continue

                    author_sim = _best_author_similarity(author_labels, [author_name] + author_aliases)
                    # Require a strong author identity match to prevent mismatched works with same title.
                    if author_sim < 0.72:
                        continue

                    base += 0.15 * author_sim

                    out.append(
                        PublicationDateCandidate(
                            date={
                                "year": candidate["year"],
                                "precision": candidate.get("precision", "year"),
                                "method": "wikidata_p577",
                                "wikidata_qid": qid,
                                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            },
                            score=max(0.0, min(0.98, base)),
                            source_name="wikidata",
                            source_locator=f"wikidata:{qid}",
                            raw_payload={
                                "qid": qid,
                                "label": label,
                                "candidate": candidate,
                                "instance_labels": instance_labels,
                                "author_labels": author_labels,
                                "author_similarity": author_sim,
                            },
                            notes="Wikidata publication date candidate",
                        )
                    )
                    if len(out) >= max_candidates:
                        return out
        return out

    def _wikidata_fetch_labels(self, qids: list[str], *, lang: str) -> dict[str, str]:
        # Use wbgetentities so we can map P31/P50/P170 QIDs to human-readable labels.
        # Cache layer will avoid repeated calls across works.
        if not qids:
            return {}
        ids = "|".join(qids[:50])
        resp = self.http.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "ids": ids,
                "props": "labels",
                "languages": f"{lang}|en",
                "format": "json",
            },
            accept="application/json",
        )
        if resp.status_code != 200 or not resp.text:
            return {}
        try:
            data = _json_loads(resp.text)
        except Exception:
            return {}
        entities = data.get("entities") if isinstance(data, dict) else None
        if not isinstance(entities, dict):
            return {}
        out: dict[str, str] = {}
        for qid, ent in entities.items():
            if not isinstance(ent, dict):
                continue
            labels = ent.get("labels")
            if not isinstance(labels, dict):
                continue
            # Prefer requested language if present, else English.
            chosen = None
            for l in (lang, "en"):
                obj = labels.get(l)
                if isinstance(obj, dict) and isinstance(obj.get("value"), str):
                    chosen = obj["value"]
                    break
            if chosen is None:
                for obj in labels.values():
                    if isinstance(obj, dict) and isinstance(obj.get("value"), str):
                        chosen = obj["value"]
                        break
            if chosen:
                out[qid] = chosen
        return out


def _generate_title_variants(title: str) -> Iterable[str]:
    t = title.strip()
    if not t:
        return []
    # Remove bracketed suffixes (common in scraped titles).
    t2 = re.sub(r"\s*[\(\[].*?[\)\]]\s*$", "", t).strip()
    if t2 and t2 != t:
        yield t2

    # Remove common leading articles for matching.
    lowered = t2.lower()
    for prefix in ("the ", "a ", "an "):
        if lowered.startswith(prefix):
            yield t2[len(prefix) :].strip()

    # Remove punctuation-only differences.
    yield re.sub(r"[^\w\s]", " ", t2).strip()


def _title_variants_from_url(url: str) -> Iterable[str]:
    try:
        path = url.split("?", 1)[0]
        parts = [p for p in path.split("/") if p]
        if not parts:
            return []
        last = parts[-1]
        last = last.replace(".htm", "").replace(".html", "")
        # prefer directory name if last looks like index/preface
        if last in {"index", "preface", "contents"} and len(parts) >= 2:
            last = parts[-2]
        last = re.sub(r"[_-]+", " ", last).strip()
        if last:
            yield last
    except Exception:
        return []


def _wikidata_query_variants(*, title: str, author: str, title_variants: list[str]) -> list[str]:
    out: list[str] = []
    for t in title_variants[:6]:
        out.append(f"{t} {author}".strip())
        out.append(t)
    # de-dup preserving order
    dedup: list[str] = []
    for q in out:
        qn = q.strip()
        if qn and qn not in dedup:
            dedup.append(qn)
    return dedup


def _best_title_similarity(label: str, variants: list[str]) -> float:
    label_n = _norm_title(label)
    if not label_n:
        return 0.0
    best = 0.0
    for v in variants[:12]:
        s = _title_similarity(_norm_title(v), label_n)
        if s > best:
            best = s
    return best


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # token overlap + sequence ratio
    at = set(a.split())
    bt = set(b.split())
    j = len(at & bt) / max(1, len(at | bt))
    r = SequenceMatcher(a=a, b=b).ratio()
    return 0.55 * r + 0.45 * j


def _norm_title(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _extract_publication_year_candidates_from_marxists_html(
    soup: BeautifulSoup,
) -> list[tuple[int, float, str, str]]:
    """
    Best-effort: marxists.org pages often include header notes like:
    - "First Published: 1894"
    - "Published: 1848"
    - "Written: ...; Published: ..."
    We only return year-level candidates (1500-2030), as (year, score, date_type, excerpt).
    """
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Focus on top-of-page region where these notes usually live.
    head = lines[:140]

    candidates: list[tuple[int, float, str, str]] = []

    def add_from_line(line: str, *, base_score: float, tag: str) -> None:
        year = _extract_first_year_after_colon(line)
        if year is None:
            return
        if 1500 <= year <= 2030:
            candidates.append((year, base_score, tag, line[:160]))

    def _extract_first_year_after_colon(line: str) -> int | None:
        # Prefer the first year that appears after the first ":" (typical "Published: 1848"),
        # to avoid accidentally picking up other years mentioned later (e.g., "written 1917").
        _, _, tail = line.partition(":")
        haystack = tail if tail.strip() else line
        m = re.search(r"(?<!\d)(1[5-9]\d{2}|20[0-3]\d)(?!\d)", haystack)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    # Strict metadata labels: only accept header-style lines that begin with a label.
    # This avoids fragment-level sentences like "Fragment written in 1940 and first published in ...".
    label_re = re.compile(
        r"^\s*(first\s+published|published|publication\s+date|first\s+edition|first\s+printed)\s*:\s*(.*)$",
        re.IGNORECASE,
    )
    bare_labels = {
        "first published",
        "published",
        "publication date",
        "first edition",
        "first printed",
    }

    for i, ln in enumerate(head):
        label: str | None = None
        label_prefix = ln
        remainder = ""
        content_start = i + 1

        m = label_re.match(ln)
        if m:
            label = m.group(1).lower()
            label_prefix = f"{m.group(1).strip()}:"
            remainder = (m.group(2) or "").strip()
            content_start = i + 1
        else:
            # Some pages split the colon onto the next line:
            #   Published
            #   : February 1848;
            #   February 1848;
            bare = ln.strip().lower()
            if bare in bare_labels and i + 1 < len(head) and head[i + 1].lstrip().startswith(":"):
                label = bare
                label_prefix = f"{ln.strip()}:"
                after_colon = head[i + 1].split(":", 1)[1].strip() if ":" in head[i + 1] else ""
                remainder = after_colon
                content_start = i + 2

        if not label:
            continue
        # Many pages put the date on the next line (e.g., "First Published:" then "February 1848;").
        # Build a compact window with at most 2 following lines.
        label_line = label_prefix
        if label_line.strip().lower() in bare_labels and not label_line.strip().endswith(":"):
            label_line = label_line.strip() + ":"

        window_parts = [label_line]
        if remainder:
            # Keep the remainder on the same line, and allow one continuation line.
            window_parts = [f"{label_line} {remainder}".strip()]
            for j in range(content_start, min(content_start + 3, len(head))):
                next_line = head[j].strip()
                if not next_line:
                    break
                if label_re.match(next_line):
                    break
                if "source:" in next_line.lower():
                    break
                window_parts.append(next_line)
        else:
            for j in range(content_start, min(content_start + 2, len(head))):
                next_line = head[j].strip()
                if not next_line:
                    break
                # Stop at new labels.
                if label_re.match(next_line):
                    break
                # Don't pull in bibliographic/copyright blocks.
                if any(bad in next_line.lower() for bad in ["source:"]):
                    break
                window_parts.append(next_line)

        window = " ".join(window_parts)
        # Trim noisy tails that frequently include unrelated years.
        window = re.split(r"(?i)(transcribed|transcription|markup|proofread|last updated|copyleft|cc by)", window, maxsplit=1)[0]
        # Avoid capturing years from bibliographic "Source:" citations if present on same line.
        if "source:" in window.lower():
            window = re.split(r"(?i)source:", window, maxsplit=1)[0]

        if label.startswith("first published"):
            base_score = 0.92
            tag = "first_published"
        elif label.startswith("publication date"):
            base_score = 0.90
            tag = "publication_date"
        elif label.startswith("published"):
            base_score = 0.86
            tag = "published"
        else:
            base_score = 0.84
            tag = "edition"

        # Some pages include both original publication and translation publication in the same block.
        # Prefer extracting the original publication year at full confidence, but still record a lower-confidence
        # candidate for the translation year.
        lower_window = window.lower()
        if "translation published" in lower_window:
            before_translation = lower_window.split("translation published", 1)[0]
            # Use the original-candidate score for the prefix.
            add_from_line(window[: len(before_translation)], base_score=base_score, tag=tag)
            add_from_line(window, base_score=0.70, tag="translation_published")
        else:
            add_from_line(window, base_score=base_score, tag=tag)

    # De-dup by year keeping the highest score + first note.
    best_by_year: dict[int, tuple[float, str, str]] = {}
    for year, score, tag, excerpt in candidates:
        existing = best_by_year.get(year)
        if existing is None or score > existing[0]:
            best_by_year[year] = (score, tag, excerpt)

    ordered_years = sorted(best_by_year.items(), key=lambda kv: -kv[1][0])
    return [(year, score, tag, excerpt) for year, (score, tag, excerpt) in ordered_years]


def _apply_author_lifespan_penalties(
    candidates: list[PublicationDateCandidate],
    *,
    birth_year: int | None,
    death_year: int | None,
) -> list[PublicationDateCandidate]:
    if not candidates or (birth_year is None and death_year is None):
        return candidates

    out: list[PublicationDateCandidate] = []
    for c in candidates:
        y = c.date.get("year") if isinstance(c.date, dict) else None
        if not isinstance(y, int):
            out.append(c)
            continue

        score = c.score
        note: str | None = None
        if isinstance(death_year, int) and y > death_year + 5:
            score *= 0.15
            note = f"penalty:year_after_death(death_year={death_year})"
        if isinstance(birth_year, int) and y < birth_year - 10:
            score *= 0.15
            note = f"penalty:year_before_birth(birth_year={birth_year})"

        if note:
            merged_notes = "; ".join([x for x in [c.notes, note] if x]) or None
            out.append(
                PublicationDateCandidate(
                    date=c.date,
                    score=score,
                    source_name=c.source_name,
                    source_locator=c.source_locator,
                    raw_payload=c.raw_payload,
                    notes=merged_notes,
                )
            )
        else:
            out.append(c)
    return out


def _extract_publication_year_from_wikidata_entity(edata: dict[str, Any], *, qid: str) -> dict[str, Any] | None:
    # Format: {"entities": {"Q...": {"claims": {"P577": [...]}}}}
    entities = edata.get("entities")
    if not isinstance(entities, dict):
        return None
    ent = entities.get(qid)
    if not isinstance(ent, dict):
        return None
    claims = ent.get("claims")
    if not isinstance(claims, dict):
        return None
    p577 = claims.get("P577")
    if not isinstance(p577, list) or not p577:
        # fallback: inception P571
        p577 = claims.get("P571")
        if not isinstance(p577, list) or not p577:
            return None

    # Choose earliest year among provided time values.
    years: list[int] = []
    for stmt in p577:
        mainsnak = stmt.get("mainsnak") if isinstance(stmt, dict) else None
        dv = mainsnak.get("datavalue") if isinstance(mainsnak, dict) else None
        val = dv.get("value") if isinstance(dv, dict) else None
        if not isinstance(val, dict):
            continue
        time_str = val.get("time")
        if not isinstance(time_str, str):
            continue
        # "+1848-01-01T00:00:00Z"
        m = re.match(r"^[+-]?(\d{4})-", time_str)
        if not m:
            continue
        y = int(m.group(1))
        if 1500 <= y <= 2030:
            years.append(y)
    if not years:
        return None
    return {"year": min(years), "precision": "year"}


def _wikidata_best_label(edata: dict[str, Any], *, qid: str, languages: list[str]) -> str | None:
    entities = edata.get("entities")
    if not isinstance(entities, dict):
        return None
    ent = entities.get(qid)
    if not isinstance(ent, dict):
        return None
    labels = ent.get("labels")
    if not isinstance(labels, dict):
        return None
    for lang in languages:
        l = labels.get(lang)
        if isinstance(l, dict) and isinstance(l.get("value"), str):
            return l["value"]
    # fallback: any label
    for v in labels.values():
        if isinstance(v, dict) and isinstance(v.get("value"), str):
            return v["value"]
    return None


def _json_loads(text: str) -> Any:
    import json

    return json.loads(text)


def _prioritize_marxists_urls(urls: list[str]) -> list[str]:
    def score(u: str) -> tuple[int, int, str]:
        lu = u.lower()
        # Prefer archive pages (works) over PDFs or newspaper scans.
        if lu.endswith(".pdf"):
            return (9, 9, u)
        p = 5
        if "/archive/" in lu:
            p = 0
        if lu.endswith("/index.htm") or lu.endswith("/index.html"):
            p = min(p, 1)
        if lu.endswith("/preface.htm") or lu.endswith("/preface.html"):
            p = min(p, 2)
        # shorter URLs often correspond to root pages
        return (p, len(u), u)

    dedup: list[str] = []
    seen: set[str] = set()
    augmented: list[str] = []
    for u in urls:
        if not isinstance(u, str) or not u.strip():
            continue
        augmented.append(u.strip())

        # Add likely directory landing pages for better metadata capture.
        # Many marxists pages put Written/Published metadata on index/preface pages rather than chapters.
        try:
            base = u.split("?", 1)[0].split("#", 1)[0]
            if "/" in base:
                dir_url = base.rsplit("/", 1)[0] + "/"
                augmented.extend(
                    [
                        dir_url + "index.htm",
                        dir_url + "index.html",
                        dir_url + "preface.htm",
                        dir_url + "preface.html",
                    ]
                )
        except Exception:
            pass

    for u in augmented:
        if u in seen:
            continue
        seen.add(u)
        dedup.append(u)
    return sorted(dedup, key=score)


def _extract_years_from_line(line: str) -> list[int]:
    """
    Extract likely year(s) from a line, including simple ranges like:
    - 1844-45, 1844–45, 1844-1845
    We return the normalized 4-digit years we can infer.
    """
    out: list[int] = []
    s = line

    # Full 4-digit year range.
    for m in re.finditer(r"([12]\d{3})\s*[\-–]\s*([12]\d{3})", s):
        a = int(m.group(1))
        b = int(m.group(2))
        out.extend([a, b])

    # Abbreviated second year: 1844-45 -> 1844, 1845
    for m in re.finditer(r"([12]\d{3})\s*[\-–]\s*(\d{2})(?!\d)", s):
        a = int(m.group(1))
        yy = int(m.group(2))
        century = a // 100
        b = century * 100 + yy
        out.extend([a, b])

    # Standalone years.
    for m in re.finditer(r"(?<!\d)([12]\d{3})(?!\d)", s):
        out.append(int(m.group(1)))

    # De-dup preserving order.
    dedup: list[int] = []
    seen: set[int] = set()
    for y in out:
        if y in seen:
            continue
        seen.add(y)
        dedup.append(y)
    return dedup


def _wikidata_extract_item_qids(edata: dict[str, Any], *, qid: str, prop: str) -> list[str]:
    entities = edata.get("entities")
    if not isinstance(entities, dict):
        return []
    ent = entities.get(qid)
    if not isinstance(ent, dict):
        return []
    claims = ent.get("claims")
    if not isinstance(claims, dict):
        return []
    stmts = claims.get(prop)
    if not isinstance(stmts, list):
        return []
    out: list[str] = []
    for stmt in stmts:
        mainsnak = stmt.get("mainsnak") if isinstance(stmt, dict) else None
        dv = mainsnak.get("datavalue") if isinstance(mainsnak, dict) else None
        val = dv.get("value") if isinstance(dv, dict) else None
        if isinstance(val, dict) and isinstance(val.get("id"), str):
            out.append(val["id"])
    return out


def _best_author_similarity(candidate_author_labels: list[str], author_variants: list[str]) -> float:
    best = 0.0
    for cand in candidate_author_labels:
        cand_n = _norm_title(cand)
        for v in author_variants:
            s = _title_similarity(_norm_title(v), cand_n)
            if s > best:
                best = s
    return best


def _is_likely_written_work(instance_labels: list[str]) -> bool:
    if not instance_labels:
        return False
    pos = {
        "book",
        "written work",
        "literary work",
        "essay",
        "pamphlet",
        "article",
        "speech",
        "treatise",
        "monograph",
        "text",
        "novel",
    }
    neg = {
        "concept",
        "theory",
        "doctrine",
        "ideology",
        "philosophical concept",
        "school",
        "movement",
        "method",
        "approach",
    }
    seen_pos = False
    for lbl in instance_labels:
        l = _norm_title(lbl)
        if any(p in l for p in pos):
            seen_pos = True
        if any(n in l for n in neg) and not any(p in l for p in pos):
            # A pure concept/theory (with no positive written-work signal) should be rejected.
            return False
    return seen_pos
