"""add smtp settings to users"""

from alembic import op
import sqlalchemy as sa


revision = "20241028_0002"
down_revision = "20240926_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("smtp_host", sa.String(length=255)))
    op.add_column("users", sa.Column("smtp_port", sa.Integer()))
    op.add_column("users", sa.Column("smtp_username", sa.String(length=255)))
    op.add_column("users", sa.Column("smtp_password", sa.String(length=255)))
    op.add_column("users", sa.Column("smtp_use_tls", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("users", sa.Column("smtp_use_ssl", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("users", sa.Column("smtp_sender", sa.String(length=255)))
    op.add_column("users", sa.Column("smtp_reply_to", sa.String(length=255)))


def downgrade() -> None:
    op.drop_column("users", "smtp_reply_to")
    op.drop_column("users", "smtp_sender")
    op.drop_column("users", "smtp_use_ssl")
    op.drop_column("users", "smtp_use_tls")
    op.drop_column("users", "smtp_password")
    op.drop_column("users", "smtp_username")
    op.drop_column("users", "smtp_port")
    op.drop_column("users", "smtp_host")
