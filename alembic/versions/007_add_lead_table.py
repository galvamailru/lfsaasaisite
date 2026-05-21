"""Add lead table (contacts from dialogs).

Revision ID: 007
Revises: 006
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("dialog_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dialog_id"], ["dialog.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_tenant_id", "lead", ["tenant_id"], unique=False)
    op.create_unique_constraint("uq_lead_tenant_user_dialog", "lead", ["tenant_id", "user_id", "dialog_id"])


def downgrade() -> None:
    op.drop_constraint("uq_lead_tenant_user_dialog", "lead", type_="unique")
    op.drop_index("ix_lead_tenant_id", table_name="lead")
    op.drop_table("lead")
