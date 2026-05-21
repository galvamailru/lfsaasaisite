"""Add reset_password_token and reset_password_expires_at to tenant_user.

Revision ID: 016
Revises: 015
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_user",
        sa.Column("reset_password_token", sa.String(128), nullable=True),
    )
    op.add_column(
        "tenant_user",
        sa.Column("reset_password_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_user", "reset_password_expires_at")
    op.drop_column("tenant_user", "reset_password_token")
