"""Drop unused vector_embeddings table and pgvector extension.

The tool retrieval system uses in-memory embeddings cached in Redis,
not PostgreSQL pgvector. This table was created but never populated.

Revision ID: drop_vector_embeddings
Revises: 38bc7c245fec
Create Date: 2026-03-18 19:23:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'drop_vector_embeddings'
down_revision: Union[str, None] = '38bc7c245fec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f('ix_vector_embeddings_user_id'), table_name='vector_embeddings')
    op.drop_index(op.f('ix_vector_embeddings_id'), table_name='vector_embeddings')
    op.drop_table('vector_embeddings')
    op.execute('DROP EXTENSION IF EXISTS vector;')


def downgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector;')
    op.create_table('vector_embeddings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', sa.LargeBinary(), nullable=True),
        sa.Column('meta_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vector_embeddings_id'), 'vector_embeddings', ['id'], unique=False)
    op.create_index(op.f('ix_vector_embeddings_user_id'), 'vector_embeddings', ['user_id'], unique=False)
