"""Make concept_mention.is_technical nullable and add is_technical_raw

Revision ID: 0008_mention_tech_raw
Revises: 0007_claim_nullable
Create Date: 2025-12-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_mention_tech_raw"
down_revision = "0007_claim_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("concept_mention", sa.Column("is_technical_raw", sa.Text(), nullable=True))
    op.execute("ALTER TABLE concept_mention ALTER COLUMN is_technical DROP NOT NULL")
    op.execute("ALTER TABLE concept_mention ALTER COLUMN is_technical DROP DEFAULT")


def downgrade() -> None:
    # Best-effort: if NULLs exist, this will fail until cleaned.
    op.execute("ALTER TABLE concept_mention ALTER COLUMN is_technical SET DEFAULT false")
    op.execute("ALTER TABLE concept_mention ALTER COLUMN is_technical SET NOT NULL")
    op.drop_column("concept_mention", "is_technical_raw")

