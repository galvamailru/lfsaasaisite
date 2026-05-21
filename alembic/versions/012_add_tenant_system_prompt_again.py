"""Add system_prompt back to tenant (user chatbot prompt).

Revision ID: 012
Revises: 011
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 006 миграция когда-то добавляла system_prompt, а потом удаляла её вместе со старой моделью промпта.
    # Мы снова вводим колонку system_prompt как базовый системный промпт пользовательского бота.
    op.add_column("tenant", sa.Column("system_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant", "system_prompt")

