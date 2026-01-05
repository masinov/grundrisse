from __future__ import annotations

import re
from dataclasses import replace
from dataclasses import dataclass
from typing import Any

from ingest_service.parse.marxists_header_metadata import parse_dateish


@dataclass(frozen=True)
class DateCandidate:
    role: str
    date: dict[str, Any]
    confidence: float
    source_name: str
    source_locator: str | None
    provenance: dict[str, Any]
    notes: str | None = None


_COLLECTED_MARKERS = (
    "collected works",
    "selected works",
    "progress publishers",
    "foreign languages publishing house",
    "volume",
    "vol.",
    "selected articles",
    "selected writings",
    "selected works of",
    "works volume",
)

_PERIODICAL_MARKERS = (
    "no.",
    "issue",
    "whole no.",
    "vol.",
    "pp.",
    "pravda",
    "iskra",
    "new international",
    "monthly review",
    "review",
    "gazette",
    "bulletin",
    "journal",
    "new york",
)


def marxists_line_has_periodical_markers(line: str | None) -> bool:
    if not line or not isinstance(line, str):
        return False
    lower = line.lower()
    return any(m in lower for m in _PERIODICAL_MARKERS)


def _marxists_date_role_for_header_line(
    *,
    line: str | None,
    source_kind: str,
    default_role: str,
    edition_confidence_cap: float,
) -> tuple[str, str | None, float | None]:
    """
    Decide whether a marxists header-derived date should be treated as:
      - `first_publication_date` (e.g., "Pravda No. 49, March 4, 1923")
      - `edition_publication_date` (e.g., "Collected Works ... Progress Publishers ... Volume ...")

    Important nuance: many marxists pages cite a *Collected Works* volume in `Source:`,
    while the actual *first publication* appears in `First Published:`. We should not
    demote those just because `Source:` is edition-like.
    """
    if isinstance(line, str):
        if marxists_line_has_periodical_markers(line):
            return "first_publication_date", None, None
        if marxists_line_has_edition_markers(line):
            return "edition_publication_date", "edition_contamination", edition_confidence_cap

    if source_kind == "edition":
        return "edition_publication_date", "edition_contamination", edition_confidence_cap

    return default_role, None, None


def classify_marxists_source_kind(source_line: str | None) -> str:
    """
    Classify the header `Source:` line into:
      - edition: selected/collected works, publishers, volumes (high contamination risk)
      - periodical: issue/journal/newspaper-like citations
      - unknown
    """
    if not source_line or not isinstance(source_line, str):
        return "unknown"
    lower = source_line.lower()
    if any(m in lower for m in _COLLECTED_MARKERS):
        return "edition"
    # Periodical / issue-ish markers.
    if marxists_line_has_periodical_markers(source_line):
        return "periodical"
    return "unknown"


def marxists_line_has_edition_markers(line: str | None) -> bool:
    if not line or not isinstance(line, str):
        return False
    lower = line.lower()
    return any(m in lower for m in _COLLECTED_MARKERS)


def derive_display_date(*, bundle: dict[str, Any]) -> tuple[dict[str, Any] | None, str, int | None]:
    """
    Rule: display first_publication_date if available, else written_date.

    If a year looks like an upload/transcription/public-domain timestamp, it should be
    classified as `ingest_upload_year` during candidate construction so it won't become
    `first_publication_date` in the bundle.

    Returns (display_date, display_date_field, display_year).
    """
    first_pub = bundle.get("first_publication_date")
    if isinstance(first_pub, dict) and isinstance(first_pub.get("date"), dict):
        d = dict(first_pub["date"])
        d["confidence"] = first_pub.get("confidence")
        d["source"] = first_pub.get("source")
        return d, "first_publication_date", _year_from(d)

    written = bundle.get("written_date")
    if isinstance(written, dict) and isinstance(written.get("date"), dict):
        d = dict(written["date"])
        d["confidence"] = written.get("confidence")
        d["source"] = written.get("source")
        return d, "written_date", _year_from(d)

    return None, "unknown", None


def _year_from(d: dict[str, Any]) -> int | None:
    y = d.get("year")
    return y if isinstance(y, int) else None


def best_candidate(cands: list[DateCandidate]) -> DateCandidate | None:
    if not cands:
        return None
    return sorted(cands, key=lambda c: (-c.confidence, c.source_name, str(c.source_locator or "")))[0]


def build_candidates_from_edition_source_metadata(
    *,
    edition_id: str,
    source_url: str | None,
    source_metadata: dict[str, Any] | None,
) -> list[DateCandidate]:
    if not source_metadata or not isinstance(source_metadata, dict):
        return []
    fields = source_metadata.get("fields")
    dates = source_metadata.get("dates")
    if not isinstance(fields, dict) or not isinstance(dates, dict):
        return []

    out: list[DateCandidate] = []

    source_line = fields.get("Source") if isinstance(fields.get("Source"), str) else None
    published_line = fields.get("Published") if isinstance(fields.get("Published"), str) else None
    first_published_line = fields.get("First Published") if isinstance(fields.get("First Published"), str) else None

    source_kind = classify_marxists_source_kind(source_line)
    edition_like_source = source_kind == "edition"

    def prov(field: str, raw: str | None) -> dict[str, Any]:
        return {
            "edition_id": edition_id,
            "source_url": source_url,
            "header_field": field,
            "header_value": raw,
            "source_kind": source_kind,
        }

    written = dates.get("written")
    if isinstance(written, dict) and isinstance(written.get("year"), int):
        out.append(
            DateCandidate(
                role="written_date",
                date=_strip_raw(written),
                confidence=0.85,
                source_name="marxists_source_metadata",
                source_locator=source_url,
                provenance=prov("Written", fields.get("Written") if isinstance(fields.get("Written"), str) else None),
            )
        )

    first_pub = dates.get("first_published")
    if isinstance(first_pub, dict) and isinstance(first_pub.get("year"), int):
        role, note, cap = _marxists_date_role_for_header_line(
            line=first_published_line,
            source_kind=source_kind,
            default_role="first_publication_date",
            edition_confidence_cap=0.60,
        )
        conf = 0.95
        if cap is not None:
            conf = min(conf, cap)
        out.append(
            DateCandidate(
                role=role,
                date=_strip_raw(first_pub),
                confidence=conf,
                source_name="marxists_source_metadata",
                source_locator=source_url,
                provenance=prov("First Published", first_published_line),
                notes=note,
            )
        )

    published = dates.get("published")
    if isinstance(published, dict) and isinstance(published.get("year"), int):
        role, note, cap = _marxists_date_role_for_header_line(
            line=published_line,
            source_kind=source_kind,
            default_role="first_publication_date",
            edition_confidence_cap=0.55,
        )
        conf = 0.90
        if cap is not None:
            conf = min(conf, cap)
        out.append(
            DateCandidate(
                role=role,
                date=_strip_raw(published),
                confidence=conf,
                source_name="marxists_source_metadata",
                source_locator=source_url,
                provenance=prov("Published", published_line),
                notes=note,
            )
        )

    # Source line often includes a periodical issue date (e.g., "New International ... July 1944").
    if not edition_like_source and source_line:
        parsed = parse_dateish(source_line)
        if isinstance(parsed, dict) and isinstance(parsed.get("year"), int):
            out.append(
                DateCandidate(
                    role="first_publication_date",
                    date=_strip_raw(parsed),
                    confidence=0.90 if source_kind == "periodical" else 0.75,
                    source_name="marxists_source_metadata",
                    source_locator=source_url,
                    provenance=prov("Source", source_line),
                )
            )

    return out


_YEAR_RE = re.compile(r"^\d{4}$")

_UPLOAD_MARKERS = (
    "internet archive",
    "marxists internet archive",
    "transcription",
    "markup",
    "mark-up",
    "proofread",
    "public domain",
    "copyleft",
    "copyright",
)


def build_candidates_from_work_metadata_evidence_row(
    *,
    source_name: str,
    score: float | None,
    extracted: dict[str, Any] | None,
    raw_payload: dict[str, Any] | None,
    source_locator: str | None,
) -> list[DateCandidate]:
    if not extracted or not isinstance(extracted, dict):
        return []
    y = extracted.get("year")
    if not isinstance(y, int) and isinstance(y, str) and _YEAR_RE.match(y):
        y = int(y)
    if not isinstance(y, int):
        return []

    confidence = float(score) if isinstance(score, (int, float)) else 0.0
    role = "first_publication_date"
    notes: str | None = None

    # Heuristic URL years are useful as a last resort but should never be treated as strong evidence.
    if source_name == "heuristic_url_year":
        return [
            DateCandidate(
                role="heuristic_publication_year",
                date={
                    "year": y,
                    "month": extracted.get("month"),
                    "day": extracted.get("day"),
                    "precision": extracted.get("precision") or "year",
                    "method": extracted.get("method") or source_name,
                },
                confidence=confidence,
                source_name=source_name,
                source_locator=source_locator,
                provenance={"raw_payload": raw_payload},
            )
        ]

    # A key gotcha: our earlier pipeline stored marxists header-derived years as "publication" even when the
    # header clearly refers to a *Collected Works/Selected Works/Volume* edition (i.e., not true first-publication).
    # When the raw payload includes the header fields, detect "edition" markers and re-route accordingly.
    if source_name in {"marxists_ingested_html", "marxists", "marxists_source_metadata"}:
        header = raw_payload.get("header") if isinstance(raw_payload, dict) else None
        fields = header.get("fields") if isinstance(header, dict) else None
        if isinstance(fields, dict):
            src_line = fields.get("Source") if isinstance(fields.get("Source"), str) else None
            pub_line = fields.get("Published") if isinstance(fields.get("Published"), str) else None
            fp_line = fields.get("First Published") if isinstance(fields.get("First Published"), str) else None

            source_kind = classify_marxists_source_kind(src_line)
            edition_like = (
                source_kind == "edition"
                or marxists_line_has_edition_markers(pub_line)
                or marxists_line_has_edition_markers(fp_line)
            )
            if edition_like:
                role = "edition_publication_date"
                notes = "edition_contamination"
                # Keep it present for auditing, but reduce confidence so it won't accidentally dominate.
                confidence = min(confidence, 0.55)
            else:
                header_field = raw_payload.get("header_field") if isinstance(raw_payload, dict) else None
                header_value = (
                    fields.get(header_field)
                    if isinstance(header_field, str) and isinstance(fields.get(header_field), str)
                    else None
                )
                if isinstance(header_value, str) and any(m in header_value.lower() for m in _UPLOAD_MARKERS):
                    role = "ingest_upload_year"
                    notes = "upload_or_transcription_year"
                    confidence = min(confidence, 0.25)
        else:
            # Some legacy marxists-derived evidence (e.g. `marxists_page`) stores a human excerpt instead of header fields.
            # Detect edition contamination and upload/transcription years from that excerpt to avoid polluting
            # `first_publication_date` with Collected/Selected Works edition years.
            excerpt = raw_payload.get("excerpt") if isinstance(raw_payload, dict) else None
            if isinstance(excerpt, str):
                lower_excerpt = excerpt.lower()
                if any(m in lower_excerpt for m in _COLLECTED_MARKERS):
                    role = "edition_publication_date"
                    notes = "edition_contamination"
                    confidence = min(confidence, 0.55)
                elif any(m in lower_excerpt for m in _UPLOAD_MARKERS):
                    role = "ingest_upload_year"
                    notes = "upload_or_transcription_year"
                    confidence = min(confidence, 0.25)

    return [
        DateCandidate(
            role=role,
            date={
                "year": y,
                "month": extracted.get("month"),
                "day": extracted.get("day"),
                "precision": extracted.get("precision") or "year",
                "method": extracted.get("method") or source_name,
            },
            confidence=confidence,
            source_name=source_name,
            source_locator=source_locator,
            provenance={"raw_payload": raw_payload},
            notes=notes,
        )
    ]


def adjust_candidates_for_author_lifespan(
    *,
    candidates: list[DateCandidate],
    birth_year: int | None,
    death_year: int | None,
) -> list[DateCandidate]:
    """
    Adjust candidate confidence/roles based on author lifespan plausibility.

    We do NOT delete candidates; we:
    - reclassify clearly edition-ish OpenLibrary "first_publish_year" beyond death into edition_publication_date
    - downweight implausible years for other sources (but keep them for audit/provenance)
    """

    def add_note(existing: str | None, note: str) -> str:
        if not existing:
            return note
        if note in existing:
            return existing
        return f"{existing};{note}"

    out: list[DateCandidate] = []
    for c in candidates:
        y = c.date.get("year")
        if not isinstance(y, int):
            out.append(c)
            continue

        # Too far after death: almost always an edition/catalogue year, not first publication.
        if death_year is not None and y > death_year + 5:
            if c.source_name == "openlibrary" and c.role == "first_publication_date":
                out.append(
                    replace(
                        c,
                        role="edition_publication_date",
                        confidence=min(c.confidence, 0.40),
                        notes=add_note(c.notes, "after_death_openlibrary_demoted"),
                    )
                )
                continue

            out.append(
                replace(
                    c,
                    confidence=min(c.confidence * 0.15, c.confidence),
                    notes=add_note(c.notes, "after_death_penalized"),
                )
            )
            continue

        # Too far before birth: usually an entity-resolution mismatch.
        if birth_year is not None and y < birth_year - 10:
            out.append(
                replace(
                    c,
                    confidence=min(c.confidence * 0.15, c.confidence),
                    notes=add_note(c.notes, "before_birth_penalized"),
                )
            )
            continue

        out.append(c)

    return out


def _strip_raw(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "year": d.get("year"),
        "month": d.get("month"),
        "day": d.get("day"),
        "precision": d.get("precision") or "year",
    }
