"""Add frozen first-publication date table for works.

Revision ID: 0016_work_date_final
Revises: 0015_author_metadata_runs
Create Date: 2026-01-03

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0016_work_date_final"
down_revision = "0015_author_metadata_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_date_final",
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_publication_date", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("method", sa.String(length=64), nullable=True),
        sa.Column("precision", sa.String(length=32), nullable=True),
        sa.Column("final_evidence_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finalized_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="finalized"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["work_id"], ["work.work_id"]),
        sa.ForeignKeyConstraint(["final_evidence_id"], ["work_metadata_evidence.evidence_id"]),
        sa.ForeignKeyConstraint(["finalized_run_id"], ["work_metadata_run.run_id"]),
        sa.PrimaryKeyConstraint("work_id"),
    )
    op.create_index("ix_work_date_final_status", "work_date_final", ["status"])
    op.create_index("ix_work_date_final_method", "work_date_final", ["method"])


def downgrade() -> None:
    op.drop_index("ix_work_date_final_method", table_name="work_date_final")
    op.drop_index("ix_work_date_final_status", table_name="work_date_final")
    op.drop_table("work_date_final")

