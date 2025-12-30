"""Add claim.polarity_raw

Revision ID: 0004_claim_polarity_raw
Revises: 0003_claim_claim_type_raw
Create Date: 2025-12-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_claim_polarity_raw"
down_revision = "0003_claim_claim_type_raw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("claim", sa.Column("polarity_raw", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("claim", "polarity_raw")

