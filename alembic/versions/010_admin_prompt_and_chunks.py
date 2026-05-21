"""Add admin system prompt (tenant) and admin_prompt_chunk table.

Revision ID: 010
Revises: 009
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("admin_system_prompt", sa.Text(), nullable=True))

    op.create_table(
        "admin_prompt_chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question", sa.String(1000), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_prompt_chunk_tenant_position",
        "admin_prompt_chunk",
        ["tenant_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admin_prompt_chunk_tenant_position", table_name="admin_prompt_chunk")
    op.drop_table("admin_prompt_chunk")
    op.drop_column("tenant", "admin_system_prompt")
