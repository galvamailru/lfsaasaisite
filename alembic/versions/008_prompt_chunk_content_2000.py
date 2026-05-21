"""Increase prompt_chunk.content from 500 to 2000 chars.

Revision ID: 008
Revises: 007
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "prompt_chunk",
        "content",
        existing_type=sa.String(500),
        type_=sa.String(2000),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "prompt_chunk",
        "content",
        existing_type=sa.String(2000),
        type_=sa.String(500),
        existing_nullable=False,
    )
