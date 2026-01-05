from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from hashlib import sha256
from typing import Any

from ingest_service.metadata.http_cached import CachedHttpClient


@dataclass(frozen=True)
class AuthorLifespanCandidate:
    birth_year: int | None
    death_year: int | None
    score: float
    source_name: str
    source_locator: str | None
    raw_payload: dict[str, Any] | None
    notes: str | None = None


class AuthorLifespanResolver:
    def __init__(self, *, http: CachedHttpClient) -> None:
        self.http = http

    def resolve(
        self,
        *,
        author_name: str,
        author_aliases: list[str],
        sources: list[str],
        max_candidates: int = 5,
    ) -> list[AuthorLifespanCandidate]:
        if "wikidata" not in set(sources):
            return []

        variants = [author_name] + [a for a in author_aliases if a != author_name]
        out: list[AuthorLifespanCandidate] = []

        current_year = datetime.now(timezone.utc).year

        for q in variants[:5]:
            resp = self.http.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbsearchentities",
                    "search": q,
                    "language": "en",
                    "format": "json",
                    "limit": 8,
                },
                accept="application/json",
            )
            if resp.status_code != 200 or not resp.text:
                continue
            try:
                data = _json_loads(resp.text)
            except Exception:
                continue
            results = data.get("search") if isinstance(data, dict) else None
            if not isinstance(results, list):
                continue

            for r in results[:8]:
                if not isinstance(r, dict) or not isinstance(r.get("id"), str):
                    continue
                qid = r["id"]
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

                label = _wikidata_best_label(edata, qid=qid, languages=["en"])
                if not label:
                    continue

                sim = _best_name_similarity(label, variants)
                if sim < 0.82:
                    continue

                if not _wikidata_is_human(edata, qid=qid):
                    continue

                birth_year = _wikidata_extract_year(edata, qid=qid, prop="P569")
                death_year = _wikidata_extract_year(edata, qid=qid, prop="P570")

                # Require at least one year to be useful.
                if birth_year is None and death_year is None:
                    continue

                # Plausibility: if death is missing but birth implies implausible age, reject.
                if birth_year is not None and death_year is None:
                    if birth_year <= current_year - 110:
                        continue

                # Plausibility: reject future years.
                if birth_year is not None and birth_year > current_year:
                    continue
                if death_year is not None and death_year > current_year:
                    continue

                completeness_bonus = 0.08 if (birth_year is not None and death_year is not None) else 0.0

                score = min(0.99, 0.6 + 0.35 * sim + completeness_bonus)
                out.append(
                    AuthorLifespanCandidate(
                        birth_year=birth_year,
                        death_year=death_year,
                        score=score,
                        source_name="wikidata",
                        source_locator=f"wikidata:{qid}",
                        raw_payload={
                            "qid": qid,
                            "label": label,
                            "similarity": sim,
                            "birth_year": birth_year,
                            "death_year": death_year,
                        },
                        notes="Wikidata human lifespan candidate",
                    )
                )
        # Return best candidates (higher score first).
        return sorted(out, key=lambda c: -c.score)[:max_candidates]


def _best_name_similarity(label: str, variants: list[str]) -> float:
    best = 0.0
    ln = _norm(label)
    for v in variants:
        s = SequenceMatcher(a=_norm(v), b=ln).ratio()
        if s > best:
            best = s
    return best


def _norm(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


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
    for v in labels.values():
        if isinstance(v, dict) and isinstance(v.get("value"), str):
            return v["value"]
    return None


def _wikidata_is_human(edata: dict[str, Any], *, qid: str) -> bool:
    # P31 instance of should include Q5 (human).
    qids = _wikidata_extract_item_qids(edata, qid=qid, prop="P31")
    return "Q5" in qids


def _wikidata_extract_year(edata: dict[str, Any], *, qid: str, prop: str) -> int | None:
    entities = edata.get("entities")
    if not isinstance(entities, dict):
        return None
    ent = entities.get(qid)
    if not isinstance(ent, dict):
        return None
    claims = ent.get("claims")
    if not isinstance(claims, dict):
        return None
    stmts = claims.get(prop)
    if not isinstance(stmts, list) or not stmts:
        return None
    # Choose first; Wikidata often has one value for birth/death.
    for stmt in stmts:
        mainsnak = stmt.get("mainsnak") if isinstance(stmt, dict) else None
        dv = mainsnak.get("datavalue") if isinstance(mainsnak, dict) else None
        val = dv.get("value") if isinstance(dv, dict) else None
        if not isinstance(val, dict):
            continue
        time_str = val.get("time")
        if not isinstance(time_str, str):
            continue
        m = re.match(r"^[+-]?(\d{4})-", time_str)
        if not m:
            continue
        y = int(m.group(1))
        if 1200 <= y <= 2030:
            return y
    return None


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


def _json_loads(text: str) -> Any:
    import json

    return json.loads(text)
