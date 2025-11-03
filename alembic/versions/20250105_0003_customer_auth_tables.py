"""Add tables for customer authentication and auditing

Revision ID: 20250105_0003
Revises: a7942eaaaca5
Create Date: 2025-01-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250105_0003"
down_revision = "a7942eaaaca5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_credentials",
        sa.Column("customer_id", sa.UUID(), sa.ForeignKey("customers.id"), primary_key=True, nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mfa_secret", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "customer_auth_tokens",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("customer_id", sa.UUID(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by_user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index(
        "ix_customer_auth_tokens_customer_id",
        "customer_auth_tokens",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_customer_auth_tokens_purpose_active",
        "customer_auth_tokens",
        ["customer_id", "purpose"],
        unique=False,
    )

    op.create_table(
        "customer_login_events",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("customer_id", sa.UUID(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("successful", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index(
        "ix_customer_login_events_customer_id",
        "customer_login_events",
        ["customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_customer_login_events_customer_id", table_name="customer_login_events")
    op.drop_table("customer_login_events")

    op.drop_index("ix_customer_auth_tokens_purpose_active", table_name="customer_auth_tokens")
    op.drop_index("ix_customer_auth_tokens_customer_id", table_name="customer_auth_tokens")
    op.drop_table("customer_auth_tokens")

    op.drop_table("customer_credentials")
