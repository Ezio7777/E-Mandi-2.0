"""order stock commit / restock markers

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14 01:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("stock_committed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("restocked_at", sa.DateTime(timezone=True), nullable=True))
    # Backfill: orders that are past payment had their stock committed. Refunded ones are conservatively left
    # un-restocked (their refund already completed before this feature existed).
    op.execute(
        "UPDATE orders SET stock_committed_at = updated_at, restocked_at = CASE WHEN status = 'REFUNDED' THEN updated_at END "
        "WHERE status IN ('PAID','CONFIRMED','IN_FULFILLMENT','COMPLETED','DISPUTED','REFUNDED')"
    )


def downgrade() -> None:
    op.drop_column("orders", "restocked_at")
    op.drop_column("orders", "stock_committed_at")
