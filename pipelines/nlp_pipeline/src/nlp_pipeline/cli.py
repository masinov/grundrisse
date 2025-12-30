from __future__ import annotations

import json
import uuid
from importlib.resources import files

import typer
from sqlalchemy import func, select

from grundrisse_contracts import schemas as contracts_schemas
from grundrisse_core.db.models import (
    Claim,
    ClaimEvidence,
    ConceptMention,
    ExtractionRun,
    Paragraph,
    SentenceSpan,
    SpanGroup,
    SpanGroupSpan,
    TextBlock,
)
from grundrisse_core.db.session import SessionLocal
from nlp_pipeline.llm.zai_glm import ZaiGlmClient
from nlp_pipeline.settings import settings
from nlp_pipeline.stage_a.run import Schemas, run_stage_a_for_edition

app = typer.Typer(help="NLP pipeline (Stage A/B, canonicalization, linking).")


@app.command("stage-a")
def stage_a(
    edition_id: str,
    *,
    progress_every: int = typer.Option(10, help="Print progress every N paragraphs."),
    commit_every: int = typer.Option(5, help="Commit DB transaction every N paragraphs."),
) -> None:
    if not settings.zai_api_key:
        raise typer.BadParameter(
            "Missing GRUNDRISSE_ZAI_API_KEY (Bearer token for https://api.z.ai/api/paas/v4/chat/completions)."
        )
    edition_uuid = uuid.UUID(edition_id)

    schema_dir = files(contracts_schemas)
    a1 = json.loads((schema_dir / "task_a1_concept_mentions.json").read_text(encoding="utf-8"))
    a3 = json.loads((schema_dir / "task_a3_claims.json").read_text(encoding="utf-8"))
    schemas = Schemas(a1=a1, a3=a3)

    with ZaiGlmClient(api_key=settings.zai_api_key, base_url=settings.zai_base_url, model=settings.zai_model) as llm:
        run_stage_a_for_edition(
            edition_id=edition_uuid,
            llm=llm,
            schemas=schemas,
            progress_every=progress_every,
            commit_every=commit_every,
        )


@app.command("stage-b")
def stage_b(work_id: str) -> None:
    raise NotImplementedError("stage-b is not implemented yet (mention clustering + concept canonicalization).")


@app.command("inspect-edition")
def inspect_edition(
    edition_id: str,
    *,
    sample_claims: int = typer.Option(10, help="Print N sample claims with evidence."),
) -> None:
    """
    Quick sanity inspection of what Stage A wrote for a given edition.
    """
    edition_uuid = uuid.UUID(edition_id)
    with SessionLocal() as session:
        paragraphs = session.scalar(
            select(func.count()).select_from(Paragraph).where(Paragraph.edition_id == edition_uuid)
        ) or 0
        spans = session.scalar(
            select(func.count()).select_from(SentenceSpan).where(SentenceSpan.edition_id == edition_uuid)
        ) or 0
        mentions = session.scalar(
            select(func.count())
            .select_from(ConceptMention)
            .join(SentenceSpan, SentenceSpan.span_id == ConceptMention.span_id)
            .where(SentenceSpan.edition_id == edition_uuid)
        ) or 0
        claim_links = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .where(Paragraph.edition_id == edition_uuid)
        ) or 0

        runs = session.execute(
            select(ExtractionRun.prompt_name, ExtractionRun.prompt_version, func.count())
            .where(ExtractionRun.status == "succeeded")
            .group_by(ExtractionRun.prompt_name, ExtractionRun.prompt_version)
            .order_by(func.count().desc())
        ).all()

        print(f"[inspect] edition_id={edition_uuid}")
        print(f"[inspect] paragraphs={paragraphs} sentence_spans={spans}")
        print(f"[inspect] concept_mentions={mentions} claim_evidence_links={claim_links}")
        if runs:
            print("[inspect] extraction_runs (succeeded):")
            for prompt_name, prompt_version, count in runs[:15]:
                print(f"- {prompt_name}@{prompt_version}: {count}")

        if sample_claims <= 0:
            return

        sample = session.execute(
            select(
                Claim.claim_id,
                Claim.claim_text_canonical,
                Claim.claim_type,
                Claim.polarity,
                Claim.modality,
                Claim.dialectical_status,
                Claim.attribution,
                ClaimEvidence.group_id,
                Paragraph.para_id,
                Paragraph.block_id,
            )
            .select_from(ClaimEvidence)
            .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .where(Paragraph.edition_id == edition_uuid)
            .limit(sample_claims)
        ).all()

        print("[inspect] sample_claims:")
        for (
            claim_id,
            claim_text,
            claim_type,
            polarity,
            modality,
            dialectical_status,
            attribution,
            group_id,
            para_id,
            block_id,
        ) in sample:
            block = session.get(TextBlock, block_id)
            block_title = block.title if block else None
            print(f"- claim_id={claim_id} para_id={para_id} block_title={block_title!r}")
            print(
                f"  type={claim_type} polarity={polarity} modality={modality} "
                f"dialectical={dialectical_status} attribution={attribution}"
            )
            print(f"  claim={claim_text.strip()[:240]!r}")

            ev_spans = session.execute(
                select(SentenceSpan.sent_index, SentenceSpan.text)
                .select_from(SpanGroupSpan)
                .join(SentenceSpan, SentenceSpan.span_id == SpanGroupSpan.span_id)
                .where(SpanGroupSpan.group_id == group_id)
                .order_by(SpanGroupSpan.order_index)
            ).all()
            if ev_spans:
                print("  evidence:")
                for sent_index, text in ev_spans:
                    print(f"   - [{sent_index}] {text}")


@app.command("modality-stats")
def modality_stats(edition_id: str) -> None:
    """
    Report unknown/normalized claim modalities for an edition.

    Counts claims where `Claim.modality` is NULL but `Claim.modality_raw` is present.
    """
    edition_uuid = uuid.UUID(edition_id)
    with SessionLocal() as session:
        edition_claims = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .where(Paragraph.edition_id == edition_uuid)
        ) or 0

        unknown = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
            .where(Paragraph.edition_id == edition_uuid)
            .where(Claim.modality.is_(None))
            .where(Claim.modality_raw.is_not(None))
        ) or 0

        rows = session.execute(
            select(Claim.modality_raw, func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
            .where(Paragraph.edition_id == edition_uuid)
            .where(Claim.modality.is_(None))
            .where(Claim.modality_raw.is_not(None))
            .group_by(Claim.modality_raw)
            .order_by(func.count().desc())
            .limit(50)
        ).all()

    print(f"[modality-stats] edition_id={edition_uuid}")
    print(f"[modality-stats] claims_in_edition={edition_claims}")
    print(f"[modality-stats] modality_unknown_count={unknown}")
    if rows:
        print("[modality-stats] raw_modality_top:")
        for raw, count in rows:
            print(f"- {raw!r}: {count}")


@app.command("technicality-stats")
def technicality_stats(edition_id: str) -> None:
    """
    Report unknown/soft technicality judgments for mentions in an edition.

    Counts mentions where `ConceptMention.is_technical` is NULL but `ConceptMention.is_technical_raw` is present.
    """
    edition_uuid = uuid.UUID(edition_id)
    with SessionLocal() as session:
        total = session.scalar(
            select(func.count())
            .select_from(ConceptMention)
            .join(SentenceSpan, SentenceSpan.span_id == ConceptMention.span_id)
            .where(SentenceSpan.edition_id == edition_uuid)
        ) or 0

        unknown = session.scalar(
            select(func.count())
            .select_from(ConceptMention)
            .join(SentenceSpan, SentenceSpan.span_id == ConceptMention.span_id)
            .where(SentenceSpan.edition_id == edition_uuid)
            .where(ConceptMention.is_technical.is_(None))
            .where(ConceptMention.is_technical_raw.is_not(None))
        ) or 0

        rows = session.execute(
            select(ConceptMention.is_technical_raw, func.count())
            .select_from(ConceptMention)
            .join(SentenceSpan, SentenceSpan.span_id == ConceptMention.span_id)
            .where(SentenceSpan.edition_id == edition_uuid)
            .where(ConceptMention.is_technical.is_(None))
            .where(ConceptMention.is_technical_raw.is_not(None))
            .group_by(ConceptMention.is_technical_raw)
            .order_by(func.count().desc())
            .limit(50)
        ).all()

    print(f"[technicality-stats] edition_id={edition_uuid}")
    print(f"[technicality-stats] mentions_in_edition={total}")
    print(f"[technicality-stats] technicality_unknown_count={unknown}")
    if rows:
        print("[technicality-stats] raw_is_technical_top:")
        for raw, count in rows:
            print(f"- {raw!r}: {count}")


@app.command("claim-type-stats")
def claim_type_stats(edition_id: str) -> None:
    """
    Report unknown/normalized claim types for an edition.

    Counts claims where `Claim.claim_type_raw` is present (meaning the model produced a non-enum claim_type
    and it was coerced before validation/persist).
    """
    edition_uuid = uuid.UUID(edition_id)
    with SessionLocal() as session:
        total = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .where(Paragraph.edition_id == edition_uuid)
        ) or 0

        unknown = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
            .where(Paragraph.edition_id == edition_uuid)
            .where(Claim.claim_type_raw.is_not(None))
        ) or 0

        rows = session.execute(
            select(Claim.claim_type_raw, func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
            .where(Paragraph.edition_id == edition_uuid)
            .where(Claim.claim_type_raw.is_not(None))
            .group_by(Claim.claim_type_raw)
            .order_by(func.count().desc())
            .limit(50)
        ).all()

    print(f"[claim-type-stats] edition_id={edition_uuid}")
    print(f"[claim-type-stats] claims_in_edition={total}")
    print(f"[claim-type-stats] claim_type_unknown_count={unknown}")
    if rows:
        print("[claim-type-stats] raw_claim_types_top:")
        for raw, count in rows:
            print(f"- {raw!r}: {count}")


@app.command("polarity-stats")
def polarity_stats(edition_id: str) -> None:
    """
    Report unknown/normalized polarities for an edition.

    Counts claims where `Claim.polarity_raw` is present (meaning the model produced a non-enum polarity
    and it was coerced before validation/persist).
    """
    edition_uuid = uuid.UUID(edition_id)
    with SessionLocal() as session:
        total = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .where(Paragraph.edition_id == edition_uuid)
        ) or 0

        unknown = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
            .where(Paragraph.edition_id == edition_uuid)
            .where(Claim.polarity_raw.is_not(None))
        ) or 0

        rows = session.execute(
            select(Claim.polarity_raw, func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
            .where(Paragraph.edition_id == edition_uuid)
            .where(Claim.polarity_raw.is_not(None))
            .group_by(Claim.polarity_raw)
            .order_by(func.count().desc())
            .limit(50)
        ).all()

    print(f"[polarity-stats] edition_id={edition_uuid}")
    print(f"[polarity-stats] claims_in_edition={total}")
    print(f"[polarity-stats] polarity_unknown_count={unknown}")
    if rows:
        print("[polarity-stats] raw_polarities_top:")
        for raw, count in rows:
            print(f"- {raw!r}: {count}")


@app.command("dialectical-stats")
def dialectical_stats(edition_id: str) -> None:
    """
    Report unknown/normalized dialectical_status values for an edition.

    Counts claims where `Claim.dialectical_status_raw` is present (meaning the model produced a non-enum
    value and it was coerced before validation/persist).
    """
    edition_uuid = uuid.UUID(edition_id)
    with SessionLocal() as session:
        total = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .where(Paragraph.edition_id == edition_uuid)
        ) or 0

        unknown = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
            .where(Paragraph.edition_id == edition_uuid)
            .where(Claim.dialectical_status_raw.is_not(None))
        ) or 0

        rows = session.execute(
            select(Claim.dialectical_status_raw, func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
            .where(Paragraph.edition_id == edition_uuid)
            .where(Claim.dialectical_status_raw.is_not(None))
            .group_by(Claim.dialectical_status_raw)
            .order_by(func.count().desc())
            .limit(50)
        ).all()

    print(f"[dialectical-stats] edition_id={edition_uuid}")
    print(f"[dialectical-stats] claims_in_edition={total}")
    print(f"[dialectical-stats] dialectical_unknown_count={unknown}")
    if rows:
        print("[dialectical-stats] raw_dialectical_status_top:")
        for raw, count in rows:
            print(f"- {raw!r}: {count}")


@app.command("attribution-stats")
def attribution_stats(edition_id: str) -> None:
    """
    Report unknown/normalized attributions for an edition.

    Counts claims where `Claim.attribution_raw` is present (meaning the model produced a non-enum value
    and it was coerced before validation/persist).
    """
    edition_uuid = uuid.UUID(edition_id)
    with SessionLocal() as session:
        total = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .where(Paragraph.edition_id == edition_uuid)
        ) or 0

        unknown = session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
            .where(Paragraph.edition_id == edition_uuid)
            .where(Claim.attribution_raw.is_not(None))
        ) or 0

        rows = session.execute(
            select(Claim.attribution_raw, func.count())
            .select_from(ClaimEvidence)
            .join(SpanGroup, SpanGroup.group_id == ClaimEvidence.group_id)
            .join(Paragraph, Paragraph.para_id == SpanGroup.para_id)
            .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
            .where(Paragraph.edition_id == edition_uuid)
            .where(Claim.attribution_raw.is_not(None))
            .group_by(Claim.attribution_raw)
            .order_by(func.count().desc())
            .limit(50)
        ).all()

    print(f"[attribution-stats] edition_id={edition_uuid}")
    print(f"[attribution-stats] claims_in_edition={total}")
    print(f"[attribution-stats] attribution_unknown_count={unknown}")
    if rows:
        print("[attribution-stats] raw_attributions_top:")
        for raw, count in rows:
            print(f"- {raw!r}: {count}")
