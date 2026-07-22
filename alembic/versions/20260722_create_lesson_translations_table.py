"""create lesson translations table

Revision ID: lesson_translations_001
Revises: reference_translations_001
Create Date: 2026-07-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'lesson_translations_001'
down_revision = 'reference_translations_001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lesson_translations',
        sa.Column('entity_type', sa.Text(), primary_key=True, nullable=False),
        sa.Column('entity_id', sa.BigInteger(), primary_key=True, nullable=False),
        sa.Column('field', sa.Text(), primary_key=True, nullable=False),
        sa.Column('language', sa.Text(), primary_key=True, nullable=False),
        sa.Column('translated_text', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False, server_default='mt'),
        sa.Column('translated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('reviewed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('source_hash', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table('lesson_translations')
