"""Add normalized edition source header table.

Revision ID: 0020_edition_source_header
Revises: 0019_work_date_derived
Create Date: 2026-01-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_edition_source_header"
down_revision = "0019_work_date_derived"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edition_source_header",
        sa.Column(
            "edition_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("edition.edition_id"),
            primary_key=True,
        ),
        sa.Column("source_name", sa.String(length=64), nullable=False, server_default="marxists"),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_object_key", sa.Text(), nullable=True),
        sa.Column("raw_sha256", sa.String(length=64), nullable=True),
        sa.Column("raw_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("raw_dates", sa.JSON(), nullable=True),
        sa.Column("editorial_intro", sa.JSON(), nullable=True),
        sa.Column("written_date", sa.JSON(), nullable=True),
        sa.Column("first_published_date", sa.JSON(), nullable=True),
        sa.Column("published_date", sa.JSON(), nullable=True),
        sa.Column("source_citation_raw", sa.Text(), nullable=True),
        sa.Column("translated_raw", sa.Text(), nullable=True),
        sa.Column("transcription_markup_raw", sa.Text(), nullable=True),
        sa.Column("public_domain_raw", sa.Text(), nullable=True),
    )
    op.create_index("ix_edition_source_header_source", "edition_source_header", ["source_name"])


def downgrade() -> None:
    op.drop_index("ix_edition_source_header_source", table_name="edition_source_header")
    op.drop_table("edition_source_header")

