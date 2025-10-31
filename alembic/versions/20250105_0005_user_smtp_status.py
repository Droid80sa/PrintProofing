"""Add SMTP status tracking columns to users

Revision ID: 20250105_0005
Revises: 20250105_0004
Create Date: 2025-01-05 01:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250105_0005"
down_revision = "20250105_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("smtp_last_test_status", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("smtp_last_test_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("smtp_last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "smtp_last_error")
    op.drop_column("users", "smtp_last_test_at")
    op.drop_column("users", "smtp_last_test_status")
