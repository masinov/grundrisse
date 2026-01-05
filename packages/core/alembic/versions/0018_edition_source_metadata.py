"""Add edition.source_metadata JSON for per-source header fields.

Revision ID: 0018_edition_source_metadata
Revises: 0017_work_title_canonical
Create Date: 2026-01-05

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0018_edition_source_metadata"
down_revision = "0017_work_title_canonical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("edition", sa.Column("source_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("edition", "source_metadata")

