"""Gallery image: store binary in DB instead of url.

Revision ID: 011
Revises: 010
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Схема gallery создаётся микросервисом gallery; таблица image могла быть с полем url.
    # Меняем на data + content_type. Старые строки удаляем (миграция не умеет скачивать по url).
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS gallery"))
    conn = op.get_bind()
    r = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'gallery' AND table_name = 'image'"
    ))
    columns = [row[0] for row in r]
    if not columns:
        return
    if "url" in columns:
        conn.execute(sa.text("DELETE FROM gallery.image"))
        op.drop_column("image", "url", schema="gallery")
    if "data" not in columns:
        op.add_column("image", sa.Column("data", sa.LargeBinary(), nullable=False), schema="gallery")
    if "content_type" not in columns:
        op.add_column("image", sa.Column("content_type", sa.String(64), nullable=False), schema="gallery")


def downgrade() -> None:
    op.add_column("image", sa.Column("url", sa.String(2048), nullable=True), schema="gallery")
    op.drop_column("image", "data", schema="gallery")
    op.drop_column("image", "content_type", schema="gallery")
