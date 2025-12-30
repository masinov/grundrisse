"""Initial provenance-first schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2025-12-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "author",
        sa.Column("author_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name_canonical", sa.String(length=512), nullable=False),
        sa.Column("name_variants", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("death_year", sa.Integer(), nullable=True),
    )

    op.create_table(
        "work",
        sa.Column("work_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("author.author_id"), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("work_type", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("composition_date", sa.JSON(), nullable=True),
        sa.Column("publication_date", sa.JSON(), nullable=True),
        sa.Column("original_language", sa.String(length=32), nullable=True),
        sa.Column("source_urls", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )

    op.create_table(
        "ingest_run",
        sa.Column("ingest_run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pipeline_version", sa.String(length=128), nullable=False),
        sa.Column("git_commit_hash", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("raw_object_key", sa.Text(), nullable=False),
        sa.Column("raw_checksum", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="started"),
        sa.Column("error_log", sa.Text(), nullable=True),
    )

    op.create_table(
        "edition",
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("work.work_id"), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("translator_editor", sa.String(length=512), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("ingest_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ingest_run.ingest_run_id"), nullable=False),
    )

    op.create_table(
        "text_block",
        sa.Column("block_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("edition.edition_id"), nullable=False),
        sa.Column("parent_block_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("text_block.block_id"), nullable=True),
        sa.Column("block_type", sa.String(length=32), nullable=False),
        sa.Column("block_subtype", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=1024), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=128), nullable=True),
        sa.Column("author_id_override", postgresql.UUID(as_uuid=True), sa.ForeignKey("author.author_id"), nullable=True),
        sa.Column("author_role", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_text_block_edition_order", "text_block", ["edition_id", "order_index"])

    op.create_table(
        "paragraph",
        sa.Column("para_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("edition.edition_id"), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("text_block.block_id"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=True),
        sa.Column("end_char", sa.Integer(), nullable=True),
        sa.Column("para_hash", sa.String(length=128), nullable=False),
        sa.Column("text_normalized", sa.Text(), nullable=False),
    )
    op.create_index("ix_paragraph_block_order", "paragraph", ["block_id", "order_index"])

    op.create_table(
        "sentence_span",
        sa.Column("span_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("edition.edition_id"), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("text_block.block_id"), nullable=False),
        sa.Column("para_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("paragraph.para_id"), nullable=False),
        sa.Column("para_index", sa.Integer(), nullable=False),
        sa.Column("sent_index", sa.Integer(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=True),
        sa.Column("end_char", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=128), nullable=False),
        sa.Column("prev_span_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sentence_span.span_id"), nullable=True),
        sa.Column("next_span_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sentence_span.span_id"), nullable=True),
        sa.UniqueConstraint("para_id", "sent_index", name="uq_sentence_span_para_sent"),
    )
    op.create_index("ix_sentence_span_edition_para", "sentence_span", ["edition_id", "para_id"])

    op.create_table(
        "extraction_run",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pipeline_version", sa.String(length=128), nullable=False),
        sa.Column("git_commit_hash", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("model_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("prompt_name", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("input_refs", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("output_hash", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="started"),
        sa.Column("error_log", sa.Text(), nullable=True),
    )

    op.create_table(
        "span_group",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("edition.edition_id"), nullable=False),
        sa.Column("para_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("paragraph.para_id"), nullable=True),
        sa.Column("group_hash", sa.String(length=128), nullable=False),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extraction_run.run_id"), nullable=False),
    )

    op.create_table(
        "span_group_span",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("span_group.group_id"), primary_key=True),
        sa.Column("span_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sentence_span.span_id"), primary_key=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
    )
    op.create_index("ix_span_group_span_group_order", "span_group_span", ["group_id", "order_index"])

    op.create_table(
        "concept",
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("label_canonical", sa.String(length=512), nullable=False),
        sa.Column("label_short", sa.String(length=256), nullable=True),
        sa.Column("original_term_vernacular", sa.String(length=256), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("gloss", sa.Text(), nullable=False),
        sa.Column("sense_notes", sa.Text(), nullable=True),
        sa.Column("root_concept_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_concept_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("temporal_scope", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="proposed"),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extraction_run.run_id"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.create_index("ix_concept_label", "concept", ["label_canonical"])

    op.create_table(
        "concept_mention",
        sa.Column("mention_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("span_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sentence_span.span_id"), nullable=False),
        sa.Column("start_char_in_sentence", sa.Integer(), nullable=True),
        sa.Column("end_char_in_sentence", sa.Integer(), nullable=True),
        sa.Column("surface_form", sa.String(length=512), nullable=False),
        sa.Column("normalized_form", sa.String(length=512), nullable=True),
        sa.Column("is_technical", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("candidate_gloss", sa.Text(), nullable=True),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extraction_run.run_id"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("concept.concept_id"), nullable=True),
    )
    op.create_index("ix_concept_mention_span", "concept_mention", ["span_id"])

    op.create_table(
        "concept_evidence",
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("concept.concept_id"), primary_key=True),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("span_group.group_id"), primary_key=True),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extraction_run.run_id"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
    )

    op.create_table(
        "claim",
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_text_canonical", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(length=32), nullable=False),
        sa.Column("polarity", sa.String(length=16), nullable=False, server_default="assert"),
        sa.Column("modality", sa.String(length=32), nullable=True),
        sa.Column("scope", sa.JSON(), nullable=True),
        sa.Column("dialectical_status", sa.String(length=32), nullable=False, server_default="none"),
        sa.Column("dialectical_pair_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="proposed"),
        sa.Column("created_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extraction_run.run_id"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("attribution", sa.String(length=16), nullable=False, server_default="self"),
        sa.Column("effective_author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("author.author_id"), nullable=True),
        sa.Column("attributed_author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("author.author_id"), nullable=True),
        sa.Column("citation_work_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("work.work_id"), nullable=True),
        sa.Column("citation_locator", sa.Text(), nullable=True),
        sa.Column(
            "citation_quote_span_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("span_group.group_id"),
            nullable=True,
        ),
    )
    op.create_index("ix_claim_created_run", "claim", ["created_run_id"])

    op.create_table(
        "claim_evidence",
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claim.claim_id"), primary_key=True),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("span_group.group_id"), primary_key=True),
        sa.Column("evidence_role", sa.String(length=32), nullable=False),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extraction_run.run_id"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
    )

    op.create_table(
        "claim_link",
        sa.Column("link_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id_src", postgresql.UUID(as_uuid=True), sa.ForeignKey("claim.claim_id"), nullable=False),
        sa.Column("claim_id_dst", postgresql.UUID(as_uuid=True), sa.ForeignKey("claim.claim_id"), nullable=False),
        sa.Column("link_type", sa.String(length=64), nullable=False),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extraction_run.run_id"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence_group_ids_src", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("evidence_group_ids_dst", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.create_index("ix_claim_link_src", "claim_link", ["claim_id_src"])
    op.create_index("ix_claim_link_dst", "claim_link", ["claim_id_dst"])

    op.create_table(
        "citation_edge",
        sa.Column("citation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claim.claim_id"), nullable=False),
        sa.Column("target_author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("author.author_id"), nullable=True),
        sa.Column("target_work_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("work.work_id"), nullable=True),
        sa.Column("target_span_group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("span_group.group_id"), nullable=True),
        sa.Column("citation_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extraction_run.run_id"), nullable=False),
    )

    op.create_table(
        "claim_concept_link",
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claim.claim_id"), primary_key=True),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("concept.concept_id"), primary_key=True),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
    )

    op.create_table(
        "span_alignment",
        sa.Column("alignment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("work.work_id"), nullable=False),
        sa.Column("edition_id_a", postgresql.UUID(as_uuid=True), sa.ForeignKey("edition.edition_id"), nullable=False),
        sa.Column("edition_id_b", postgresql.UUID(as_uuid=True), sa.ForeignKey("edition.edition_id"), nullable=False),
        sa.Column("block_id_a", postgresql.UUID(as_uuid=True), sa.ForeignKey("text_block.block_id"), nullable=True),
        sa.Column("block_id_b", postgresql.UUID(as_uuid=True), sa.ForeignKey("text_block.block_id"), nullable=True),
        sa.Column("para_id_a", postgresql.UUID(as_uuid=True), sa.ForeignKey("paragraph.para_id"), nullable=True),
        sa.Column("para_id_b", postgresql.UUID(as_uuid=True), sa.ForeignKey("paragraph.para_id"), nullable=True),
        sa.Column("group_id_a", postgresql.UUID(as_uuid=True), sa.ForeignKey("span_group.group_id"), nullable=True),
        sa.Column("group_id_b", postgresql.UUID(as_uuid=True), sa.ForeignKey("span_group.group_id"), nullable=True),
        sa.Column("alignment_type", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extraction_run.run_id"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("span_alignment")
    op.drop_table("claim_concept_link")
    op.drop_table("citation_edge")
    op.drop_index("ix_claim_link_dst", table_name="claim_link")
    op.drop_index("ix_claim_link_src", table_name="claim_link")
    op.drop_table("claim_link")
    op.drop_table("claim_evidence")
    op.drop_index("ix_claim_created_run", table_name="claim")
    op.drop_table("claim")
    op.drop_table("concept_evidence")
    op.drop_index("ix_concept_mention_span", table_name="concept_mention")
    op.drop_table("concept_mention")
    op.drop_index("ix_concept_label", table_name="concept")
    op.drop_table("concept")
    op.drop_index("ix_span_group_span_group_order", table_name="span_group_span")
    op.drop_table("span_group_span")
    op.drop_table("span_group")
    op.drop_table("extraction_run")
    op.drop_index("ix_sentence_span_edition_para", table_name="sentence_span")
    op.drop_table("sentence_span")
    op.drop_index("ix_paragraph_block_order", table_name="paragraph")
    op.drop_table("paragraph")
    op.drop_index("ix_text_block_edition_order", table_name="text_block")
    op.drop_table("text_block")
    op.drop_table("edition")
    op.drop_table("ingest_run")
    op.drop_table("work")
    op.drop_table("author")

