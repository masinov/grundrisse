"""Add index for idempotent ingest paragraph lookups

Revision ID: 0009_para_ed_order
Revises: 0008_mention_tech_raw
Create Date: 2025-12-30
"""

from __future__ import annotations

from alembic import op


revision = "0009_para_ed_order"
down_revision = "0008_mention_tech_raw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_paragraph_edition_order",
        "paragraph",
        ["edition_id", "order_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_paragraph_edition_order", table_name="paragraph")

