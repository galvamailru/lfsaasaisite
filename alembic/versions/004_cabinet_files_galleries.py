"""Add role to tenant_user; add user_file, gallery, gallery_item for cabinet.

Revision ID: 004
Revises: 003
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenant_user", sa.Column("role", sa.String(32), nullable=False, server_default="admin"))

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


def downgrade() -> None:
    op.drop_table("gallery_item")
    op.drop_index("ix_gallery_tenant_user", table_name="gallery")
    op.drop_table("gallery")
    op.drop_index("ix_user_file_tenant_user", table_name="user_file")
    op.drop_table("user_file")
    op.drop_column("tenant_user", "role")
