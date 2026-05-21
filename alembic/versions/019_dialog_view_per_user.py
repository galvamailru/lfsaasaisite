"""Replace dialog.viewed_at with dialog_view table (просмотр по пользователю кабинета).

Revision ID: 019
Revises: 018
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dialog_view",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("cabinet_user_id", sa.String(64), nullable=False),
        sa.Column("dialog_id", sa.Uuid(), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dialog_id"], ["dialog.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "cabinet_user_id", "dialog_id", name="uq_dialog_view_tenant_user_dialog"),
    )
    op.create_index("ix_dialog_view_tenant_cabinet_user", "dialog_view", ["tenant_id", "cabinet_user_id"], unique=False)
    op.drop_column("dialog", "viewed_at")


def downgrade() -> None:
    op.add_column(
        "dialog",
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_table("dialog_view")
