"""Add TextBlock.source_url

Revision ID: 0010_text_block_source_url
Revises: 0009_para_ed_order
Create Date: 2025-12-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_text_block_source_url"
down_revision = "0009_para_ed_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("text_block", sa.Column("source_url", sa.Text(), nullable=True))
    op.create_index("ix_text_block_source_url", "text_block", ["source_url"])


def downgrade() -> None:
    op.drop_index("ix_text_block_source_url", table_name="text_block")
    op.drop_column("text_block", "source_url")

