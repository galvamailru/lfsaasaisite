"""Drop prompt_survey from user_profile (откат анкеты).

Revision ID: 014
Revises: 013
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("user_profile", "prompt_survey")


def downgrade() -> None:
    op.add_column(
        "user_profile",
        sa.Column("prompt_survey", postgresql.JSONB(), nullable=True),
    )
