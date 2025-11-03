"""Add customer notifications table

Revision ID: 20250105_0004
Revises: 20250105_0003
Create Date: 2025-01-05 00:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20250105_0004"
down_revision = "20250105_0003"
branch_labels = None
depends_on = None


def _uuid_type():
    bind = op.get_bind()
    if bind and bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(length=36)


def upgrade() -> None:
    uuid_type = _uuid_type()

    op.create_table(
        "customer_notifications",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("proof_id", uuid_type, sa.ForeignKey("proofs.id"), nullable=False),
        sa.Column("proof_version_id", uuid_type, sa.ForeignKey("proof_versions.id"), nullable=True),
        sa.Column("customer_id", uuid_type, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("sent_by_user_id", uuid_type, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("smtp_user_id", uuid_type, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("sender_email", sa.String(length=255), nullable=True),
        sa.Column("reply_to_email", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_customer_notifications_proof_id", "customer_notifications", ["proof_id"], unique=False)
    op.create_index("ix_customer_notifications_proof_version_id", "customer_notifications", ["proof_version_id"], unique=False)
    op.create_index("ix_customer_notifications_customer_id", "customer_notifications", ["customer_id"], unique=False)
    op.create_index("ix_customer_notifications_sent_by_user_id", "customer_notifications", ["sent_by_user_id"], unique=False)
    op.create_index("ix_customer_notifications_smtp_user_id", "customer_notifications", ["smtp_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_customer_notifications_smtp_user_id", table_name="customer_notifications")
    op.drop_index("ix_customer_notifications_sent_by_user_id", table_name="customer_notifications")
    op.drop_index("ix_customer_notifications_customer_id", table_name="customer_notifications")
    op.drop_index("ix_customer_notifications_proof_version_id", table_name="customer_notifications")
    op.drop_index("ix_customer_notifications_proof_id", table_name="customer_notifications")
    op.drop_table("customer_notifications")
