"""Add claim.claim_type_raw

Revision ID: 0003_claim_claim_type_raw
Revises: 0002_claim_modality_raw
Create Date: 2025-12-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_claim_claim_type_raw"
down_revision = "0002_claim_modality_raw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("claim", sa.Column("claim_type_raw", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("claim", "claim_type_raw")

