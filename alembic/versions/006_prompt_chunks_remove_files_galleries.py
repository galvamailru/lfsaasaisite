"""Prompt chunks (max 500 chars); remove user_file, gallery, gallery_item, tenant.system_prompt.

Revision ID: 006
Revises: 005
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop file/gallery tables (order: gallery_item -> gallery, user_file)
    op.drop_table("gallery_item")
    op.drop_table("gallery")
    op.drop_table("user_file")

    op.drop_column("tenant", "system_prompt")

    op.create_table(
        "prompt_chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(500), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prompt_chunk_tenant_position", "prompt_chunk", ["tenant_id", "position"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_prompt_chunk_tenant_position", table_name="prompt_chunk")
    op.drop_table("prompt_chunk")

    op.add_column("tenant", sa.Column("system_prompt", sa.Text(), nullable=True))

    op.create_table(
        "user_file",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("minio_key", sa.String(512), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("trigger", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_file_tenant_user", "user_file", ["tenant_id", "user_id"], unique=False)

    op.create_table(
        "gallery",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gallery_tenant_user", "gallery", ["tenant_id", "user_id"], unique=False)

    op.create_table(
        "gallery_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gallery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["gallery_id"], ["gallery.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_file_id"], ["user_file.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
