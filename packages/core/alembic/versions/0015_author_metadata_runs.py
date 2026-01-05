"""Add author metadata run/evidence tables.

Revision ID: 0015_author_metadata_runs
Revises: 0014_work_metadata_runs
Create Date: 2026-01-03

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0015_author_metadata_runs"
down_revision = "0014_work_metadata_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "author_metadata_run",
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
        sa.Column("authors_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("authors_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("authors_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("authors_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("run_id"),
    )

    op.create_table(
        "author_metadata_evidence",
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("raw_sha256", sa.String(length=64), nullable=True),
        sa.Column("extracted", sa.JSON(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["author_metadata_run.run_id"]),
        sa.ForeignKeyConstraint(["author_id"], ["author.author_id"]),
        sa.PrimaryKeyConstraint("evidence_id"),
    )

    op.create_index("ix_author_metadata_evidence_author", "author_metadata_evidence", ["author_id"])
    op.create_index("ix_author_metadata_evidence_run", "author_metadata_evidence", ["run_id"])
    op.create_index("ix_author_metadata_evidence_source", "author_metadata_evidence", ["source_name"])


def downgrade() -> None:
    op.drop_index("ix_author_metadata_evidence_source", table_name="author_metadata_evidence")
    op.drop_index("ix_author_metadata_evidence_run", table_name="author_metadata_evidence")
    op.drop_index("ix_author_metadata_evidence_author", table_name="author_metadata_evidence")
    op.drop_table("author_metadata_evidence")
    op.drop_table("author_metadata_run")

