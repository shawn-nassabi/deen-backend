"""create reference translations table

Revision ID: reference_translations_001
Revises: onboarding_profiles_001
Create Date: 2026-07-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'reference_translations_001'
down_revision = 'onboarding_profiles_001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'reference_translations',
        sa.Column('ref_type', sa.Text(), primary_key=True, nullable=False),
        sa.Column('ref_key', sa.Text(), primary_key=True, nullable=False),
        sa.Column('language', sa.Text(), primary_key=True, nullable=False),
        sa.Column('translated_text', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False, server_default='mt'),
        sa.Column('translated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('reviewed_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table('reference_translations')
