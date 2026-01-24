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
    ArgumentRelationType,
    AuthorRole,
    BlockSubtype,
    ClaimAttribution,
    ClaimLinkType,
    ClaimType,
    ConflictType,
    DialecticalStatus,
    EntityType,
    IllocutionForce,
    Modality,
    Polarity,
    TextBlockType,
    TransitionHint,
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


# =============================================================================
# Argument Extraction Tables (AIF/IAT Schema)
# =============================================================================


class ArgumentExtractionRun(Base):
    """
    Pipeline tracking for argument extraction runs.

    Separate from ExtractionRun to avoid coupling with Stage A/B NLP pipeline.
    """
    __tablename__ = "argument_extraction_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_version: Mapped[str] = mapped_column(String(128), nullable=False)
    git_commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)

    windows_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    propositions_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relations_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ArgumentLocution(Base):
    """
    L-node in AIF/IAT: An immutable span of text.

    Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §3.2 and Appendix A:
    Every higher-order object MUST reference loc_ids. Locutions constitute
    the audit trail of the system.

    Grounding fields:
    - One of paragraph_id or sentence_span_id must be set
    - section_path preserves DOM structure for navigation
    - is_footnote and footnote_links capture polemical/definitional content
    """
    __tablename__ = "argument_locution"

    loc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    edition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("edition.edition_id"), nullable=False)

    # Text content (verbatim, immutable)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # Character offsets (original text positions)
    start_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Grounding: exactly one of these should be set
    paragraph_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("paragraph.para_id"), nullable=True)
    sentence_span_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sentence_span.span_id"), nullable=True)

    # Structural context (§4.1: DOM-aware ingestion)
    section_path: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)  # List[str]

    # Footnote handling (footnotes are often polemical/definitional)
    is_footnote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    footnote_links: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)  # List of linked loc_ids

    # Provenance
    created_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_extraction_run.run_id"))

    edition: Mapped[Edition] = relationship()
    paragraph: Mapped[Paragraph | None] = relationship()
    sentence_span: Mapped[SentenceSpan | None] = relationship()
    extraction_run: Mapped[ArgumentExtractionRun] = relationship()

    __table_args__ = (
        Index("ix_argument_locution_edition", "edition_id"),
        Index("ix_argument_locution_paragraph", "paragraph_id"),
        Index("ix_argument_locution_sentence_span", "sentence_span_id"),
        Index("ix_argument_locution_footnote", "is_footnote"),
    )


class ArgumentProposition(Base):
    """
    I-node in AIF/IAT: Abstract content separated from the act of uttering it.

    Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §3.4 and Appendix A:
    A proposition may be realized by multiple locutions. It captures
    truth-evaluable content abstracted from one or more locutions.
    """
    __tablename__ = "argument_proposition"

    prop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    edition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("edition.edition_id"), nullable=False)

    # Content representation (self-contained statement of content)
    text_summary: Mapped[str] = mapped_column(Text, nullable=False)

    # Grounding: MUST be grounded to at least one locution
    surface_loc_ids: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)  # List[str] of loc_ids

    # Concept and entity bindings (§4.3, §9.1)
    concept_bindings: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)  # List[ConceptBinding]
    entity_bindings: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)  # List[EntityBinding]

    # Temporal/Dialectical tags (§9.2)
    temporal_scope: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Implicit reconstruction from enthymeme (§5.3)
    is_implicit_reconstruction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Optional canonical label (late-stage only, §8)
    canonical_label: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Confidence and provenance
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_extraction_run.run_id"))

    edition: Mapped[Edition] = relationship()
    extraction_run: Mapped[ArgumentExtractionRun] = relationship()

    __table_args__ = (
        Index("ix_argument_proposition_edition", "edition_id"),
        Index("ix_argument_proposition_created_run", "created_run_id"),
        Index("ix_argument_proposition_canonical", "canonical_label"),
    )


class ArgumentIllocution(Base):
    """
    L→P edge in AIF/IAT: The link between L-Node and I-Node.

    Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §3.5 and Appendix A:
    Captures 'What is done' with the text - the pragmatic action performed
    with a proposition (asserting, denying, attributing, defining, etc.).

    Critical for Marxist texts: attribution and denial are explicitly modeled.
    Irony is treated as a first-class force.
    """
    __tablename__ = "argument_illocution"

    illoc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Source and target
    source_loc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_locution.loc_id"), nullable=False)
    target_prop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_proposition.prop_id"), nullable=False)

    # Illocutionary force (§6.2)
    force: Mapped[IllocutionForce] = mapped_column(
        Enum(IllocutionForce, native_enum=False), nullable=False
    )

    # Attribution (§6.3: implicit opponent handling)
    attributed_to: Mapped[str | None] = mapped_column(Text, nullable=True)  # Person/School (e.g., 'Ricardo', 'The Vulgar Economists')
    is_implicit_opponent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # True if target is abstract/unnamed opponent

    # Confidence and provenance
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_extraction_run.run_id"))

    source_locution: Mapped[ArgumentLocution] = relationship()
    target_proposition: Mapped[ArgumentProposition] = relationship()
    extraction_run: Mapped[ArgumentExtractionRun] = relationship()

    __table_args__ = (
        Index("ix_argument_illocution_source", "source_loc_id"),
        Index("ix_argument_illocution_target", "target_prop_id"),
    )


class ArgumentRelation(Base):
    """
    S-node in AIF/IAT: RA/CA/MA Nodes capturing dialectical motion.

    Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §3.6 and Appendix A:
    Captures support, conflict, and rephrase relations between propositions.
    Evidence is MANDATORY - all relations must cite text spans.

    Supports:
    - RA (inference): premises → conclusion
    - CA (conflict): rebut, undercut, incompatibility
    - MA (rephrase): paraphrase, abstraction, concretization
    """
    __tablename__ = "argument_relation"

    rel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    edition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("edition.edition_id"), nullable=False)

    # Relation type
    relation_type: Mapped[ArgumentRelationType] = mapped_column(
        Enum(ArgumentRelationType, native_enum=False), nullable=False
    )

    # Direction: source_prop_ids is a LIST (multiple premises/attacking claims)
    source_prop_ids: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)  # List[str] of prop_ids (Premises / Attacking Claims)
    target_prop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_proposition.prop_id"), nullable=False)  # Conclusion / Attacked Claim

    # Conflict detail (for conflict relations)
    conflict_detail: Mapped[ConflictType | None] = mapped_column(
        Enum(ConflictType, native_enum=False), nullable=True
    )

    # Evidence is MANDATORY (§12.1 hard constraint)
    evidence_loc_ids: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)  # List[str] of loc_ids (text spans licensing the link)

    # Optional justification
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Confidence and provenance
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_extraction_run.run_id"))

    edition: Mapped[Edition] = relationship()
    target_proposition: Mapped[ArgumentProposition] = relationship(foreign_keys=[target_prop_id])
    extraction_run: Mapped[ArgumentExtractionRun] = relationship()

    __table_args__ = (
        Index("ix_argument_relation_edition", "edition_id"),
        Index("ix_argument_relation_target", "target_prop_id"),
        Index("ix_argument_relation_type", "relation_type"),
    )


class ArgumentTransition(Base):
    """
    Discourse transition between locutions (persisted, queryable).

    Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md §3.3 and Appendix A:
    Transitions are persisted and queryable as first-class objects. They encode
    rhetorical motion independent of argument structure and are analytically
    valuable for identifying discourse boundaries, recovering authorial intent,
    and supporting fine-grained navigation.

    Transitions are not arguments themselves but signal likely illocutionary
    and argumentative structure.
    """
    __tablename__ = "argument_transition"

    transition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[str] = mapped_column(String(128), nullable=False)  # Document identifier (for cross-doc tracking)

    # Locutions connected by this transition
    from_loc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_locution.loc_id"), nullable=False)
    to_loc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_locution.loc_id"), nullable=False)

    # The discourse marker (e.g., "however", "therefore", "on the contrary")
    marker: Mapped[str] = mapped_column(String(256), nullable=False)

    # Functional classification
    function_hint: Mapped[TransitionHint] = mapped_column(
        Enum(TransitionHint, native_enum=False), nullable=False
    )

    # Position in text (for ordering)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_argument_transition_doc", "doc_id"),
        Index("ix_argument_transition_from", "from_loc_id"),
        Index("ix_argument_transition_to", "to_loc_id"),
    )


class ConceptBinding(Base):
    """
    Concept binding for propositions (§9.1).

    Per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md:
    Each proposition may bind to one or more concepts with:
    - concept_id
    - embedding
    - time_index (document date)
    """
    __tablename__ = "concept_binding"

    binding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_proposition.prop_id"), nullable=False)

    # Reference to existing Concept table (Stage A/B)
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("concept.concept_id"), nullable=False)

    # Confidence and provenance
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_extraction_run.run_id"))

    proposition: Mapped[ArgumentProposition] = relationship()
    concept: Mapped["Concept"] = relationship()
    extraction_run: Mapped[ArgumentExtractionRun] = relationship()

    __table_args__ = (
        Index("ix_concept_binding_prop", "prop_id"),
        Index("ix_concept_binding_concept", "concept_id"),
    )


class RetrievedProposition(Base):
    """
    Retrieved context proposition (read-only, non-extractible).

    Per §5.4: Retrieved context presentation (critical):
    To prevent context poisoning, retrieved material is presented as:
    - Explicit marking with [RETRIEVED_CONTEXT]
    - Structurally separated from extraction window
    - Read-only constraint: marked with extractable=false
    - Cannot generate new locutions
    - Relations may cite retrieved props as premises, but retrieved text
      cannot serve as evidence locutions

    This table tracks which propositions were retrieved for context
    during extraction, preventing circular references and ensuring
    auditability of what context influenced each extraction.
    """
    __tablename__ = "retrieved_proposition"

    retrieval_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The extraction run that performed the retrieval
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_extraction_run.run_id"))

    # The window/edition that retrieved this context
    window_id: Mapped[str] = mapped_column(String(128), nullable=False)  # The ExtractionWindow that retrieved this
    edition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("edition.edition_id"), nullable=False)

    # The proposition that was retrieved for context
    source_prop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("argument_proposition.prop_id"), nullable=False)

    # Source edition of the retrieved proposition (for cross-document retrieval)
    source_edition_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("edition.edition_id"), nullable=True)

    # Retrieval metadata
    retrieval_method: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., "vector", "concept_overlap", "entity_alignment"
    retrieval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_in_context: Mapped[int] = mapped_column(Integer, nullable=False)  # Order in retrieved context list

    extraction_run: Mapped[ArgumentExtractionRun] = relationship()
    edition: Mapped[Edition] = relationship()
    source_proposition: Mapped[ArgumentProposition] = relationship()
    source_edition: Mapped[Edition | None] = relationship(foreign_keys=[source_edition_id])

    __table_args__ = (
        Index("ix_retrieved_proposition_window", "window_id"),
        Index("ix_retrieved_proposition_edition", "edition_id"),
        Index("ix_retrieved_proposition_run", "extraction_run_id"),
    )


class EntityCatalog(Base):
    """
    Canonical catalog of named entities (persons, schools, positions).

    Enables stable entity resolution across argument extraction runs.
    """
    __tablename__ = "entity_catalog"

    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Entity type
    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, native_enum=False), nullable=False
    )

    # Canonical name/label
    label_canonical: Mapped[str] = mapped_column(String(512), nullable=False)

    # Aliases and variants
    aliases: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)

    # Optional metadata (renamed from 'metadata' - reserved in SQLAlchemy)
    entity_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # External reference (e.g., to Author table for persons)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("author.author_id"), nullable=True
    )

    # Provenance
    created_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("argument_extraction_run.run_id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")

    author: Mapped[Author | None] = relationship()

    __table_args__ = (
        Index("ix_entity_catalog_type", "entity_type"),
        Index("ix_entity_catalog_label", "label_canonical"),
    )


class EntityBinding(Base):
    """
    Binds surface form mentions to canonical entities.

    Enables stable attribution of propositions to specific persons/schools.
    """
    __tablename__ = "entity_binding"

    binding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The canonical entity this binding resolves to
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("entity_catalog.entity_id"), nullable=False)

    # Surface form mention
    surface_form: Mapped[str] = mapped_column(String(512), nullable=False)

    # Context of the mention (which proposition/locution)
    proposition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("argument_proposition.prop_id"), nullable=True
    )
    locution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("argument_locution.loc_id"), nullable=True
    )

    # Confidence and provenance
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("argument_extraction_run.run_id"), nullable=True
    )

    entity: Mapped[EntityCatalog] = relationship()
    proposition: Mapped[ArgumentProposition | None] = relationship()
    locution: Mapped[ArgumentLocution | None] = relationship()

    __table_args__ = (
        Index("ix_entity_binding_entity", "entity_id"),
        Index("ix_entity_binding_surface", "surface_form"),
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
        # Argument extraction models (AIF/IAT per AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md)
        ArgumentExtractionRun,
        ArgumentLocution,
        ArgumentProposition,
        ArgumentIllocution,
        ArgumentRelation,
        ArgumentTransition,
        ConceptBinding,
        RetrievedProposition,
        EntityCatalog,
        EntityBinding,
    )
