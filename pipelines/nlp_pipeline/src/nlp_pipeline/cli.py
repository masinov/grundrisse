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
    Concept,
    ConceptMention,
    Edition,
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
from nlp_pipeline.stage_b.run import SchemasB, run_stage_b_for_work

app = typer.Typer(help="NLP pipeline (Stage A/B, canonicalization, linking).")


@app.command("stage-a")
def stage_a(
    edition_id: str,
    *,
    progress_every: int = typer.Option(10, help="Print progress every N paragraphs."),
    commit_every: int = typer.Option(5, help="Commit DB transaction every N paragraphs."),
    include_apparatus: bool = typer.Option(
        False,
        help="Include obvious non-content apparatus blocks (TOC/study guide/navigation/license).",
    ),
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
            include_apparatus=include_apparatus,
        )


@app.command("stage-b")
def stage_b(
    work_id: str,
    *,
    progress_every: int = typer.Option(20, help="Print progress every N clusters."),
    commit_every: int = typer.Option(10, help="Commit DB transaction every N clusters."),
    min_cluster_size: int = typer.Option(2, help="Minimum cluster size to canonicalize."),
    max_cluster_size: int = typer.Option(50, help="Maximum mentions sent to LLM per cluster."),
    include_apparatus: bool = typer.Option(
        False,
        help="Include obvious non-content apparatus blocks (TOC/study guide/navigation/license).",
    ),
) -> None:
    if not settings.zai_api_key:
        raise typer.BadParameter("Missing GRUNDRISSE_ZAI_API_KEY.")
    work_uuid = uuid.UUID(work_id)

    schema_dir = files(contracts_schemas)
    b = json.loads((schema_dir / "task_b_concept_canonicalize.json").read_text(encoding="utf-8"))
    schemas = SchemasB(b=b)

    with ZaiGlmClient(api_key=settings.zai_api_key, base_url=settings.zai_base_url, model=settings.zai_model) as llm:
        run_stage_b_for_work(
            work_id=work_uuid,
            llm=llm,
            schemas=schemas,
            max_cluster_size=max_cluster_size,
            min_cluster_size=min_cluster_size,
            progress_every=progress_every,
            commit_every=commit_every,
            include_apparatus=include_apparatus,
        )


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


@app.command("sample-edition")
def sample_edition(
    edition_id: str,
    *,
    n: int = typer.Option(10, help="Number of random paragraphs to sample."),
    include_no_mentions: int = typer.Option(3, help="Also sample N paragraphs that have no mentions."),
    include_no_claims: int = typer.Option(3, help="Also sample N paragraphs that have no claims."),
    max_mentions: int = typer.Option(20, help="Max mentions printed per paragraph."),
    max_claims: int = typer.Option(5, help="Max claims printed per paragraph."),
) -> None:
    """
    Targeted spot-check sampler for validating Stage A/B outputs.
    Reconstructs paragraph text from sentence spans, prints mentions (with concept label if assigned),
    and prints a few claims with evidence.
    """
    edition_uuid = uuid.UUID(edition_id)
    with SessionLocal() as session:
        ed = session.get(Edition, edition_uuid)
        if ed is None:
            raise typer.BadParameter(f"Edition not found: {edition_uuid}")

        def paragraph_text(para_id: uuid.UUID) -> str:
            spans = session.execute(
                select(SentenceSpan.sent_index, SentenceSpan.text)
                .where(SentenceSpan.para_id == para_id)
                .order_by(SentenceSpan.sent_index)
            ).all()
            return " ".join((t or "").strip() for _, t in spans).strip()

        def print_para(para: Paragraph) -> None:
            block = session.get(TextBlock, para.block_id)
            block_title = block.title if block else None
            print(f"\n[para] para_id={para.para_id} block_title={block_title!r}")
            text = paragraph_text(para.para_id)
            print(f"[para] text={text[:1200]!r}")

            mentions = session.execute(
                select(
                    ConceptMention.mention_id,
                    ConceptMention.surface_form,
                    ConceptMention.normalized_form,
                    ConceptMention.is_technical,
                    ConceptMention.concept_id,
                )
                .join(SentenceSpan, SentenceSpan.span_id == ConceptMention.span_id)
                .where(SentenceSpan.para_id == para.para_id)
                .limit(max_mentions)
            ).all()
            if mentions:
                print("[para] mentions:")
                for mid, surface, norm, is_tech, concept_id in mentions:
                    label = None
                    if concept_id is not None:
                        c = session.get(Concept, concept_id)
                        label = c.label_canonical if c else None
                    print(
                        f" - mention_id={mid} concept={label!r} surface={surface!r} "
                        f"norm={norm!r} technical={is_tech}"
                    )
            else:
                print("[para] mentions: (none)")

            claims = session.execute(
                select(
                    Claim.claim_id,
                    Claim.claim_text_canonical,
                    Claim.claim_type,
                    Claim.polarity,
                    Claim.modality,
                    Claim.dialectical_status,
                    ClaimEvidence.group_id,
                )
                .select_from(SpanGroup)
                .join(ClaimEvidence, ClaimEvidence.group_id == SpanGroup.group_id)
                .join(Claim, Claim.claim_id == ClaimEvidence.claim_id)
                .where(SpanGroup.para_id == para.para_id)
                .limit(max_claims)
            ).all()
            if claims:
                print("[para] claims:")
                for claim_id, claim_text, claim_type, polarity, modality, dialectical_status, group_id in claims:
                    print(
                        f" - claim_id={claim_id} type={claim_type} polarity={polarity} "
                        f"modality={modality} dialectical={dialectical_status}"
                    )
                    print(f"   claim={claim_text.strip()[:400]!r}")
                    ev_spans = session.execute(
                        select(SentenceSpan.sent_index, SentenceSpan.text)
                        .select_from(SpanGroupSpan)
                        .join(SentenceSpan, SentenceSpan.span_id == SpanGroupSpan.span_id)
                        .where(SpanGroupSpan.group_id == group_id)
                        .order_by(SpanGroupSpan.order_index)
                    ).all()
                    for sent_index, span_text in ev_spans:
                        print(f"    - [{sent_index}] {span_text}")
            else:
                print("[para] claims: (none)")

        # Random sample.
        if n > 0:
            paras = session.execute(
                select(Paragraph)
                .where(Paragraph.edition_id == edition_uuid)
                .order_by(func.random())
                .limit(n)
            ).scalars().all()
            print(f"[sample] edition_id={edition_uuid} language={ed.language} url={ed.source_url!r}")
            print(f"[sample] random_paragraphs={len(paras)}")
            for p in paras:
                print_para(p)

        # Paragraphs with spans but no mentions.
        if include_no_mentions > 0:
            paras = session.execute(
                select(Paragraph)
                .where(Paragraph.edition_id == edition_uuid)
                .where(
                    select(func.count())
                    .select_from(SentenceSpan)
                    .where(SentenceSpan.para_id == Paragraph.para_id)
                    .scalar_subquery()
                    > 0
                )
                .where(
                    select(func.count())
                    .select_from(ConceptMention)
                    .join(SentenceSpan, SentenceSpan.span_id == ConceptMention.span_id)
                    .where(SentenceSpan.para_id == Paragraph.para_id)
                    .scalar_subquery()
                    == 0
                )
                .limit(include_no_mentions)
            ).scalars().all()
            print(f"\n[sample] no_mentions_paragraphs={len(paras)}")
            for p in paras:
                print_para(p)

        # Paragraphs with spans but no claims.
        if include_no_claims > 0:
            paras = session.execute(
                select(Paragraph)
                .where(Paragraph.edition_id == edition_uuid)
                .where(
                    select(func.count())
                    .select_from(SentenceSpan)
                    .where(SentenceSpan.para_id == Paragraph.para_id)
                    .scalar_subquery()
                    > 0
                )
                .where(
                    select(func.count())
                    .select_from(SpanGroup)
                    .join(ClaimEvidence, ClaimEvidence.group_id == SpanGroup.group_id)
                    .where(SpanGroup.para_id == Paragraph.para_id)
                    .scalar_subquery()
                    == 0
                )
                .limit(include_no_claims)
            ).scalars().all()
            print(f"\n[sample] no_claims_paragraphs={len(paras)}")
            for p in paras:
                print_para(p)


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
