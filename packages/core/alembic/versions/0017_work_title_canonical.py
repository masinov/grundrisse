"""Add work.title_canonical for standardized display titles.

Revision ID: 0017_work_title_canonical
Revises: 0016_work_date_final
Create Date: 2026-01-04

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0017_work_title_canonical"
down_revision = "0016_work_date_final"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work", sa.Column("title_canonical", sa.String(length=1024), nullable=True))
    op.create_index("ix_work_title_canonical", "work", ["title_canonical"])


def downgrade() -> None:
    op.drop_index("ix_work_title_canonical", table_name="work")
    op.drop_column("work", "title_canonical")

