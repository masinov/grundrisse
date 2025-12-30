from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import select

from grundrisse_contracts.validate import ValidationError, validate_json
from grundrisse_core.db.session import SessionLocal
from grundrisse_core.db.models import (
    Claim,
    ClaimEvidence,
    ConceptMention,
    Edition,
    ExtractionRun,
    Paragraph,
    SentenceSpan,
    SpanGroup,
    SpanGroupSpan,
    TextBlock,
    Work,
)
from grundrisse_core.db.enums import ClaimAttribution, ClaimType, DialecticalStatus, Modality, Polarity
from nlp_pipeline.llm.client import LLMClient
from nlp_pipeline.stage_a.context import build_context_window
from nlp_pipeline.stage_a.prompts import render_a1_prompt, render_a3_prompt
from nlp_pipeline.settings import settings


@dataclass(frozen=True)
class Schemas:
    a1: dict[str, Any]
    a3: dict[str, Any]

STAGE_A1_PROMPT_NAME = "task_a1_concept_mentions"
STAGE_A1_PROMPT_VERSION = "v1"
STAGE_A3_PROMPT_NAME = "task_a3_claims"
STAGE_A3_PROMPT_VERSION = "v1"


def run_stage_a_for_edition(
    *,
    edition_id: uuid.UUID,
    llm: LLMClient,
    schemas: Schemas,
    progress_every: int = 10,
    commit_every: int = 5,
) -> None:
    """
    Minimal Day-1 implementation:
    - Iterate paragraphs in order.
    - Build context window (prev paragraph tail + target sentences).
    - Call A1 and A3 and validate strict schemas.
    - Persist ExtractionRun + ConceptMentions + Claims + evidence SpanGroups.
    """
    with SessionLocal() as session:
        edition = session.get(Edition, edition_id)
        if edition is None:
            raise RuntimeError(f"Edition not found: {edition_id}")

        work = session.get(Work, edition.work_id)
        if work is None:
            raise RuntimeError(f"Work not found for edition: {edition.work_id}")

        paragraphs = session.scalars(
            select(Paragraph).where(Paragraph.edition_id == edition_id).order_by(Paragraph.order_index)
        ).all()
        total = len(paragraphs)
        print(f"[stage-a] edition_id={edition_id} work_id={work.work_id} paragraphs={total}")

        processed_para_ids = _prefetch_stage_a_processed_para_ids(session, paragraphs)
        if processed_para_ids:
            print(f"[stage-a] already_processed={len(processed_para_ids)} (will skip)")

        # Prefetch blocks and sentence spans to reduce DB chatter.
        block_ids = {p.block_id for p in paragraphs}
        blocks = {
            b.block_id: b
            for b in session.scalars(select(TextBlock).where(TextBlock.block_id.in_(block_ids))).all()
        }
        para_ids = [p.para_id for p in paragraphs]
        spans_by_para: dict[uuid.UUID, list[SentenceSpan]] = {pid: [] for pid in para_ids}
        for span in session.scalars(
            select(SentenceSpan)
            .where(SentenceSpan.para_id.in_(para_ids))
            .order_by(SentenceSpan.para_id, SentenceSpan.sent_index)
        ).all():
            spans_by_para[span.para_id].append(span)

        prev_para_id: uuid.UUID | None = None
        prev_sent_texts: list[str] | None = None

        pending_commits = 0
        skipped = 0
        for idx, paragraph in enumerate(paragraphs, start=1):
            if progress_every > 0 and (idx == 1 or idx % progress_every == 0):
                print(f"[stage-a] paragraph {idx}/{total} para_id={paragraph.para_id} skipped={skipped}")
            spans = spans_by_para.get(paragraph.para_id, [])
            if paragraph.para_id in processed_para_ids:
                skipped += 1
                prev_para_id = paragraph.para_id
                prev_sent_texts = [s.text for s in spans]
                continue
            target_sentences = [s.text for s in spans]
            if not target_sentences:
                prev_para_id = paragraph.para_id
                prev_sent_texts = []
                continue

            ctx = build_context_window(prev_sent_texts, target_sentences, max_context_sentences=2)

            block = blocks.get(paragraph.block_id)
            effective_author_id = block.author_id_override if block and block.author_id_override else work.author_id

            try:
                _call_a1(
                    session=session,
                    llm=llm,
                    schemas=schemas,
                    ctx=ctx,
                    spans=spans,
                    paragraph=paragraph,
                    effective_author_id=effective_author_id,
                )
                _call_a3(
                    session=session,
                    llm=llm,
                    schemas=schemas,
                    ctx=ctx,
                    spans=spans,
                    paragraph=paragraph,
                    effective_author_id=effective_author_id,
                )
                pending_commits += 1
                if commit_every > 0 and pending_commits >= commit_every:
                    session.commit()
                    pending_commits = 0
            except Exception as exc:
                session.rollback()
                block_title = block.title if block else None
                print(
                    "[stage-a] ERROR "
                    f"para_id={paragraph.para_id} block_id={paragraph.block_id} block_title={block_title!r}: {exc}"
                )
                raise
            prev_para_id = paragraph.para_id
            prev_sent_texts = target_sentences
        if pending_commits:
            session.commit()
        print("[stage-a] done")

def _prefetch_stage_a_processed_para_ids(session, paragraphs: list[Paragraph]) -> set[uuid.UUID]:
    """
    Idempotent skipping:
    - Treat a paragraph as processed only if BOTH A1 and A3 succeeded for the current prompt versions.
    """
    para_ids = {p.para_id for p in paragraphs}
    if not para_ids:
        return set()

    runs = session.scalars(
        select(ExtractionRun).where(
            ExtractionRun.status == "succeeded",
            ExtractionRun.prompt_version.in_([STAGE_A13_PROMPT_VERSION, STAGE_A1_PROMPT_VERSION, STAGE_A3_PROMPT_VERSION]),
            ExtractionRun.prompt_name.in_([STAGE_A1_PROMPT_NAME, STAGE_A3_PROMPT_NAME]),
        )
    ).all()

    a1_done: set[uuid.UUID] = set()
    a3_done: set[uuid.UUID] = set()

    for run in runs:
        refs = run.input_refs or {}
        para_id_str = refs.get("para_id")
        if not isinstance(para_id_str, str):
            continue
        try:
            pid = uuid.UUID(para_id_str)
        except Exception:
            continue
        if pid not in para_ids:
            continue

        if run.prompt_name == STAGE_A1_PROMPT_NAME and run.prompt_version == STAGE_A1_PROMPT_VERSION:
            a1_done.add(pid)
        elif run.prompt_name == STAGE_A3_PROMPT_NAME and run.prompt_version == STAGE_A3_PROMPT_VERSION:
            a3_done.add(pid)

    return a1_done.intersection(a3_done)


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _call_a1(
    *,
    session,
    llm: LLMClient,
    schemas: Schemas,
    ctx,
    spans: list[SentenceSpan],
    paragraph: Paragraph,
    effective_author_id: uuid.UUID,
) -> None:
    prompt = render_a1_prompt(context_only=ctx.context_only_sentences, target=ctx.target_sentences)
    resp = llm.complete_json(prompt=prompt, schema=schemas.a1)
    if resp.json is None:
        raise ValidationError(f"A1 response was not valid JSON. raw={resp.raw_text[:500]!r}")
    _normalize_a1_output_in_place(resp.json)
    validate_json(resp.json, schemas.a1)

    run = _create_extraction_run(
        session=session,
        model_name=resp.model_name,
        prompt_name="task_a1_concept_mentions",
        prompt_version="v1",
        input_refs={"para_id": str(paragraph.para_id)},
        output_obj=resp.json,
        usage={"prompt_tokens": resp.prompt_tokens, "completion_tokens": resp.completion_tokens, "cost_usd": resp.cost_usd},
    )

    for mention in resp.json.get("mentions", []):
        sentence_index = mention["sentence_index"]
        if sentence_index < 0 or sentence_index >= len(spans):
            raise ValidationError(f"A1 sentence_index out of range: {sentence_index}")
        span = spans[sentence_index]

        session.add(
            ConceptMention(
                span_id=span.span_id,
                start_char_in_sentence=mention.get("start_char_in_sentence"),
                end_char_in_sentence=mention.get("end_char_in_sentence"),
                surface_form=mention["surface_form"],
                normalized_form=mention.get("normalized_form"),
                is_technical=_coerce_bool_or_none(mention.get("is_technical_term")),
                is_technical_raw=mention.get("is_technical_term_raw"),
                candidate_gloss=mention.get("candidate_gloss"),
                extraction_run_id=run.run_id,
                confidence=mention.get("confidence"),
            )
        )


def _call_a3(
    *,
    session,
    llm: LLMClient,
    schemas: Schemas,
    ctx,
    spans: list[SentenceSpan],
    paragraph: Paragraph,
    effective_author_id: uuid.UUID,
) -> None:
    prompt = render_a3_prompt(context_only=ctx.context_only_sentences, target=ctx.target_sentences)
    resp = llm.complete_json(prompt=prompt, schema=schemas.a3)
    if resp.json is None:
        raise ValidationError(f"A3 response was not valid JSON. raw={resp.raw_text[:500]!r}")
    _normalize_a3_output_in_place(resp.json)
    validate_json(resp.json, schemas.a3)

    run = _create_extraction_run(
        session=session,
        model_name=resp.model_name,
        prompt_name="task_a3_claims",
        prompt_version="v1",
        input_refs={"para_id": str(paragraph.para_id)},
        output_obj=resp.json,
        usage={"prompt_tokens": resp.prompt_tokens, "completion_tokens": resp.completion_tokens, "cost_usd": resp.cost_usd},
    )

    for claim_obj in resp.json.get("claims", []):
        evidence_indices = claim_obj["evidence_sentence_indices"]
        for idx in evidence_indices:
            if idx < 0 or idx >= len(spans):
                raise ValidationError(f"A3 evidence_sentence_indices out of range: {idx}")

        group = _create_span_group(session=session, run_id=run.run_id, paragraph=paragraph, spans=spans, indices=evidence_indices)

        claim = Claim(
            claim_text_canonical=claim_obj["claim_text_canonical"],
            claim_type=_map_claim_type(claim_obj.get("claim_type")),
            claim_type_raw=claim_obj.get("claim_type_raw"),
            polarity=_map_polarity(claim_obj.get("polarity")),
            polarity_raw=claim_obj.get("polarity_raw"),
            modality=_map_modality(claim_obj.get("modality")),
            modality_raw=claim_obj.get("modality_raw"),
            scope=claim_obj.get("scope"),
            dialectical_status=_map_dialectical_status(claim_obj.get("dialectical_status")),
            dialectical_status_raw=claim_obj.get("dialectical_status_raw"),
            created_run_id=run.run_id,
            confidence=claim_obj.get("confidence"),
            attribution=_map_attribution(claim_obj.get("attribution")),
            attribution_raw=claim_obj.get("attribution_raw"),
            effective_author_id=effective_author_id,
            citation_locator=claim_obj.get("citation_marker"),
        )
        session.add(claim)
        session.flush()

        session.add(
            ClaimEvidence(
                claim_id=claim.claim_id,
                group_id=group.group_id,
                evidence_role="direct_quote",
                extraction_run_id=run.run_id,
                confidence=claim_obj.get("confidence"),
            )
        )


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


def _create_span_group(
    *,
    session,
    run_id: uuid.UUID,
    paragraph: Paragraph,
    spans: list[SentenceSpan],
    indices: list[int],
) -> SpanGroup:
    span_ids = [str(spans[i].span_id) for i in indices]
    group_hash = sha256(("|".join(span_ids)).encode("utf-8")).hexdigest()
    group = SpanGroup(
        edition_id=paragraph.edition_id,
        para_id=paragraph.para_id,
        group_hash=group_hash,
        created_run_id=run_id,
    )
    session.add(group)
    session.flush()
    for order_index, i in enumerate(indices):
        session.add(SpanGroupSpan(group_id=group.group_id, span_id=spans[i].span_id, order_index=order_index))
    return group


def _map_claim_type(value: str | None) -> ClaimType | None:
    if value is None:
        return None
    mapping = {
        "definition": ClaimType.definition,
        "thesis": ClaimType.thesis,
        "empirical": ClaimType.empirical,
        "normative": ClaimType.normative,
        "methodological": ClaimType.methodological,
        "objection": ClaimType.objection,
        "reply": ClaimType.reply,
    }
    if value not in mapping:
        return None
    return mapping[value]


def _map_polarity(value: str | None) -> Polarity | None:
    mapping = {"assert": Polarity.assert_, "deny": Polarity.deny, "conditional": Polarity.conditional}
    if value is None:
        return None
    if value not in mapping:
        return None
    return mapping[value]


def _map_modality(value: str | None) -> Modality | None:
    if value is None:
        return None
    mapping = {
        "is": Modality.is_,
        "will": Modality.will,
        "would": Modality.would,
        "can": Modality.can,
        "could": Modality.could,
        "cannot": Modality.cannot,
        "must": Modality.must,
        "should": Modality.should,
        "ought": Modality.ought,
        "may": Modality.may,
        "appears_as": Modality.appears_as,
        "becomes": Modality.becomes,
        "in_essence_is": Modality.in_essence_is,
    }
    if value not in mapping:
        raise ValidationError(f"Unknown modality: {value}")
    return mapping[value]


_ALLOWED_MODALITIES = {
    "is",
    "will",
    "would",
    "can",
    "could",
    "cannot",
    "must",
    "should",
    "ought",
    "may",
    "appears_as",
    "becomes",
    "in_essence_is",
}

_ALLOWED_CLAIM_TYPES = {
    "definition",
    "thesis",
    "empirical",
    "normative",
    "methodological",
    "objection",
    "reply",
}

_ALLOWED_POLARITIES = {"assert", "deny", "conditional"}
_ALLOWED_DIALECTICAL_STATUS = {"none", "tension_pair", "appearance_essence", "developmental"}
_ALLOWED_ATTRIBUTIONS = {"self", "citation", "interlocutor"}


def _normalize_a3_output_in_place(output: dict[str, Any]) -> None:
    """
    Keep the external JSON schema strict while being robust to common model noise.

    Strategy:
    - Coerce tokens to the strict enums (lower/strip).
    - Preserve unexpected model values in `*_raw` fields.
    - Drop claims that cannot meet hard invariants (evidence_sentence_indices non-empty, claim_text present).
    """
    claims = output.get("claims")
    if claims is None:
        output["claims"] = []
        return
    if not isinstance(claims, list):
        output["claims"] = []
        return

    normalized_claims: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue

        claim_text = claim.get("claim_text_canonical")
        if not isinstance(claim_text, str) or not claim_text.strip():
            continue

        evidence = claim.get("evidence_sentence_indices")
        evidence_indices: list[int] = []
        if isinstance(evidence, list):
            for item in evidence:
                if isinstance(item, int):
                    evidence_indices.append(item)
                elif isinstance(item, str) and item.strip().isdigit():
                    evidence_indices.append(int(item.strip()))
        if not evidence_indices:
            continue

        # Do not force canonical categories; keep unknowns as *_raw and store canonical fields as null.
        out: dict[str, Any] = {
            "claim_text_canonical": claim_text.strip(),
            "claim_type": None,
            "polarity": None,
            "modality": None,
            "dialectical_status": None,
            "scope": None,
            "attribution": None,
            "evidence_sentence_indices": evidence_indices,
            "about_terms": [],
            "confidence": None,
        }

        # claim_type
        claim_type = _norm_token(claim.get("claim_type"))
        if claim_type is None:
            out["claim_type_raw"] = claim.get("claim_type")
        elif claim_type in _ALLOWED_CLAIM_TYPES:
            out["claim_type"] = claim_type
        else:
            out["claim_type_raw"] = claim.get("claim_type")
            out["claim_type"] = None

        # polarity
        polarity = _norm_token(claim.get("polarity"))
        if polarity is None:
            out["polarity_raw"] = claim.get("polarity")
        elif polarity in _ALLOWED_POLARITIES:
            out["polarity"] = polarity
        else:
            out["polarity_raw"] = claim.get("polarity")
            out["polarity"] = None

        # dialectical_status
        ds = _norm_token(claim.get("dialectical_status"))
        if ds is None:
            out["dialectical_status_raw"] = claim.get("dialectical_status")
        elif ds in _ALLOWED_DIALECTICAL_STATUS:
            out["dialectical_status"] = ds
        else:
            out["dialectical_status_raw"] = claim.get("dialectical_status")
            out["dialectical_status"] = None

        # attribution
        attribution = _norm_token(claim.get("attribution"))
        if attribution is None:
            out["attribution_raw"] = claim.get("attribution")
        elif attribution in _ALLOWED_ATTRIBUTIONS:
            out["attribution"] = attribution
        else:
            out["attribution_raw"] = claim.get("attribution")
            out["attribution"] = None

        # modality
        modality = claim.get("modality")
        if isinstance(modality, str):
            modality_norm = _norm_token(modality)
            if modality_norm is not None and modality_norm in _ALLOWED_MODALITIES:
                out["modality"] = modality_norm
            elif modality_norm is not None:
                out["modality_raw"] = modality

        # scope
        scope = claim.get("scope")
        if isinstance(scope, dict):
            out["scope"] = scope

        # about_terms
        about_terms = claim.get("about_terms")
        if isinstance(about_terms, list):
            out["about_terms"] = [t for t in about_terms if isinstance(t, str)]

        # citation marker / attributed_to pass-through (optional in schema)
        if isinstance(claim.get("citation_marker"), str):
            out["citation_marker"] = claim.get("citation_marker")
        attributed_to = claim.get("attributed_to")
        if isinstance(attributed_to, dict):
            out["attributed_to"] = {
                "author_name": attributed_to.get("author_name") if isinstance(attributed_to.get("author_name"), str) else None,
                "work_hint": attributed_to.get("work_hint") if isinstance(attributed_to.get("work_hint"), str) else None,
            }

        # confidence
        out["confidence"] = _coerce_confidence_or_none(claim.get("confidence"))

        normalized_claims.append(out)

    output["claims"] = normalized_claims


def _normalize_a1_output_in_place(output: dict[str, Any]) -> None:
    mentions = output.get("mentions")
    if mentions is None:
        output["mentions"] = []
        return
    if not isinstance(mentions, list):
        output["mentions"] = []
        return

    normalized: list[dict[str, Any]] = []
    for mention in mentions:
        if not isinstance(mention, dict):
            continue
        surface = mention.get("surface_form")
        if not isinstance(surface, str) or not surface.strip():
            continue

        sentence_index = mention.get("sentence_index")
        if isinstance(sentence_index, str) and sentence_index.strip().isdigit():
            sentence_index = int(sentence_index.strip())
        if not isinstance(sentence_index, int):
            continue

        raw_value = mention.get("is_technical_term")
        normalized_bool = _coerce_bool_or_none(raw_value)
        item: dict[str, Any] = {
            "surface_form": surface,
            "sentence_index": sentence_index,
            "is_technical_term": normalized_bool,
            "normalized_form": mention.get("normalized_form")
            if isinstance(mention.get("normalized_form"), str)
            else None,
            "candidate_gloss": mention.get("candidate_gloss")
            if isinstance(mention.get("candidate_gloss"), str)
            else None,
            "start_char_in_sentence": _coerce_int_or_none(mention.get("start_char_in_sentence")),
            "end_char_in_sentence": _coerce_int_or_none(mention.get("end_char_in_sentence")),
            "confidence": _coerce_confidence_or_none(mention.get("confidence")),
        }
        if normalized_bool is None and raw_value is not None:
            item["is_technical_term_raw"] = raw_value
        normalized.append(item)

    output["mentions"] = normalized


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "t", "yes", "y", "1"}:
            return True
        if v in {"false", "f", "no", "n", "0"}:
            return False
    return False


def _coerce_bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "t", "yes", "y", "1"}:
            return True
        if v in {"false", "f", "no", "n", "0"}:
            return False
    return None


def _coerce_int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        v = value.strip()
        if v.isdigit():
            return int(v)
    return None


def _coerce_confidence_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        try:
            f = float(value.strip())
            return max(0.0, min(1.0, float(f)))
        except Exception:
            return None
    return None


def _norm_token(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if not v:
        return None
    return v


def _map_dialectical_status(value: str | None) -> DialecticalStatus | None:
    if value is None:
        return None
    mapping = {
        "none": DialecticalStatus.none,
        "tension_pair": DialecticalStatus.tension_pair,
        "appearance_essence": DialecticalStatus.appearance_essence,
        "developmental": DialecticalStatus.developmental,
    }
    if value not in mapping:
        return None
    return mapping[value]


def _map_attribution(value: str | None) -> ClaimAttribution | None:
    if value is None:
        return None
    mapping = {"self": ClaimAttribution.self_, "citation": ClaimAttribution.citation, "interlocutor": ClaimAttribution.interlocutor}
    if value not in mapping:
        return None
    return mapping[value]
