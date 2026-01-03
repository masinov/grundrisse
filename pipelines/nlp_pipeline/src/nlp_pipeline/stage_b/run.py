from __future__ import annotations

import json
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy import select

from grundrisse_contracts.validate import ValidationError, validate_json
from grundrisse_core.db.models import (
    Concept,
    ConceptMention,
    Edition,
    ExtractionRun,
    Paragraph,
    SentenceSpan,
    TextBlock,
    Work,
)
from grundrisse_core.db.session import SessionLocal
from nlp_pipeline.llm.client import LLMClient
from nlp_pipeline.settings import settings
from nlp_pipeline.stage_b.prompts import render_b_prompt, render_b_repair_prompt
from grundrisse_core.db.enums import BlockSubtype


@dataclass(frozen=True)
class SchemasB:
    b: dict[str, Any]


STAGE_B_PROMPT_NAME = "task_b_concept_canonicalize"
STAGE_B_PROMPT_VERSION = "v1"


def run_stage_b_for_work(
    *,
    work_id: uuid.UUID,
    llm: LLMClient,
    schemas: SchemasB,
    max_cluster_size: int = 50,
    min_cluster_size: int = 2,
    progress_every: int = 20,
    commit_every: int = 10,
    include_apparatus: bool = False,
) -> None:
    """
    Stage B: cluster ConceptMentions and canonicalize into Concept nodes.

    Idempotent behavior:
    - only processes mentions with ConceptMention.concept_id IS NULL
    - safe to rerun
    """
    with SessionLocal() as session:
        work = session.get(Work, work_id)
        if work is None:
            raise RuntimeError(f"Work not found: {work_id}")

        mentions = _load_unassigned_mentions_for_work(session, work_id=work_id, include_apparatus=include_apparatus)
        print(f"[stage-b] work_id={work_id} unassigned_mentions={len(mentions)}")
        if not mentions:
            print("[stage-b] nothing to do")
            return

        clusters = _cluster_mentions(mentions)
        # Drop singletons by default (low value for canonicalization).
        clusters = [c for c in clusters if len(c) >= min_cluster_size]
        clusters.sort(key=len, reverse=True)

        print(f"[stage-b] clusters={len(clusters)} (min_cluster_size={min_cluster_size})")

        pending = 0
        for idx, cluster in enumerate(clusters, start=1):
            if progress_every > 0 and (idx == 1 or idx % progress_every == 0):
                print(f"[stage-b] cluster {idx}/{len(clusters)} size={len(cluster)}")

            payload = _build_cluster_payload(cluster, max_items=max_cluster_size)
            output, resp = _call_b_with_retries(llm=llm, schemas=schemas, payload=payload)

            run = _create_extraction_run(
                session=session,
                model_name=resp.model_name,
                prompt_name=STAGE_B_PROMPT_NAME,
                prompt_version=STAGE_B_PROMPT_VERSION,
                input_refs={"work_id": str(work_id), "mention_ids": [m["mention_id"] for m in payload["mentions"]]},
                output_obj=output,
                usage={
                    "prompt_tokens": resp.prompt_tokens,
                    "completion_tokens": resp.completion_tokens,
                    "cost_usd": resp.cost_usd,
                },
            )

            _persist_b_output(session, output, run_id=run.run_id, work_id=work_id)

            pending += 1
            if commit_every > 0 and pending >= commit_every:
                session.commit()
                pending = 0

        if pending:
            session.commit()
        print("[stage-b] done")


def _load_unassigned_mentions_for_work(
    session, *, work_id: uuid.UUID, include_apparatus: bool
) -> list[dict[str, Any]]:
    """
    Load mentions with enough context for canonicalization.
    """
    skip_subtypes = {BlockSubtype.toc, BlockSubtype.navigation, BlockSubtype.license, BlockSubtype.metadata, BlockSubtype.study_guide}
    stmt = (
        select(
            ConceptMention.mention_id,
            ConceptMention.surface_form,
            ConceptMention.normalized_form,
            ConceptMention.is_technical,
            ConceptMention.candidate_gloss,
            ConceptMention.confidence,
            SentenceSpan.span_id,
            SentenceSpan.sent_index,
            SentenceSpan.text,
            Paragraph.para_id,
            Paragraph.edition_id,
            TextBlock.block_subtype,
        )
        .select_from(ConceptMention)
        .join(SentenceSpan, SentenceSpan.span_id == ConceptMention.span_id)
        .join(Paragraph, Paragraph.para_id == SentenceSpan.para_id)
        .join(TextBlock, TextBlock.block_id == Paragraph.block_id)
        .join(Edition, Edition.edition_id == Paragraph.edition_id)
        .where(Edition.work_id == work_id)
        .where(ConceptMention.concept_id.is_(None))
    )

    if not include_apparatus:
        from sqlalchemy import or_

        stmt = stmt.where(or_(TextBlock.block_subtype.is_(None), TextBlock.block_subtype.not_in(skip_subtypes)))

    rows = session.execute(stmt).all()

    mentions: list[dict[str, Any]] = []
    for r in rows:
        mentions.append(
            {
                "mention_id": str(r.mention_id),
                "surface_form": r.surface_form,
                "normalized_form": r.normalized_form,
                "is_technical": r.is_technical,
                "candidate_gloss": r.candidate_gloss,
                "confidence": r.confidence,
                "span_id": str(r.span_id),
                "sent_index": r.sent_index,
                "sentence_text": r.text,
                "para_id": str(r.para_id),
                "edition_id": str(r.edition_id),
            }
        )
    return mentions


def _cluster_mentions(mentions: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in mentions:
        key = _cluster_key(m.get("normalized_form") or m.get("surface_form") or "")
        if not key:
            continue
        buckets[key].append(m)
    return list(buckets.values())


_NONWORD = re.compile(r"[^\w\-]+", re.UNICODE)


def _cluster_key(text: str) -> str:
    t = text.strip().lower()
    t = _NONWORD.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _build_cluster_payload(cluster: list[dict[str, Any]], *, max_items: int) -> dict[str, Any]:
    # Keep payload bounded.
    items = cluster
    if len(items) > max_items:
        items = sorted(items, key=lambda x: (x.get("confidence") is None, -(x.get("confidence") or 0.0)))[:max_items]

    return {
        "mentions": [
            {
                "mention_id": m["mention_id"],
                "surface_form": m["surface_form"],
                "normalized_form": m.get("normalized_form"),
                "candidate_gloss": m.get("candidate_gloss"),
                "is_technical": m.get("is_technical"),
                "confidence": m.get("confidence"),
                "span_id": m["span_id"],
                "sentence_text": m["sentence_text"],
                "para_id": m["para_id"],
                "edition_id": m["edition_id"],
            }
            for m in items
        ]
    }


def _call_b_with_retries(
    *,
    llm: LLMClient,
    schemas: SchemasB,
    payload: dict[str, Any],
    max_attempts: int = 3,
) -> tuple[dict[str, Any], Any]:
    """
    Stage B is more error-prone than Stage A: schema drift or invalid JSON can happen.
    Treat validation failures as recoverable by re-asking with a strict repair prompt.
    """
    last_error: str | None = None
    prior_raw: str = ""

    for attempt in range(1, max_attempts + 1):
        if attempt == 1:
            prompt = render_b_prompt(payload=payload, schema=schemas.b)
        else:
            prompt = render_b_repair_prompt(
                payload=payload,
                schema=schemas.b,
                validation_error=last_error or "unknown validation error",
                prior_output=prior_raw,
            )

        resp = llm.complete_json(prompt=prompt, schema=schemas.b)
        prior_raw = resp.raw_text or ""

        if resp.json is None:
            last_error = f"B response was not valid JSON. raw={prior_raw[:500]!r}"
            time.sleep(0.75 * attempt)
            continue

        try:
            normalized = _normalize_b_output(resp.json)
            validate_json(normalized, schemas.b)
            return normalized, resp
        except ValidationError as exc:
            last_error = str(exc)
            time.sleep(0.75 * attempt)
            continue

    raise ValidationError(last_error or "Stage B failed after retries")


_TRAILING_COLON = re.compile(r"\s*:\s*$")


def _normalize_b_output(output: dict[str, Any]) -> dict[str, Any]:
    """
    Narrow tolerance for common LLM key drift:
    - strip whitespace and trailing ':' from keys (e.g. 'gloss:' -> 'gloss')
    - if `gloss` is missing but a near-miss key clearly contains the gloss text, map it to `gloss`
    This is intentionally conservative; ambiguous cases fall back to retry.
    """

    def normalize_key(key: str) -> str:
        k = key.strip()
        k = _TRAILING_COLON.sub("", k)
        return k

    def normalize_obj(obj: Any) -> Any:
        if isinstance(obj, list):
            return [normalize_obj(x) for x in obj]
        if not isinstance(obj, dict):
            return obj

        # Detect unambiguous gloss typos before key normalization collapses them.
        maybe_gloss_value: str | None = None
        gloss_from_vernacular_typo = False
        if "gloss" not in obj:
            for k, v in obj.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                k_stripped = k.strip().lower()
                if k_stripped in {"gloss:", "gloss :"}:
                    maybe_gloss_value = v
                    break
                if k_stripped in {"original_term_vernacular:", "original_term_vernacular :"}:
                    # Only treat this as gloss if it looks like prose, not a single vernacular term.
                    if len(v.strip()) >= 25 and (" " in v.strip() or v.strip().endswith(".")):
                        maybe_gloss_value = v
                        gloss_from_vernacular_typo = True
                        break

        out: dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str):
                out[normalize_key(k)] = normalize_obj(v)
            else:
                out[k] = normalize_obj(v)

        if "gloss" not in out and maybe_gloss_value is not None:
            out["gloss"] = maybe_gloss_value.strip()
            # If we used a vernacular-key typo to recover the gloss, avoid polluting
            # `original_term_vernacular` with prose text.
            if gloss_from_vernacular_typo and out.get("original_term_vernacular") == maybe_gloss_value:
                out["original_term_vernacular"] = None

        return out

    normalized = normalize_obj(output)
    return normalized if isinstance(normalized, dict) else output


def _concept_label_key(label: str) -> str:
    return _cluster_key(label)


def _find_existing_concept_for_work(session, *, work_id: uuid.UUID, label_canonical: str) -> Concept | None:
    """
    Avoid creating duplicate concepts for the same work when Stage B is re-run or when clustering
    splits superficial variants.

    Conservative behavior: only reuse an existing Concept if it is already used by at least one
    ConceptMention within the same work.
    """
    key = _concept_label_key(label_canonical)
    if not key:
        return None

    return session.scalar(
        select(Concept)
        .join(ConceptMention, ConceptMention.concept_id == Concept.concept_id)
        .join(SentenceSpan, SentenceSpan.span_id == ConceptMention.span_id)
        .join(Paragraph, Paragraph.para_id == SentenceSpan.para_id)
        .join(Edition, Edition.edition_id == Paragraph.edition_id)
        .where(Edition.work_id == work_id)
        .where(func.lower(Concept.label_canonical) == key)
        .limit(1)
    )


def _persist_b_output(session, output: dict[str, Any], *, run_id: uuid.UUID, work_id: uuid.UUID) -> None:
    concepts = output.get("concepts") or []
    rejected = output.get("rejected_mentions") or []

    # Create concepts.
    created_or_reused: dict[str, uuid.UUID] = {}
    for c in concepts:
        label = c["label_canonical"]
        label_key = _concept_label_key(label)

        existing_id = created_or_reused.get(label_key)
        concept: Concept | None = session.get(Concept, existing_id) if existing_id else None
        if concept is None:
            concept = _find_existing_concept_for_work(session, work_id=work_id, label_canonical=label)

        if concept is None:
            concept = Concept(
                concept_id=uuid.uuid4(),
                label_canonical=label,
                label_short=c.get("label_short"),
                original_term_vernacular=c.get("original_term_vernacular"),
                aliases=[],
                gloss=c["gloss"],
                sense_notes=None,
                root_concept_id=None,
                parent_concept_id=None,
                temporal_scope=c.get("temporal_scope"),
                status="proposed",
                created_run_id=run_id,
                confidence=None,
            )
            session.add(concept)
            session.flush()

        created_or_reused[label_key] = concept.concept_id

        for mention_id in c.get("assigned_mention_ids", []):
            try:
                mid = uuid.UUID(mention_id)
            except Exception:
                continue
            mention = session.get(ConceptMention, mid)
            if mention is None:
                continue
            if mention.concept_id is None:
                mention.concept_id = concept.concept_id

    # Mark rejected mentions by leaving them unassigned; we don’t persist reasons yet.
    _ = rejected


def _create_extraction_run(
    *,
    session,
    model_name: str,
    prompt_name: str,
    prompt_version: str,
    input_refs: dict[str, Any],
    output_obj: dict[str, Any],
    usage: dict[str, Any],
) -> ExtractionRun:
    output_bytes = json.dumps(output_obj, sort_keys=True).encode("utf-8")
    run = ExtractionRun(
        pipeline_version="v0",
        git_commit_hash=None,
        model_name=model_name,
        model_fingerprint=None,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        params={"temperature": settings.llm_temperature, "max_tokens": settings.llm_max_tokens},
        input_refs=input_refs,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        cost_usd=usage.get("cost_usd"),
        output_hash=sha256(output_bytes).hexdigest(),
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        status="succeeded",
        error_log=None,
    )
    session.add(run)
    session.flush()
    return run
