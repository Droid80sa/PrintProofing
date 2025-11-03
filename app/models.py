import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import UUID

try:
    from .extensions import db
except ImportError:  # Allows importing without package context
    from extensions import db  # type: ignore


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(db.Model, TimestampMixin):
    __tablename__ = "users"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default="designer")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    smtp_host = db.Column(db.String(255))
    smtp_port = db.Column(db.Integer)
    smtp_username = db.Column(db.String(255))
    smtp_password = db.Column(db.String(255))
    smtp_use_tls = db.Column(db.Boolean, default=False)
    smtp_use_ssl = db.Column(db.Boolean, default=False)
    smtp_sender = db.Column(db.String(255))
    smtp_reply_to = db.Column(db.String(255))
    smtp_last_test_status = db.Column(db.String(20))
    smtp_last_test_at = db.Column(db.DateTime(timezone=True))
    smtp_last_error = db.Column(db.Text)

    designer_profile = db.relationship("Designer", back_populates="user", uselist=False, cascade="all, delete-orphan")
    uploads = db.relationship("ProofVersion", back_populates="uploaded_by")
    customer_notifications = db.relationship(
        "CustomerNotification",
        back_populates="sent_by",
        foreign_keys="CustomerNotification.sent_by_user_id",
    )


class Designer(db.Model, TimestampMixin):
    __tablename__ = "designers"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False, unique=True)
    display_name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    reply_to_email = db.Column(db.String(255))
    phone_number = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    user = db.relationship("User", back_populates="designer_profile")
    proofs = db.relationship("Proof", back_populates="designer")


class Customer(db.Model, TimestampMixin):
    __tablename__ = "customers"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(255), nullable=False)
    company_name = db.Column(db.String(255))
    email = db.Column(db.String(255), unique=True, nullable=False)

    proofs = db.relationship("Proof", back_populates="customer")
    credential = db.relationship(
        "CustomerCredential",
        back_populates="customer",
        uselist=False,
        cascade="all, delete-orphan",
    )
    auth_tokens = db.relationship(
        "CustomerAuthToken",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    login_events = db.relationship(
        "CustomerLoginEvent",
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="CustomerLoginEvent.occurred_at.desc()",
    )
    notifications = db.relationship(
        "CustomerNotification",
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="CustomerNotification.created_at.desc()",
    )


class Proof(db.Model, TimestampMixin):
    __tablename__ = "proofs"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    share_id = db.Column(db.String(32), nullable=False, unique=True, index=True)
    job_name = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text)
    status = db.Column(db.String(50), nullable=False, default="pending")
    designer_id = db.Column(UUID(as_uuid=True), db.ForeignKey("designers.id"), nullable=True)
    customer_id = db.Column(UUID(as_uuid=True), db.ForeignKey("customers.id"), nullable=True)

    designer = db.relationship("Designer", back_populates="proofs")
    customer = db.relationship("Customer", back_populates="proofs")
    versions = db.relationship(
        "ProofVersion",
        back_populates="proof",
        cascade="all, delete-orphan",
        order_by="ProofVersion.created_at",
    )
    decisions = db.relationship(
        "Decision",
        back_populates="proof",
        order_by="Decision.created_at",
    )
    notifications = db.relationship(
        "CustomerNotification",
        back_populates="proof",
        cascade="all, delete-orphan",
        order_by="CustomerNotification.created_at",
    )
    guest_accesses = db.relationship(
        "ProofGuestAccess",
        back_populates="proof",
        cascade="all, delete-orphan",
        order_by="ProofGuestAccess.created_at",
    )


class ProofVersion(db.Model, TimestampMixin):
    __tablename__ = "proof_versions"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proof_id = db.Column(UUID(as_uuid=True), db.ForeignKey("proofs.id"), nullable=False, index=True)
    storage_path = db.Column(db.String(1024), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(128))
    file_size = db.Column(db.Integer)
    uploaded_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)

    proof = db.relationship("Proof", back_populates="versions")
    uploaded_by = db.relationship("User", back_populates="uploads")
    decisions = db.relationship("Decision", back_populates="proof_version", cascade="all, delete-orphan")
    notifications = db.relationship(
        "CustomerNotification",
        back_populates="proof_version",
        cascade="all, delete-orphan",
    )


class Decision(db.Model, TimestampMixin):
    __tablename__ = "decisions"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proof_id = db.Column(UUID(as_uuid=True), db.ForeignKey("proofs.id"), nullable=False, index=True)
    proof_version_id = db.Column(UUID(as_uuid=True), db.ForeignKey("proof_versions.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False)
    approver_name = db.Column(db.String(255))
    client_comment = db.Column(db.Text)
    client_email = db.Column(db.String(255))
    client_ip = db.Column(db.String(45))

    proof = db.relationship("Proof", back_populates="decisions")
    proof_version = db.relationship("ProofVersion", back_populates="decisions")


class CustomerCredential(db.Model, TimestampMixin):
    __tablename__ = "customer_credentials"

    customer_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("customers.id"), primary_key=True, nullable=False
    )
    password_hash = db.Column(db.String(255), nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    mfa_secret = db.Column(db.String(255))

    customer = db.relationship("Customer", back_populates="credential")


class CustomerAuthToken(db.Model, TimestampMixin):
    __tablename__ = "customer_auth_tokens"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("customers.id"), nullable=False, index=True
    )
    token_hash = db.Column(db.String(255), nullable=False)
    purpose = db.Column(db.String(20), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    consumed_at = db.Column(db.DateTime(timezone=True))
    issued_by_user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"))

    customer = db.relationship("Customer", back_populates="auth_tokens")
    issued_by = db.relationship("User")


class CustomerLoginEvent(db.Model):
    __tablename__ = "customer_login_events"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("customers.id"), nullable=False, index=True
    )
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(512))
    successful = db.Column(db.Boolean, nullable=False, default=True)
    occurred_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    customer = db.relationship("Customer", back_populates="login_events")


class CustomerNotification(db.Model, TimestampMixin):
    __tablename__ = "customer_notifications"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proof_id = db.Column(UUID(as_uuid=True), db.ForeignKey("proofs.id"), nullable=False, index=True)
    proof_version_id = db.Column(UUID(as_uuid=True), db.ForeignKey("proof_versions.id"), nullable=True, index=True)
    customer_id = db.Column(UUID(as_uuid=True), db.ForeignKey("customers.id"), nullable=False, index=True)
    sent_by_user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True, index=True)
    smtp_user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True, index=True)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    recipient_email = db.Column(db.String(255), nullable=False)
    sender_email = db.Column(db.String(255))
    reply_to_email = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default="queued")
    error_message = db.Column(db.Text)
    queued_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at = db.Column(db.DateTime(timezone=True))

    proof = db.relationship("Proof", back_populates="notifications")
    proof_version = db.relationship("ProofVersion", back_populates="notifications")
    customer = db.relationship("Customer", back_populates="notifications")
    sent_by = db.relationship("User", back_populates="customer_notifications", foreign_keys=[sent_by_user_id])
    smtp_user = db.relationship("User", foreign_keys=[smtp_user_id])


class ProofGuestAccess(db.Model, TimestampMixin):
    __tablename__ = "proof_guest_accesses"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proof_id = db.Column(UUID(as_uuid=True), db.ForeignKey("proofs.id"), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255))
    access_token = db.Column(db.String(128), nullable=False, unique=True)
    pin_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True))
    accessed_at = db.Column(db.DateTime(timezone=True))
    revoked_at = db.Column(db.DateTime(timezone=True))

    proof = db.relationship("Proof", back_populates="guest_accesses")

    def is_active(self) -> bool:
        if self.revoked_at:
            return False
        now = datetime.now(timezone.utc)
        expires_at = self.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at and expires_at < now:
            return False
        return True


class NotificationTemplate(db.Model, TimestampMixin):
    __tablename__ = "notification_templates"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = db.Column(db.String(100), unique=True, nullable=False)
    subject_template = db.Column(db.String(255), nullable=False)
    body_template = db.Column(db.Text, nullable=False)
    updated_by_user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)

    updated_by = db.relationship("User")
