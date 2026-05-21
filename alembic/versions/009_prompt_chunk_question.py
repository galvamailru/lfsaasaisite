"""Add question column to prompt_chunk (admin bot question that led to this chunk).

Revision ID: 009
Revises: 008
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("prompt_chunk", sa.Column("question", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("prompt_chunk", "question")
