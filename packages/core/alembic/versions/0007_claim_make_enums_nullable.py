"""Make claim enum-like fields nullable

Revision ID: 0007_claim_nullable
Revises: 0006_claim_attribution_raw
Create Date: 2025-12-30
"""

from __future__ import annotations

from alembic import op

revision = "0007_claim_nullable"
down_revision = "0006_claim_attribution_raw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE claim ALTER COLUMN claim_type DROP NOT NULL")
    op.execute("ALTER TABLE claim ALTER COLUMN polarity DROP NOT NULL")
    op.execute("ALTER TABLE claim ALTER COLUMN dialectical_status DROP NOT NULL")
    op.execute("ALTER TABLE claim ALTER COLUMN attribution DROP NOT NULL")


def downgrade() -> None:
    # Downgrade is best-effort: if NULLs exist, this will fail until cleaned.
    op.execute("ALTER TABLE claim ALTER COLUMN claim_type SET NOT NULL")
    op.execute("ALTER TABLE claim ALTER COLUMN polarity SET NOT NULL")
    op.execute("ALTER TABLE claim ALTER COLUMN dialectical_status SET NOT NULL")
    op.execute("ALTER TABLE claim ALTER COLUMN attribution SET NOT NULL")

