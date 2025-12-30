"""Add claim.dialectical_status_raw

Revision ID: 0005_ds_raw
Revises: 0004_claim_polarity_raw
Create Date: 2025-12-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_ds_raw"
down_revision = "0004_claim_polarity_raw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("claim", sa.Column("dialectical_status_raw", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("claim", "dialectical_status_raw")
