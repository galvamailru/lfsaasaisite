"""Add system_prompt to tenant (per-tenant chatbot prompt).

Revision ID: 005
Revises: 004
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("system_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant", "system_prompt")
