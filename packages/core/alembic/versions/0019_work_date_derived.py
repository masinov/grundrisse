"""Add derived work date bundle and derivation runs.

Revision ID: 0019_work_date_derived
Revises: 0018_edition_source_metadata
Create Date: 2026-01-05

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0019_work_date_derived"
down_revision = "0018_edition_source_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_date_derivation_run",
        sa.Column("run_id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pipeline_version", sa.String(length=128), nullable=False),
        sa.Column("git_commit_hash", sa.String(length=64), nullable=True),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("works_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("works_derived", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("works_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("works_failed", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "work_date_derived",
        sa.Column(
            "work_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work.work_id"),
            primary_key=True,
        ),
        sa.Column("dates", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("display_date", sa.JSON(), nullable=True),
        sa.Column("display_date_field", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("display_year", sa.Integer(), nullable=True),
        sa.Column(
            "derived_run_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_date_derivation_run.run_id"),
            nullable=True,
        ),
        sa.Column("derived_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_work_date_derived_display_year", "work_date_derived", ["display_year"])


def downgrade() -> None:
    op.drop_index("ix_work_date_derived_display_year", table_name="work_date_derived")
    op.drop_table("work_date_derived")
    op.drop_table("work_date_derivation_run")

