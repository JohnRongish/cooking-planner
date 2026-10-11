"""initial schema

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingredient",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("store_section", sa.String(), nullable=False, server_default=""),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_index("ix_ingredient_name", "ingredient", ["name"])
    op.create_table(
        "recipe",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("tags", sa.String(), nullable=False, server_default=""),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_index("ix_recipe_name", "recipe", ["name"])
    op.create_table(
        "kitchen",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_index("ix_kitchen_name", "kitchen", ["name"])
    op.create_table(
        "event",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("start_date", sa.String(), nullable=False, server_default=""),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_index("ix_event_name", "event", ["name"])


def downgrade() -> None:
    for t in ("event", "kitchen", "recipe", "ingredient"):
        op.drop_table(t)
