"""Add author aliases and display names.

Revision ID: 0013_author_aliases
Revises: 0012_progressive_classify
Create Date: 2026-01-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0013_author_aliases'
down_revision = '0012_progressive_classify'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns to author table
    op.add_column('author', sa.Column('name_display', sa.String(), nullable=True))
    op.add_column('author', sa.Column('name_sort', sa.String(), nullable=True))

    # Create author_aliases table
    op.create_table(
        'author_aliases',
        sa.Column('alias_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('author_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name_variant', sa.String(), nullable=False),
        sa.Column('variant_type', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['author.author_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('alias_id'),
    )

    # Create indexes for searching
    op.create_index('idx_author_aliases_author_id', 'author_aliases', ['author_id'])
    op.create_index('idx_author_aliases_name_variant', 'author_aliases', ['name_variant'])
    op.create_index('idx_author_name_display', 'author', ['name_display'])
    op.create_index('idx_author_name_sort', 'author', ['name_sort'])

    # Populate name_display with name_canonical (default)
    op.execute("UPDATE author SET name_display = name_canonical WHERE name_display IS NULL")

    # Populate name_sort with reversed name for sorting (Last, First)
    # This is a simple heuristic - will be improved by the population tool
    op.execute("""
        UPDATE author
        SET name_sort = CASE
            WHEN name_canonical LIKE '% %' THEN
                regexp_replace(name_canonical, '^(.*) ([^ ]+)$', '\\2, \\1')
            ELSE
                name_canonical
        END
        WHERE name_sort IS NULL
    """)

    # Make columns non-nullable after populating
    op.alter_column('author', 'name_display', nullable=False)
    op.alter_column('author', 'name_sort', nullable=False)


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_author_name_sort', 'author')
    op.drop_index('idx_author_name_display', 'author')
    op.drop_index('idx_author_aliases_name_variant', 'author_aliases')
    op.drop_index('idx_author_aliases_author_id', 'author_aliases')

    # Drop table
    op.drop_table('author_aliases')

    # Drop columns
    op.drop_column('author', 'name_sort')
    op.drop_column('author', 'name_display')
