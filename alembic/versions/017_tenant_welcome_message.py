"""Add welcome_message to tenant.

Revision ID: 017
Revises: 016
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column("welcome_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant", "welcome_message")
