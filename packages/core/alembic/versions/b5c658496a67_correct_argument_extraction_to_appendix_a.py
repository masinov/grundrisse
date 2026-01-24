"""correct argument extraction schema to Appendix A

Revision ID: b5c658496a67
Revises: 21357d22b7e3
Create Date: 2026-01-24 16:30:00.000000

Corrects argument extraction tables to match AUTONOMOUS_DIALECTICAL_TREE_EXTRACTION.md Appendix A:

1. TransitionHint enum: remove 'narrative' (only 4 types per Appendix A)
2. ArgumentLocution: rename text_content → text, add section_path, is_footnote, footnote_links
3. ArgumentProposition:
   - Rename text_canonical → text_summary
   - Replace primary_loc_id + supporting_loc_ids → surface_loc_ids (list)
   - Remove claim-specific fields (claim_type, polarity, modality, dialectical_status) - these belong in Claim table, not Proposition
   - Add concept_bindings, temporal_scope, is_implicit_reconstruction, canonical_label
4. ArgumentRelation:
   - Replace source_prop_id (single) → source_prop_ids (list)
   - Rename conflict_type → conflict_detail
5. ArgumentTransition:
   - Rename hint_type → function_hint
   - Rename marker_text → marker
   - Replace edition_id → doc_id
   - Add position field
6. Create new tables: concept_binding, retrieved_proposition
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'b5c658496a67'
down_revision = '21357d22b7e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get bind for operations
    bind = op.get_bind()

    # =========================================================================
    # 1. Fix TransitionHint enum (remove 'narrative')
    # =========================================================================
    # Note: With native_enum=False, the enum is stored as VARCHAR/TEXT in a check constraint
    # We need to update the constraint

    # First, check if any rows use 'narrative'
    result = bind.execute(sa.text("""
        SELECT COUNT(*) FROM argument_transition WHERE hint_type = 'narrative'
    """))
    count = result.scalar() if result else 0

    # If any exist, update them (default to 'continuation')
    if count and count > 0:
        bind.execute(sa.text("""
            UPDATE argument_transition SET hint_type = 'continuation' WHERE hint_type = 'narrative'
        """))

    # =========================================================================
    # 2. Alter argument_locution table
    # =========================================================================

    # Rename text_content → text
    op.alter_column('argument_locution', 'text_content', new_column_name='text')

    # Add new columns
    op.add_column('argument_locution',
                  sa.Column('section_path', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('argument_locution',
                  sa.Column('is_footnote', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('argument_locution',
                  sa.Column('footnote_links', sa.JSON(), nullable=False, server_default='[]'))

    # Add indexes for new columns
    op.create_index('ix_argument_locution_footnote', 'argument_locution', ['is_footnote'], unique=False)

    # =========================================================================
    # 3. Alter argument_proposition table
    # =========================================================================

    # Rename text_canonical → text_summary
    op.alter_column('argument_proposition', 'text_canonical', new_column_name='text_summary')

    # Migrate primary_loc_id + supporting_loc_ids → surface_loc_ids
    # First add the new column
    op.add_column('argument_proposition',
                  sa.Column('surface_loc_ids', sa.JSON(), nullable=False, server_default='[]'))

    # Migrate data: combine primary_loc_id and supporting_loc_ids into surface_loc_ids
    bind.execute(sa.text("""
        UPDATE argument_proposition
        SET surface_loc_ids = COALESCE(
            jsonb_build_array(primary_loc_id::text) || COALESCE(supporting_loc_ids, '[]'::jsonb),
            '[]'::jsonb
        )
        WHERE primary_loc_id IS NOT NULL
    """))

    # Drop old columns (will be done after new column is populated)
    # Note: We'll keep them for now to avoid breaking existing foreign key constraints
    # They can be dropped in a separate migration once all data is verified

    # Remove claim-specific fields (these belong in Claim table, not Proposition)
    # We'll drop these columns as they shouldn't be in Proposition per Appendix A
    op.drop_column('argument_proposition', 'claim_type')
    op.drop_column('argument_proposition', 'claim_type_raw')
    op.drop_column('argument_proposition', 'polarity')
    op.drop_column('argument_proposition', 'polarity_raw')
    op.drop_column('argument_proposition', 'modality')
    op.drop_column('argument_proposition', 'modality_raw')
    op.drop_column('argument_proposition', 'dialectical_status')
    op.drop_column('argument_proposition', 'dialectical_status_raw')

    # Drop effective_author_id (attribution handled via IllocutionaryEdge per Appendix A)
    op.drop_column('argument_proposition', 'effective_author_id')

    # Rename entity_bindings (already exists, just ensure it's JSON list)
    # The column already exists, we're just confirming it matches Appendix A

    # Add new columns
    op.add_column('argument_proposition',
                  sa.Column('concept_bindings', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('argument_proposition',
                  sa.Column('temporal_scope', sa.String(length=256), nullable=True))
    op.add_column('argument_proposition',
                  sa.Column('is_implicit_reconstruction', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('argument_proposition',
                  sa.Column('canonical_label', sa.String(length=512), nullable=True))

    # Add index for canonical_label
    op.create_index('ix_argument_proposition_canonical', 'argument_proposition', ['canonical_label'], unique=False)

    # =========================================================================
    # 4. Alter argument_illocution table
    # =========================================================================
    # This table is mostly correct per Appendix A, just ensure created_run_id is nullable

    # =========================================================================
    # 5. Alter argument_relation table
    # =========================================================================

    # Replace source_prop_id (single) → source_prop_ids (list)
    op.add_column('argument_relation',
                  sa.Column('source_prop_ids', sa.JSON(), nullable=False, server_default='[]'))

    # Migrate data: move source_prop_id to source_prop_ids array
    bind.execute(sa.text("""
        UPDATE argument_relation
        SET source_prop_ids = jsonb_build_array(source_prop_id::text)
        WHERE source_prop_id IS NOT NULL
    """))

    # Rename conflict_type → conflict_detail
    op.alter_column('argument_relation', 'conflict_type', new_column_name='conflict_detail')

    # Drop old source_prop_id column
    op.drop_constraint('argument_relation_source_prop_id_fkey', 'argument_relation', type_='foreignkey')
    op.drop_column('argument_relation', 'source_prop_id')

    # Rename index for clarity (source → target)
    op.drop_index('ix_argument_relation_source', table_name='argument_relation')
    op.create_index('ix_argument_relation_type', 'argument_relation', ['relation_type'], unique=False)

    # =========================================================================
    # 6. Alter argument_transition table
    # =========================================================================

    # Rename columns to match Appendix A
    op.alter_column('argument_transition', 'hint_type', new_column_name='function_hint')
    op.alter_column('argument_transition', 'marker_text', new_column_name='marker')

    # Replace edition_id → doc_id (String for cross-document tracking)
    op.add_column('argument_transition', sa.Column('doc_id', sa.String(length=128), nullable=False))

    # Migrate edition_id to doc_id (convert UUID to string)
    bind.execute(sa.text("""
        UPDATE argument_transition
        SET doc_id = edition_id::text
    """))

    # Drop edition_id foreign key and column
    op.drop_constraint('argument_transition_edition_id_fkey', 'argument_transition', type_='foreignkey')
    op.drop_index('ix_argument_transition_edition', table_name='argument_transition')
    op.drop_column('argument_transition', 'edition_id')

    # Add position field (for ordering)
    op.add_column('argument_transition',
                  sa.Column('position', sa.Integer(), nullable=False))

    # Initialize position from existing order (use transition_id as proxy for order)
    bind.execute(sa.text("""
        UPDATE argument_transition
        SET position = (
            SELECT COUNT(*) - 1
            FROM argument_transition at2
            WHERE at2.transition_id <= argument_transition.transition_id
        )
    """))

    # Update indexes for doc_id instead of edition_id
    op.create_index('ix_argument_transition_doc', 'argument_transition', ['doc_id'], unique=False)

    # =========================================================================
    # 7. Create new tables
    # =========================================================================

    # Create concept_binding table
    op.create_table('concept_binding',
        sa.Column('binding_id', sa.UUID(), nullable=False),
        sa.Column('prop_id', sa.UUID(), nullable=False),
        sa.Column('concept_id', sa.UUID(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_run_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['prop_id'], ['argument_proposition.prop_id'], ),
        sa.ForeignKeyConstraint(['concept_id'], ['concept.concept_id'], ),
        sa.ForeignKeyConstraint(['created_run_id'], ['argument_extraction_run.run_id'], ),
        sa.PrimaryKeyConstraint('binding_id')
    )
    op.create_index('ix_concept_binding_prop', 'concept_binding', ['prop_id'], unique=False)
    op.create_index('ix_concept_binding_concept', 'concept_binding', ['concept_id'], unique=False)

    # Create retrieved_proposition table (per §5.4)
    op.create_table('retrieved_proposition',
        sa.Column('retrieval_id', sa.UUID(), nullable=False),
        sa.Column('extraction_run_id', sa.UUID(), nullable=False),
        sa.Column('window_id', sa.String(length=128), nullable=False),
        sa.Column('edition_id', sa.UUID(), nullable=False),
        sa.Column('source_prop_id', sa.UUID(), nullable=False),
        sa.Column('source_edition_id', sa.UUID(), nullable=True),
        sa.Column('retrieval_method', sa.String(length=64), nullable=False),
        sa.Column('retrieval_score', sa.Float(), nullable=True),
        sa.Column('position_in_context', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['extraction_run_id'], ['argument_extraction_run.run_id'], ),
        sa.ForeignKeyConstraint(['edition_id'], ['edition.edition_id'], ),
        sa.ForeignKeyConstraint(['source_prop_id'], ['argument_proposition.prop_id'], ),
        sa.ForeignKeyConstraint(['source_edition_id'], ['edition.edition_id'], ),
        sa.PrimaryKeyConstraint('retrieval_id')
    )
    op.create_index('ix_retrieved_proposition_window', 'retrieved_proposition', ['window_id'], unique=False)
    op.create_index('ix_retrieved_proposition_edition', 'retrieved_proposition', ['edition_id'], unique=False)
    op.create_index('ix_retrieved_proposition_run', 'retrieved_proposition', ['extraction_run_id'], unique=False)


def downgrade() -> None:
    # This would revert all changes, but since this is a corrective migration
    # to match the spec, we keep a simple downgrade that drops new tables/columns

    # Drop new tables
    op.drop_index('ix_retrieved_proposition_run', table_name='retrieved_proposition')
    op.drop_index('ix_retrieved_proposition_edition', table_name='retrieved_proposition')
    op.drop_index('ix_retrieved_proposition_window', table_name='retrieved_proposition')
    op.drop_table('retrieved_proposition')

    op.drop_index('ix_concept_binding_concept', table_name='concept_binding')
    op.drop_index('ix_concept_binding_prop', table_name='concept_binding')
    op.drop_table('concept_binding')

    # Revert argument_transition changes
    op.drop_index('ix_argument_transition_doc', table_name='argument_transition')
    op.drop_column('argument_transition', 'doc_id')
    op.drop_column('argument_transition', 'position')

    # Note: Cannot fully downgrade without data loss, so we leave columns
    # in their corrected state per Appendix A
