"""Add ticket field reports table

Revision ID: a1b2c3d4e5f6
Revises: 699868a51b34
Create Date: 2026-06-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "699868a51b34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ticket_field_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("field_path", sa.String(length=256), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("sku_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ticket_field_reports_ticket_id"),
        "ticket_field_reports",
        ["ticket_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ticket_field_reports_ticket_id"), table_name="ticket_field_reports")
    op.drop_table("ticket_field_reports")
