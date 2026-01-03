"""Add crawler tables

Revision ID: 0011_add_crawler_tables
Revises: 0010_text_block_source_url
Create Date: 2025-12-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0011_add_crawler_tables"
down_revision = "0010_text_block_source_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create crawl_run table
    op.create_table(
        "crawl_run",
        sa.Column("crawl_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_version", sa.String(length=128), nullable=False),
        sa.Column("git_commit_hash", sa.String(length=64), nullable=True),
        sa.Column("crawl_scope", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("urls_discovered", sa.Integer(), nullable=False),
        sa.Column("urls_fetched", sa.Integer(), nullable=False),
        sa.Column("urls_failed", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("crawl_run_id"),
    )

    # Create url_catalog_entry table
    op.create_table(
        "url_catalog_entry",
        sa.Column("url_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url_canonical", sa.Text(), nullable=False),
        sa.Column("discovered_from_url", sa.Text(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("crawl_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=256), nullable=True),
        sa.Column("etag", sa.String(length=512), nullable=True),
        sa.Column("last_modified", sa.String(length=256), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("raw_path", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_run.crawl_run_id"]),
        sa.PrimaryKeyConstraint("url_id"),
        sa.UniqueConstraint("url_canonical"),
    )
    op.create_index("ix_url_catalog_status", "url_catalog_entry", ["status"])
    op.create_index("ix_url_catalog_sha256", "url_catalog_entry", ["content_sha256"])

    # Create work_discovery table
    op.create_table(
        "work_discovery",
        sa.Column("discovery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("root_url", sa.Text(), nullable=False),
        sa.Column("author_name", sa.String(length=512), nullable=False),
        sa.Column("work_title", sa.String(length=1024), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("page_urls", sa.JSON(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingestion_status", sa.String(length=32), nullable=False),
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_run.crawl_run_id"]),
        sa.ForeignKeyConstraint(["edition_id"], ["edition.edition_id"]),
        sa.PrimaryKeyConstraint("discovery_id"),
    )
    op.create_index("ix_work_discovery_ingestion_status", "work_discovery", ["ingestion_status"])


def downgrade() -> None:
    op.drop_index("ix_work_discovery_ingestion_status", table_name="work_discovery")
    op.drop_table("work_discovery")
    op.drop_index("ix_url_catalog_sha256", table_name="url_catalog_entry")
    op.drop_index("ix_url_catalog_status", table_name="url_catalog_entry")
    op.drop_table("url_catalog_entry")
    op.drop_table("crawl_run")
