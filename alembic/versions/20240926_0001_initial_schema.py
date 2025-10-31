"""initial schema for proofs app"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20240926_0001"
down_revision = None
branch_labels = None
depends_on = None


def _uuid_type(bind):
    if bind and bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(length=36)


def upgrade() -> None:
    bind = op.get_bind()
    uuid_type = _uuid_type(bind)

    op.create_table(
        "users",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False, server_default="designer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "designers",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("reply_to_email", sa.String(length=255)),
        sa.Column("phone_number", sa.String(length=50)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_designers_email", "designers", ["email"], unique=True)

    op.create_table(
        "proofs",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("share_id", sa.String(length=32), nullable=False),
        sa.Column("job_name", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("designer_id", uuid_type, sa.ForeignKey("designers.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_proofs_share_id", "proofs", ["share_id"], unique=True)
    op.create_index("ix_proofs_designer_id", "proofs", ["designer_id"], unique=False)

    op.create_table(
        "proof_versions",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("proof_id", uuid_type, sa.ForeignKey("proofs.id"), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128)),
        sa.Column("file_size", sa.Integer()),
        sa.Column("uploaded_by_id", uuid_type, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_proof_versions_proof_id", "proof_versions", ["proof_id"], unique=False)

    op.create_table(
        "decisions",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("proof_id", uuid_type, sa.ForeignKey("proofs.id"), nullable=False),
        sa.Column("proof_version_id", uuid_type, sa.ForeignKey("proof_versions.id")),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("approver_name", sa.String(length=255)),
        sa.Column("client_comment", sa.Text()),
        sa.Column("client_email", sa.String(length=255)),
        sa.Column("client_ip", sa.String(length=45)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_decisions_proof_id", "decisions", ["proof_id"], unique=False)
    op.create_index("ix_decisions_proof_version_id", "decisions", ["proof_version_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_decisions_proof_version_id", table_name="decisions")
    op.drop_index("ix_decisions_proof_id", table_name="decisions")
    op.drop_table("decisions")

    op.drop_index("ix_proof_versions_proof_id", table_name="proof_versions")
    op.drop_table("proof_versions")

    op.drop_index("ix_proofs_designer_id", table_name="proofs")
    op.drop_index("ix_proofs_share_id", table_name="proofs")
    op.drop_table("proofs")

    op.drop_index("ix_designers_email", table_name="designers")
    op.drop_table("designers")

    op.drop_table("users")
