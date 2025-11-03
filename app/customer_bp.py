import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Union
from urllib.parse import urljoin
import uuid

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.guest_access import access_is_active, pin_is_valid
from app.models import Customer, CustomerAuthToken, CustomerCredential, CustomerLoginEvent, Proof, ProofGuestAccess
from app.utils import customer_login_required, send_email_notification


CUSTOMER_SESSION_KEY = "customer_session_id"
CUSTOMER_CSRF_SESSION_KEY = "customer_csrf_token"
GUEST_PROOF_SESSION_KEY = "guest_proofs"
_customer_login_failures: dict[str, list[float]] = {}

customer_bp = Blueprint("customer", __name__, url_prefix="/customer")

DEFAULT_INVITE_EXPIRY_HOURS = 72


class InviteAlreadyPendingError(RuntimeError):
    """Raised when an invite is already active for a customer."""

    def __init__(self, token: CustomerAuthToken):
        super().__init__("An invitation is already pending for this customer.")
        self.token = token


def _feature_enabled() -> bool:
    return bool(current_app.config.get("CUSTOMER_LOGIN_ENABLED"))


def _require_feature() -> None:
    if not _feature_enabled():
        abort(404)


def _current_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


def _trim_login_attempts(ip: str) -> list[float]:
    window = int(current_app.config.get("LOGIN_ATTEMPT_WINDOW", 300))
    now = time.time()
    attempts = [ts for ts in _customer_login_failures.get(ip, []) if ts >= now - window]
    _customer_login_failures[ip] = attempts
    return attempts


def _record_failure(ip: str) -> None:
    attempts = _trim_login_attempts(ip)
    attempts.append(time.time())
    _customer_login_failures[ip] = attempts


def _is_locked(ip: str) -> bool:
    attempts = _trim_login_attempts(ip)
    max_attempts = int(current_app.config.get("LOGIN_MAX_ATTEMPTS", 5))
    return len(attempts) >= max_attempts


def _clear_failures(ip: str) -> None:
    _customer_login_failures.pop(ip, None)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ensure_customer_csrf_token() -> str:
    token = session.get(CUSTOMER_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_hex(32)
        session[CUSTOMER_CSRF_SESSION_KEY] = token
    return token


@customer_bp.route("/guest/<string:token>", methods=["GET", "POST"])
def guest_access(token: str):
    guest = ProofGuestAccess.query.filter_by(access_token=token).first()
    if not guest or not guest.proof:
        abort(404)

    error_message = None
    expired = False
    csrf_token = _ensure_customer_csrf_token()
    if not access_is_active(guest):
        expired = True
        if guest.revoked_at:
            error_message = "This guest link has been revoked. Please contact the team for a fresh invite."
        elif guest.expires_at and guest.expires_at < datetime.utcnow():
            error_message = "This guest link has expired. Ask your designer for a new link."
        else:
            error_message = "This guest link is no longer active."
    elif request.method == "POST":
        if request.form.get("csrf_token") != csrf_token:
            error_message = "Your session expired. Please reload this page and try again."
        else:
            pin = (request.form.get("pin") or "").strip()
            if not pin:
                error_message = "Please enter the PIN that was emailed to you."
            elif not pin_is_valid(guest, pin):
                error_message = "That PIN doesn't match our records. Double-check and try again."
            else:
                guest_ids = session.get(GUEST_PROOF_SESSION_KEY, [])
                if guest.proof.share_id not in guest_ids:
                    guest_ids.append(guest.proof.share_id)
                    session[GUEST_PROOF_SESSION_KEY] = guest_ids
                guest.accessed_at = datetime.utcnow()
                db.session.commit()
                session.modified = True
                next_url = request.args.get("next") or url_for("show_proof", job_id=guest.proof.share_id)
                return redirect(next_url)

    return render_template(
        "customer/guest_access.html",
        guest=guest,
        proof=guest.proof,
        error_message=error_message,
        expired=expired,
        customer_csrf_token=csrf_token,
    )


def issue_customer_token(
    customer: Customer,
    purpose: str,
    *,
    hours_valid: int,
    issued_by_user_id: Optional[Union[str, uuid.UUID]] = None,
) -> str:
    """Create a token for invite or password reset and return the raw token."""
    now = datetime.utcnow()
    expiry = now + timedelta(hours=hours_valid)

    issued_uuid = None
    if issued_by_user_id is not None:
        issued_uuid = issued_by_user_id if isinstance(issued_by_user_id, uuid.UUID) else uuid.UUID(str(issued_by_user_id))

    # Invalidate previous tokens of the same purpose
    (
        CustomerAuthToken.query.filter(
            CustomerAuthToken.customer_id == customer.id,
            CustomerAuthToken.purpose == purpose,
            CustomerAuthToken.consumed_at.is_(None),
        )
        .update({"consumed_at": now}, synchronize_session=False)
    )

    raw_token = secrets.token_urlsafe(32)
    token = CustomerAuthToken(
        customer_id=customer.id,
        token_hash=_hash_token(raw_token),
        purpose=purpose,
        expires_at=expiry,
        issued_by_user_id=issued_uuid,
    )
    db.session.add(token)
    db.session.flush()
    return raw_token


def _invite_tokens(customer: Customer) -> list[CustomerAuthToken]:
    return (
        CustomerAuthToken.query.filter(
            CustomerAuthToken.customer_id == customer.id,
            CustomerAuthToken.purpose == "invite",
        )
        .order_by(CustomerAuthToken.created_at.desc())
        .all()
    )


def active_invite_token(customer: Customer) -> Optional[CustomerAuthToken]:
    now = datetime.now(timezone.utc)
    for token in _invite_tokens(customer):
        expires_at = token.expires_at
        if token.consumed_at is not None:
            continue
        if expires_at is not None and expires_at < now:
            continue
        return token
    return None


def latest_invite_token(customer: Customer) -> Optional[CustomerAuthToken]:
    tokens = _invite_tokens(customer)
    return tokens[0] if tokens else None


def _invite_expiry_hours() -> int:
    configured = current_app.config.get("CUSTOMER_INVITE_EXPIRY_HOURS")
    if configured:
        try:
            return int(configured)
        except (TypeError, ValueError):
            pass
    return DEFAULT_INVITE_EXPIRY_HOURS


def build_invite_link(raw_token: str) -> str:
    base = current_app.config.get("PUBLIC_BASE_URL")
    if base:
        invite_path = url_for("customer.accept_invite", token=raw_token).lstrip("/")
        return urljoin(base.rstrip("/") + "/", invite_path)
    return url_for("customer.accept_invite", token=raw_token, _external=True)


def issue_customer_invite(
    customer: Customer,
    *,
    issued_by_user_id: Optional[object] = None,
    hours_valid: Optional[int] = None,
    allow_existing: bool = False,
    suppress_email: bool = False,
) -> tuple[str, CustomerAuthToken]:
    if not _feature_enabled():
        raise RuntimeError("Customer portal is not enabled.")

    if hours_valid is None:
        hours_valid = _invite_expiry_hours()

    issued_uuid: Optional[uuid.UUID] = None
    if issued_by_user_id is not None:
        if isinstance(issued_by_user_id, uuid.UUID):
            issued_uuid = issued_by_user_id
        else:
            issued_uuid = uuid.UUID(str(issued_by_user_id))

    existing = active_invite_token(customer)
    if existing and not allow_existing:
        raise InviteAlreadyPendingError(existing)

    raw_token = issue_customer_token(
        customer,
        "invite",
        hours_valid=hours_valid,
        issued_by_user_id=issued_uuid,
    )
    invite_link = build_invite_link(raw_token)

    if not suppress_email:
        send_customer_token_email(customer, "invite", invite_link)

    latest = latest_invite_token(customer)
    if not latest:
        raise RuntimeError("Failed to persist invite token.")
    return invite_link, latest


def describe_invite_status(customer: Customer) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    credential = customer.credential
    if credential and credential.is_active:
        detail = ""
        if credential.last_login_at:
            detail = f"Last login {credential.last_login_at.strftime('%Y-%m-%d %H:%M %Z')}"
        return {
            "state": "active",
            "label": "Account active",
            "detail": detail,
            "last_event": credential.last_login_at,
        }

    active_token = active_invite_token(customer)
    latest_token = latest_invite_token(customer)

    if active_token:
        expires = active_token.expires_at
        detail = ""
        if expires:
            detail = f"Expires {expires.strftime('%Y-%m-%d %H:%M %Z')}"
        return {
            "state": "pending",
            "label": "Invite pending",
            "detail": detail,
            "last_event": active_token.created_at,
        }

    if latest_token:
        if latest_token.consumed_at:
            detail = f"Accepted {latest_token.consumed_at.strftime('%Y-%m-%d %H:%M %Z')}"
            return {
                "state": "consumed",
                "label": "Invite accepted",
                "detail": detail,
                "last_event": latest_token.consumed_at,
            }
        if latest_token.expires_at and latest_token.expires_at < now:
            detail = f"Expired {latest_token.expires_at.strftime('%Y-%m-%d %H:%M %Z')}"
            return {
                "state": "expired",
                "label": "Invite expired",
                "detail": detail,
                "last_event": latest_token.expires_at,
            }

    return {"state": "none", "label": "No invite sent", "detail": "", "last_event": None}


def find_customer_token(raw_token: str, purpose: str) -> Optional[CustomerAuthToken]:
    token_hash = _hash_token(raw_token)
    now = datetime.utcnow()
    return (
        CustomerAuthToken.query.filter(
            CustomerAuthToken.token_hash == token_hash,
            CustomerAuthToken.purpose == purpose,
            CustomerAuthToken.consumed_at.is_(None),
            CustomerAuthToken.expires_at >= now,
        )
        .options(joinedload(CustomerAuthToken.customer).joinedload(Customer.credential))
        .first()
    )


def _validate_password(password: str) -> tuple[bool, str]:
    if len(password) < 12:
        return False, "Password must be at least 12 characters long."
    has_alpha = any(ch.isalpha() for ch in password)
    has_other = any(not ch.isalpha() for ch in password)
    if not (has_alpha and has_other):
        return False, "Password must include at least one letter and one number or symbol."
    return True, ""


def send_customer_token_email(customer: Customer, purpose: str, link: str) -> None:
    branding = g.get("branding") or {}
    company_name = branding.get("company_name") or "Proof Approval System"
    if purpose == "invite":
        subject = f"{company_name}: Finish setting up your account"
        body = (
            f"Hello {customer.name},\n\n"
            "You're invited to access your proofs securely. Click the link below to create a password:\n"
            f"{link}\n\n"
            "If you did not expect this email, please ignore it."
        )
    else:
        subject = f"{company_name}: Reset your customer portal password"
        body = (
            f"Hello {customer.name},\n\n"
            "We received a request to reset your password. Use the link below to choose a new password:\n"
            f"{link}\n\n"
            "If you did not request this change, you can safely ignore this message."
        )

    send_email_notification(
        subject,
        body,
        customer.email,
        fallback_sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
        fallback_reply_to=current_app.config.get("MAIL_DEFAULT_REPLY_TO"),
        async_send=True,
    )


@customer_bp.route("/login", methods=["GET", "POST"])
def login():
    _require_feature()
    csrf_token = _ensure_customer_csrf_token()

    if g.get("current_customer"):
        return redirect(url_for("customer.dashboard"))

    if request.method == "POST":
        if request.form.get("csrf_token") != csrf_token:
            flash("Your session expired. Please try again.", "error")
            return render_template("customer/login.html"), 400

        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()
        ip = _current_ip()

        if not email or not password:
            flash("❌ Email and password are required.", "error")
            return render_template("customer/login.html")

        if _is_locked(ip):
            flash("❌ Too many attempts. Please try again in a few minutes.", "error")
            return render_template("customer/login.html"), 429

        customer = (
            Customer.query.filter(func.lower(Customer.email) == email)
            .options(joinedload(Customer.credential))
            .first()
        )
        credential = customer.credential if customer else None

        if not customer or not credential or not credential.is_active:
            _record_failure(ip)
            flash("❌ Invalid credentials.", "error")
            return render_template("customer/login.html")

        if not check_password_hash(credential.password_hash, password):
            _record_failure(ip)
            db.session.add(
                CustomerLoginEvent(
                    customer_id=customer.id,
                    ip_address=ip,
                    user_agent=(request.headers.get("User-Agent") or "")[:512],
                    successful=False,
                )
            )
            db.session.commit()
            flash("❌ Invalid credentials.", "error")
            return render_template("customer/login.html")

        session[CUSTOMER_SESSION_KEY] = str(customer.id)
        session[CUSTOMER_CSRF_SESSION_KEY] = secrets.token_hex(32)
        credential.last_login_at = datetime.utcnow()
        db.session.add(
            CustomerLoginEvent(
                customer_id=customer.id,
                ip_address=ip,
                user_agent=(request.headers.get("User-Agent") or "")[:512],
                successful=True,
            )
        )
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("⚠️ Unable to complete login right now. Please try again.", "warning")
            return render_template("customer/login.html")

        _clear_failures(ip)
        flash("✅ Signed in successfully.", "success")

        next_url = request.args.get("next")
        return redirect(next_url or url_for("customer.dashboard"))

    _ensure_customer_csrf_token()
    return render_template("customer/login.html")


@customer_bp.route("/logout")
def logout():
    _require_feature()
    session.pop(CUSTOMER_SESSION_KEY, None)
    session.pop(CUSTOMER_CSRF_SESSION_KEY, None)
    flash("You have been signed out.", "info")
    return redirect(url_for("customer.login"))


@customer_bp.route("/dashboard")
@customer_login_required
def dashboard():
    _require_feature()
    customer: Customer = g.current_customer  # type: ignore[assignment]
    proofs = (
        Proof.query.filter(Proof.customer_id == customer.id)
        .options(
            joinedload(Proof.designer),
            joinedload(Proof.versions),
            joinedload(Proof.decisions),
        )
        .order_by(Proof.updated_at.desc(), Proof.created_at.desc())
        .all()
    )
    return render_template("customer/dashboard.html", proofs=proofs, customer=customer)


@customer_bp.route("/reset", methods=["GET", "POST"])
def reset_request():
    _require_feature()
    csrf_token = _ensure_customer_csrf_token()
    if request.method == "POST":
        if request.form.get("csrf_token") != csrf_token:
            flash("Your session expired. Please try again.", "error")
            return render_template("customer/reset_request.html"), 400

        email = (request.form.get("email") or "").strip().lower()
        customer = (
            Customer.query.filter(func.lower(Customer.email) == email)
            .options(joinedload(Customer.credential))
            .first()
        )

        # Always respond with success-style message to avoid account enumeration.
        flash("If the email is registered, a reset link will arrive shortly.", "info")
        if not customer or not customer.credential or not customer.credential.is_active:
            return redirect(url_for("customer.login"))

        try:
            raw_token = issue_customer_token(customer, "reset", hours_valid=24)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            return redirect(url_for("customer.login"))

        reset_link = url_for("customer.reset", token=raw_token, _external=True)
        send_customer_token_email(customer, "reset", reset_link)
        return redirect(url_for("customer.login"))

    return render_template("customer/reset_request.html")


@customer_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token: str):
    _require_feature()
    token_record = find_customer_token(token, "reset")
    if not token_record:
        flash("The reset link is invalid or has expired.", "error")
        return redirect(url_for("customer.login"))

    csrf_token = _ensure_customer_csrf_token()
    if request.method == "POST":
        if request.form.get("csrf_token") != csrf_token:
            flash("Your session expired. Please submit the form again.", "error")
            return render_template("customer/reset.html", customer=token_record.customer), 400

        password = (request.form.get("password") or "").strip()
        confirm = (request.form.get("confirm_password") or "").strip()

        is_valid, error_message = _validate_password(password)
        if not is_valid:
            flash(error_message, "error")
            return render_template("customer/reset.html", customer=token_record.customer)
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("customer/reset.html", customer=token_record.customer)

        credential = token_record.customer.credential
        if not credential:
            credential = CustomerCredential(
                customer_id=token_record.customer.id,
                password_hash=generate_password_hash(password),
                is_active=True,
            )
            db.session.add(credential)
        else:
            credential.password_hash = generate_password_hash(password)
            credential.is_active = True

        credential.last_login_at = None
        token_record.consumed_at = datetime.utcnow()
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("We could not update your password. Please try again.", "error")
            return render_template("customer/reset.html", customer=token_record.customer)

        flash("✅ Password updated. You can sign in now.", "success")
        return redirect(url_for("customer.login"))

    return render_template("customer/reset.html", customer=token_record.customer)


@customer_bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invite(token: str):
    _require_feature()
    token_record = find_customer_token(token, "invite")
    if not token_record:
        flash("Invitation is invalid or expired.", "error")
        return redirect(url_for("customer.login"))

    customer = token_record.customer
    csrf_token = _ensure_customer_csrf_token()
    if request.method == "POST":
        if request.form.get("csrf_token") != csrf_token:
            flash("Your session expired. Please submit the form again.", "error")
            return render_template("customer/invite.html", customer=customer), 400

        password = (request.form.get("password") or "").strip()
        confirm = (request.form.get("confirm_password") or "").strip()

        is_valid, error_message = _validate_password(password)
        if not is_valid:
            flash(error_message, "error")
            return render_template("customer/invite.html", customer=customer)
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("customer/invite.html", customer=customer)

        credential = customer.credential
        if not credential:
            credential = CustomerCredential(
                customer_id=customer.id,
                password_hash=generate_password_hash(password),
                is_active=True,
            )
            db.session.add(credential)
        else:
            credential.password_hash = generate_password_hash(password)
            credential.is_active = True

        credential.last_login_at = None
        token_record.consumed_at = datetime.utcnow()

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("We could not activate your account. Please try again.", "error")
            return render_template("customer/invite.html", customer=customer)

        flash("✅ Account ready. Please sign in with your new password.", "success")
        return redirect(url_for("customer.login"))

    return render_template("customer/invite.html", customer=customer)


@customer_bp.route("/proof/<share_id>")
@customer_login_required
def view_proof(share_id: str):
    _require_feature()
    customer: Customer = g.current_customer  # type: ignore[assignment]
    proof = (
        Proof.query.filter(
            Proof.share_id == share_id,
            Proof.customer_id == customer.id,
        )
        .options(joinedload(Proof.versions), joinedload(Proof.designer), joinedload(Proof.decisions))
        .first()
    )
    if not proof:
        abort(404)
    # For now reuse legacy client view; Stage 5 will introduce dedicated template.
    return redirect(url_for("show_proof", job_id=proof.share_id))
