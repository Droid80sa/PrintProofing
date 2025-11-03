"""Add notification templates table

Revision ID: 20250110_0006
Revises: 20250105_0005
Create Date: 2025-01-10 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20250110_0006"
down_revision = "20250105_0005"
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
        "notification_templates",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False, unique=True),
        sa.Column("subject_template", sa.String(length=255), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("updated_by_user_id", uuid_type, sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_notification_templates_updated_by_user_id",
        "notification_templates",
        ["updated_by_user_id"],
        unique=False,
    )

def downgrade() -> None:
    op.drop_index(
        "ix_notification_templates_updated_by_user_id",
        table_name="notification_templates",
    )
    op.drop_table("notification_templates")
