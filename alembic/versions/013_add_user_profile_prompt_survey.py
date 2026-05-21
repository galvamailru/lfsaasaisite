"""Add prompt_survey (JSONB) to user_profile.

Revision ID: 013
Revises: 012
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("prompt_survey", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "prompt_survey")

