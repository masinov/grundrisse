"""Add progressive classification support

Revision ID: 0012_add_progressive_classification
Revises: 0011_add_crawler_tables
Create Date: 2025-12-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0012_add_progressive_classification"
down_revision = "0011_add_crawler_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add link graph fields to url_catalog_entry
    op.add_column("url_catalog_entry", sa.Column("parent_url_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("url_catalog_entry", sa.Column("depth", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("url_catalog_entry", sa.Column("child_count", sa.Integer(), nullable=False, server_default="0"))

    # Add classification fields to url_catalog_entry
    op.add_column(
        "url_catalog_entry",
        sa.Column("classification_status", sa.String(length=32), nullable=False, server_default="unclassified"),
    )
    op.add_column("url_catalog_entry", sa.Column("classification_result", sa.JSON(), nullable=True))
    op.add_column("url_catalog_entry", sa.Column("classification_run_id", postgresql.UUID(as_uuid=True), nullable=True))

    # Add foreign keys
    op.create_foreign_key(
        "fk_url_catalog_entry_parent",
        "url_catalog_entry",
        "url_catalog_entry",
        ["parent_url_id"],
        ["url_id"],
    )
    op.create_foreign_key(
        "fk_url_catalog_entry_classification_run",
        "url_catalog_entry",
        "classification_run",
        ["classification_run_id"],
        ["run_id"],
    )

    # Add indexes
    op.create_index("ix_url_catalog_depth", "url_catalog_entry", ["depth"])
    op.create_index("ix_url_catalog_classification_status", "url_catalog_entry", ["classification_status"])
    op.create_index("ix_url_catalog_parent", "url_catalog_entry", ["parent_url_id"])

    # Create classification_run table
    op.create_table(
        "classification_run",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("budget_tokens", sa.Integer(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("start_depth", sa.Integer(), nullable=True),
        sa.Column("current_depth", sa.Integer(), nullable=True),
        sa.Column("urls_classified", sa.Integer(), nullable=False),
        sa.Column("urls_pending", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_run.crawl_run_id"]),
        sa.PrimaryKeyConstraint("run_id"),
    )


def downgrade() -> None:
    # Drop classification_run table
    op.drop_table("classification_run")

    # Drop indexes from url_catalog_entry
    op.drop_index("ix_url_catalog_parent", table_name="url_catalog_entry")
    op.drop_index("ix_url_catalog_classification_status", table_name="url_catalog_entry")
    op.drop_index("ix_url_catalog_depth", table_name="url_catalog_entry")

    # Drop foreign keys
    op.drop_constraint("fk_url_catalog_entry_classification_run", "url_catalog_entry", type_="foreignkey")
    op.drop_constraint("fk_url_catalog_entry_parent", "url_catalog_entry", type_="foreignkey")

    # Drop columns from url_catalog_entry
    op.drop_column("url_catalog_entry", "classification_run_id")
    op.drop_column("url_catalog_entry", "classification_result")
    op.drop_column("url_catalog_entry", "classification_status")
    op.drop_column("url_catalog_entry", "child_count")
    op.drop_column("url_catalog_entry", "depth")
    op.drop_column("url_catalog_entry", "parent_url_id")
