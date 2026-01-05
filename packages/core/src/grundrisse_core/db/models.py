from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from grundrisse_core.db.base import Base
from grundrisse_core.db.enums import (
    AlignmentType,
    AuthorRole,
    BlockSubtype,
    ClaimAttribution,
    ClaimLinkType,
    ClaimType,
    DialecticalStatus,
    Modality,
    Polarity,
    TextBlockType,
    WorkType,
)


class Author(Base):
    __tablename__ = "author"

    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name_canonical: Mapped[str] = mapped_column(String(512), nullable=False)
    name_display: Mapped[str] = mapped_column(String(512), nullable=False)
    name_sort: Mapped[str] = mapped_column(String(512), nullable=False)
    name_variants: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    death_year: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AuthorAlias(Base):
    __tablename__ = "author_aliases"

    alias_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("author.author_id", ondelete="CASCADE"))
    name_variant: Mapped[str] = mapped_column(String(512), nullable=False)
    variant_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="now()")

    author: Mapped[Author] = relationship()


class Work(Base):
    __tablename__ = "work"

    work_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("author.author_id"))
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Display/canonical title for UI/search; does NOT participate in deterministic work_id generation.
    title_canonical: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    work_type: Mapped[WorkType] = mapped_column(
        Enum(WorkType, native_enum=False), nullable=False, default=WorkType.other
    )
    composition_date: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    publication_date: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    original_language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_urls: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)

    author: Mapped[Author] = relationship()


class IngestRun(Base):
    __tablename__ = "ingest_run"

    ingest_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    git_commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    raw_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    raw_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)


class Edition(Base):
    __tablename__ = "edition"

    edition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    work_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work.work_id"))
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    translator_editor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    # Source-specific metadata extracted from the ingested page(s), e.g. marxists.org header fields.
    source_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ingest_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ingest_run.ingest_run_id"))

    work: Mapped[Work] = relationship()
    ingest_run: Mapped[IngestRun] = relationship()


class TextBlock(Base):
    __tablename__ = "text_block"

    block_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    edition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("edition.edition_id"))
    parent_block_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("text_block.block_id"), nullable=True
    )
    block_type: Mapped[TextBlockType] = mapped_column(Enum(TextBlockType, native_enum=False), nullable=False)
    block_subtype: Mapped[BlockSubtype | None] = mapped_column(
        Enum(BlockSubtype, native_enum=False), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    path: Mapped[str | None] = mapped_column(String(128), nullable=True)

    author_id_override: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("author.author_id"), nullable=True
    )
    author_role: Mapped[AuthorRole | None] = mapped_column(Enum(AuthorRole, native_enum=False), nullable=True)

    edition: Mapped[Edition] = relationship()
    parent: Mapped["TextBlock | None"] = relationship(remote_side="TextBlock.block_id")
    author_override: Mapped[Author | None] = relationship()

    __table_args__ = (Index("ix_text_block_edition_order", "edition_id", "order_index"),)


class Paragraph(Base):
    __tablename__ = "paragraph"

    para_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    edition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("edition.edition_id"))
    block_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("text_block.block_id"))
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    para_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    text_normalized: Mapped[str] = mapped_column(Text, nullable=False)

    block: Mapped[TextBlock] = relationship()
    edition: Mapped[Edition] = relationship()

    __table_args__ = (Index("ix_paragraph_block_order", "block_id", "order_index"),)


class SentenceSpan(Base):
    __tablename__ = "sentence_span"

    span_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    edition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("edition.edition_id"))
    block_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("text_block.block_id"))
    para_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("paragraph.para_id"))

    para_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    prev_span_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sentence_span.span_id"), nullable=True
    )
    next_span_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sentence_span.span_id"), nullable=True
    )

    paragraph: Mapped[Paragraph] = relationship()
    block: Mapped[TextBlock] = relationship()
    edition: Mapped[Edition] = relationship()

    __table_args__ = (
        UniqueConstraint("para_id", "sent_index", name="uq_sentence_span_para_sent"),
        Index("ix_sentence_span_edition_para", "edition_id", "para_id"),
    )


class SpanGroup(Base):
    __tablename__ = "span_group"

    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    edition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("edition.edition_id"))
    para_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("paragraph.para_id"))
    group_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_run.run_id"))

    edition: Mapped[Edition] = relationship()
    paragraph: Mapped[Paragraph | None] = relationship()


class SpanGroupSpan(Base):
    __tablename__ = "span_group_span"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("span_group.group_id"), primary_key=True
    )
    span_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sentence_span.span_id"), primary_key=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_span_group_span_group_order", "group_id", "order_index"),)


class ExtractionRun(Base):
    __tablename__ = "extraction_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    git_commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    input_refs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)


class Concept(Base):
    __tablename__ = "concept"

    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label_canonical: Mapped[str] = mapped_column(String(512), nullable=False)
    label_short: Mapped[str | None] = mapped_column(String(256), nullable=True)
    original_term_vernacular: Mapped[str | None] = mapped_column(String(256), nullable=True)
    aliases: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    gloss: Mapped[str] = mapped_column(Text, nullable=False)
    sense_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_concept_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    parent_concept_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    temporal_scope: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    created_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_run.run_id"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (Index("ix_concept_label", "label_canonical"),)


class ConceptMention(Base):
    __tablename__ = "concept_mention"

    mention_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    span_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sentence_span.span_id"))
    start_char_in_sentence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char_in_sentence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    surface_form: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_form: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_technical: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    is_technical_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_gloss: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_run.run_id"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    concept_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("concept.concept_id"))

    __table_args__ = (Index("ix_concept_mention_span", "span_id"),)


class ConceptEvidence(Base):
    __tablename__ = "concept_evidence"

    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("concept.concept_id"), primary_key=True)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("span_group.group_id"), primary_key=True)
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_run.run_id"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class Claim(Base):
    __tablename__ = "claim"

    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_text_canonical: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[ClaimType | None] = mapped_column(
        Enum(ClaimType, native_enum=False), nullable=True
    )
    claim_type_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    polarity: Mapped[Polarity | None] = mapped_column(
        Enum(Polarity, native_enum=False), nullable=True, default=None
    )
    polarity_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    modality: Mapped[Modality | None] = mapped_column(Enum(Modality, native_enum=False), nullable=True)
    modality_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    dialectical_status: Mapped[DialecticalStatus | None] = mapped_column(
        Enum(DialecticalStatus, native_enum=False), nullable=True, default=None
    )
    dialectical_status_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialectical_pair_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    created_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_run.run_id"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    attribution: Mapped[ClaimAttribution | None] = mapped_column(
        Enum(ClaimAttribution, native_enum=False), nullable=True, default=None
    )
    attribution_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("author.author_id"), nullable=True
    )
    attributed_author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("author.author_id"), nullable=True
    )
    citation_work_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work.work_id"), nullable=True
    )
    citation_locator: Mapped[str | None] = mapped_column(Text, nullable=True)
    citation_quote_span_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("span_group.group_id"), nullable=True
    )

    __table_args__ = (Index("ix_claim_created_run", "created_run_id"),)


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"

    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claim.claim_id"), primary_key=True)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("span_group.group_id"), primary_key=True)
    evidence_role: Mapped[str] = mapped_column(String(32), nullable=False)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_run.run_id"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class ClaimLink(Base):
    __tablename__ = "claim_link"

    link_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id_src: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claim.claim_id"))
    claim_id_dst: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claim.claim_id"))
    link_type: Mapped[ClaimLinkType] = mapped_column(Enum(ClaimLinkType, native_enum=False), nullable=False)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_run.run_id"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    evidence_group_ids_src: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    evidence_group_ids_dst: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (
        Index("ix_claim_link_src", "claim_id_src"),
        Index("ix_claim_link_dst", "claim_id_dst"),
    )


class CitationEdge(Base):
    __tablename__ = "citation_edge"

    citation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claim.claim_id"))
    target_author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("author.author_id"), nullable=True
    )
    target_work_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work.work_id"), nullable=True)
    target_span_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("span_group.group_id"), nullable=True
    )
    citation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_run.run_id"))


class ClaimConceptLink(Base):
    __tablename__ = "claim_concept_link"

    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claim.claim_id"), primary_key=True)
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("concept.concept_id"), primary_key=True)
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class SpanAlignment(Base):
    __tablename__ = "span_alignment"

    alignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work.work_id"))
    edition_id_a: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("edition.edition_id"))
    edition_id_b: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("edition.edition_id"))

    block_id_a: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("text_block.block_id"), nullable=True)
    block_id_b: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("text_block.block_id"), nullable=True)
    para_id_a: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("paragraph.para_id"), nullable=True)
    para_id_b: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("paragraph.para_id"), nullable=True)
    group_id_a: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("span_group.group_id"), nullable=True)
    group_id_b: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("span_group.group_id"), nullable=True)

    alignment_type: Mapped[AlignmentType] = mapped_column(
        Enum(AlignmentType, native_enum=False), nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_run.run_id"))


class CrawlRun(Base):
    __tablename__ = "crawl_run"

    crawl_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    git_commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    crawl_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    urls_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urls_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urls_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UrlCatalogEntry(Base):
    __tablename__ = "url_catalog_entry"

    url_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url_canonical: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    discovered_from_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("crawl_run.crawl_run_id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Link graph fields
    parent_url_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("url_catalog_entry.url_id"), nullable=True
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    child_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Classification fields
    classification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unclassified")
    classification_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    classification_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classification_run.run_id"), nullable=True
    )

    __table_args__ = (
        Index("ix_url_catalog_status", "status"),
        Index("ix_url_catalog_sha256", "content_sha256"),
        Index("ix_url_catalog_depth", "depth"),
        Index("ix_url_catalog_classification_status", "classification_status"),
        Index("ix_url_catalog_parent", "parent_url_id"),
    )


class ClassificationRun(Base):
    __tablename__ = "classification_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("crawl_run.crawl_run_id"))
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    budget_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    urls_classified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urls_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)


class WorkDiscovery(Base):
    __tablename__ = "work_discovery"

    discovery_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("crawl_run.crawl_run_id"))
    root_url: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[str] = mapped_column(String(512), nullable=False)
    work_title: Mapped[str] = mapped_column(String(1024), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    page_urls: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    ingestion_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    edition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("edition.edition_id"), nullable=True
    )

    __table_args__ = (Index("ix_work_discovery_ingestion_status", "ingestion_status"),)


class WorkMetadataRun(Base):
    __tablename__ = "work_metadata_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    git_commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sources: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)

    works_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    works_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    works_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    works_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WorkMetadataEvidence(Base):
    __tablename__ = "work_metadata_evidence"

    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work_metadata_run.run_id"))
    work_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work.work_id"))

    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extracted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_work_metadata_evidence_work", "work_id"),
        Index("ix_work_metadata_evidence_run", "run_id"),
        Index("ix_work_metadata_evidence_source", "source_name"),
    )


class WorkDateFinal(Base):
    """
    Frozen, provenance-backed first-publication date for a Work.

    This is intentionally separate from `work.publication_date` (legacy/heuristic field) so that we can:
    - collect multiple candidates over time in evidence tables
    - finalize once, then never overwrite unless explicitly forced
    """

    __tablename__ = "work_date_final"

    work_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work.work_id"), primary_key=True)

    # Canonical target: first-publication date (what becomes public).
    first_publication_date: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    precision: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Provenance
    final_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_metadata_evidence.evidence_id"), nullable=True
    )
    finalized_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_metadata_run.run_id"), nullable=True
    )
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # finalized | heuristic | unknown | conflict
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="finalized")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_work_date_final_status", "status"),
        Index("ix_work_date_final_method", "method"),
    )


class WorkDateDerivationRun(Base):
    """
    No-network derivation run that produces `work_date_derived` rows from stored evidence:
    - edition.source_metadata (ingested HTML headers)
    - work_metadata_evidence (Wikidata/OpenLibrary/etc.)
    """

    __tablename__ = "work_date_derivation_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    git_commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)

    works_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    works_derived: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    works_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    works_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WorkDateDerived(Base):
    """
    Derived multi-date bundle for a Work, computed deterministically from stored evidence.

    This is the "single source of truth" for UI chronology and for graph ordering.
    """

    __tablename__ = "work_date_derived"

    work_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work.work_id"), primary_key=True)

    # Multi-date bundle (roles + provenance).
    dates: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Selected display date (e.g., first_publication_date, falling back to written_date).
    display_date: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    display_date_field: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    display_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Provenance
    derived_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_date_derivation_run.run_id"), nullable=True
    )
    derived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (Index("ix_work_date_derived_display_year", "display_year"),)


class EditionSourceHeader(Base):
    """
    Normalized view of source-specific per-edition header metadata (e.g., marxists.org "Written/Source/First Published").

    Keep both:
    - raw extracted structures for provenance
    - structured fields for easy querying
    """

    __tablename__ = "edition_source_header"

    edition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("edition.edition_id"), primary_key=True
    )

    source_name: Mapped[str] = mapped_column(String(64), nullable=False, default="marxists")
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    raw_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    raw_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    raw_dates: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    editorial_intro: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Important: use `none_as_null=True` so Python `None` becomes SQL NULL (not JSON `null`),
    # which keeps DB-level nullability meaningful (e.g., `count(col)` reflects "has date").
    written_date: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    first_published_date: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    published_date: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)

    source_citation_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    translated_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcription_markup_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_domain_raw: Mapped[str | None] = mapped_column(Text, nullable=True)

    edition: Mapped[Edition] = relationship()


class AuthorMetadataRun(Base):
    __tablename__ = "author_metadata_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    git_commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sources: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)

    authors_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    authors_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    authors_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    authors_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AuthorMetadataEvidence(Base):
    __tablename__ = "author_metadata_evidence"

    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("author_metadata_run.run_id"))
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("author.author_id"))

    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extracted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_author_metadata_evidence_author", "author_id"),
        Index("ix_author_metadata_evidence_run", "run_id"),
        Index("ix_author_metadata_evidence_source", "source_name"),
    )


def import_models() -> None:
    # Used by Alembic autogenerate. Keep import side effects explicit.
    _ = (
        Author,
        Work,
        IngestRun,
        Edition,
        TextBlock,
        Paragraph,
        SentenceSpan,
        SpanGroup,
        SpanGroupSpan,
        ExtractionRun,
        Concept,
        ConceptMention,
        ConceptEvidence,
        Claim,
        ClaimEvidence,
        ClaimLink,
        CitationEdge,
        ClaimConceptLink,
        SpanAlignment,
        CrawlRun,
        UrlCatalogEntry,
        ClassificationRun,
        WorkDiscovery,
        WorkMetadataRun,
        WorkMetadataEvidence,
        WorkDateFinal,
        WorkDateDerivationRun,
        WorkDateDerived,
        EditionSourceHeader,
        AuthorMetadataRun,
        AuthorMetadataEvidence,
    )
