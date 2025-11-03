"""Add proof guest access table

Revision ID: 20250110_0007
Revises: 20250110_0006
Create Date: 2025-01-10 01:15:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20250110_0007"
down_revision = "20250110_0006"
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
        "proof_guest_accesses",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("proof_id", uuid_type, sa.ForeignKey("proofs.id"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("access_token", sa.String(length=128), nullable=False, unique=True),
        sa.Column("pin_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        "ix_proof_guest_accesses_proof_id",
        "proof_guest_accesses",
        ["proof_id"],
        unique=False,
    )
def downgrade() -> None:
    op.drop_index(
        "ix_proof_guest_accesses_proof_id",
        table_name="proof_guest_accesses",
    )
    op.drop_table("proof_guest_accesses")
