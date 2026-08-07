"""model registry config + run model_override

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "model_providers",
        sa.Column("config", pg.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "runs",
        sa.Column("model_override", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runs", "model_override")
    op.drop_column("model_providers", "config")
