"""Add demo tenant for development.

Revision ID: 002
Revises: 001
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO tenant (id, slug, name, created_at)
            VALUES (gen_random_uuid(), 'demo', 'Demo Tenant', now())
            ON CONFLICT (slug) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM tenant WHERE slug = 'demo'"))
