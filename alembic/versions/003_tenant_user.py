"""Add tenant_user for registration with email confirmation.

Revision ID: 003
Revises: 002
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_user",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("email_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmation_token", sa.String(128), nullable=True),
        sa.Column("confirmation_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tenant_user_tenant_email",
        "tenant_user",
        ["tenant_id", "email"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_user_tenant_email", table_name="tenant_user")
    op.drop_table("tenant_user")
