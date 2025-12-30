"""Add claim.attribution_raw

Revision ID: 0006_claim_attribution_raw
Revises: 0005_ds_raw
Create Date: 2025-12-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_claim_attribution_raw"
down_revision = "0005_ds_raw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("claim", sa.Column("attribution_raw", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("claim", "attribution_raw")
