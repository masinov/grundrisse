"""Add work metadata run/evidence tables.

Revision ID: 0014_work_metadata_runs
Revises: 0013_author_aliases
Create Date: 2026-01-03

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0014_work_metadata_runs"
down_revision = "0013_author_aliases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_metadata_run",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_version", sa.String(length=128), nullable=False),
        sa.Column("git_commit_hash", sa.String(length=64), nullable=True),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("sources", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="started"),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("works_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("works_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("works_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("works_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("run_id"),
    )

    op.create_table(
        "work_metadata_evidence",
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("raw_sha256", sa.String(length=64), nullable=True),
        sa.Column("extracted", sa.JSON(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["work_metadata_run.run_id"]),
        sa.ForeignKeyConstraint(["work_id"], ["work.work_id"]),
        sa.PrimaryKeyConstraint("evidence_id"),
    )

    op.create_index("ix_work_metadata_evidence_work", "work_metadata_evidence", ["work_id"])
    op.create_index("ix_work_metadata_evidence_run", "work_metadata_evidence", ["run_id"])
    op.create_index("ix_work_metadata_evidence_source", "work_metadata_evidence", ["source_name"])


def downgrade() -> None:
    op.drop_index("ix_work_metadata_evidence_source", table_name="work_metadata_evidence")
    op.drop_index("ix_work_metadata_evidence_run", table_name="work_metadata_evidence")
    op.drop_index("ix_work_metadata_evidence_work", table_name="work_metadata_evidence")
    op.drop_table("work_metadata_evidence")
    op.drop_table("work_metadata_run")

