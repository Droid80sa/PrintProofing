import os
import uuid
import json
import logging
import mimetypes
import secrets
import smtplib
import ssl
import sys
import time
import csv
import re
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import urljoin
from typing import Optional

import click
from dotenv import load_dotenv
from flask import (
    Flask,
    request,
    render_template,
    url_for,
    send_from_directory,
    Response,
    redirect,
    flash,
    session,
    g,
    abort,
    current_app,
)
from flask_mail import Mail
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from app.admin_bp import admin_bp
from app.customer_bp import (
    customer_bp,
    CUSTOMER_SESSION_KEY,
    GUEST_PROOF_SESSION_KEY,
    InviteAlreadyPendingError,
    describe_invite_status,
    issue_customer_invite,
    issue_customer_token,
    send_customer_token_email,
)
from app.customer_notifications import (
    queue_customer_notification,
    default_subject_template,
    default_body_template,
    render_notification_content,
)
from app.email_queue import EMAIL_QUEUE  # noqa: F401 imported for side effects
from app.extensions import db
from app.guest_access import build_guest_access, access_is_active
from app.models import Customer, Decision, Designer, Proof, ProofVersion, User
from app.storage import LocalStorage, S3Storage, StorageError
from app.utils import login_required, send_email_notification


def _as_bool(value: Optional[str], *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024 * 1024  # 1GB
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
PROOF_DIR = os.path.join(BASE_DIR, "proofs")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ADMIN_DIR = os.path.join(BASE_DIR, "admin")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(PROOF_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "development-secret"),
    SQLALCHEMY_DATABASE_URI=os.getenv(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'app.db')}"
    ),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAIL_SERVER=os.getenv("MAIL_SERVER", "localhost"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", "25")),
    MAIL_USE_TLS=_as_bool(os.getenv("MAIL_USE_TLS")),
    MAIL_USE_SSL=_as_bool(os.getenv("MAIL_USE_SSL")),
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER"),
    MAIL_DEFAULT_REPLY_TO=os.getenv("MAIL_DEFAULT_REPLY_TO"),
    BASE_DIR=BASE_DIR,
    ADMIN_DIR=ADMIN_DIR,
    UPLOAD_DIR=UPLOAD_DIR,
    LOG_DIR=LOG_DIR,
    PROOF_DIR=PROOF_DIR,
)

BASE_URL = os.getenv("PUBLIC_BASE_URL")
FILE_BASE_URL = os.getenv("FILE_BASE_URL")
FILE_STORAGE_ROOT = os.path.abspath(os.getenv("FILE_STORAGE_ROOT", PROOF_DIR))
FILE_STORAGE_BACKEND = os.getenv("FILE_STORAGE_BACKEND", "local").strip().lower()

mail = Mail(app)
db.init_app(app)

DEFAULT_REPLY_TO = os.getenv("MAIL_DEFAULT_REPLY_TO")
SESSION_USER_ID = "current_user_id"
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_ATTEMPT_WINDOW = int(os.getenv("LOGIN_ATTEMPT_WINDOW", "300"))
CUSTOMER_LOGIN_ENABLED = _as_bool(os.getenv("CUSTOMER_LOGIN_ENABLED", "0"))
LEGACY_PUBLIC_LINKS_ENABLED = _as_bool(os.getenv("LEGACY_PUBLIC_LINKS_ENABLED", "1"))
CUSTOMER_INVITE_EXPIRY_HOURS = int(os.getenv("CUSTOMER_INVITE_EXPIRY_HOURS", "72"))
_login_failures: dict[str, list[float]] = {}

app.config["LOGIN_MAX_ATTEMPTS"] = LOGIN_MAX_ATTEMPTS
app.config["LOGIN_ATTEMPT_WINDOW"] = LOGIN_ATTEMPT_WINDOW
app.config["CUSTOMER_LOGIN_ENABLED"] = CUSTOMER_LOGIN_ENABLED
app.config["LEGACY_PUBLIC_LINKS_ENABLED"] = LEGACY_PUBLIC_LINKS_ENABLED
app.config["CUSTOMER_INVITE_EXPIRY_HOURS"] = CUSTOMER_INVITE_EXPIRY_HOURS


def _build_storage_backend():
    if FILE_STORAGE_BACKEND == "s3":
        try:
            return S3Storage(
                bucket=os.getenv("AWS_S3_BUCKET", ""),
                base_path=os.getenv("AWS_S3_PREFIX"),
                region_name=os.getenv("AWS_S3_REGION"),
                endpoint_url=os.getenv("AWS_S3_ENDPOINT_URL"),
                public_base_url=FILE_BASE_URL or BASE_URL,
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            )
        except StorageError as exc:
            logging.getLogger(__name__).warning(
                "Failed to initialise S3 storage (%s); falling back to local storage.",
                exc,
            )
    try:
        return LocalStorage(FILE_STORAGE_ROOT, public_base_url=FILE_BASE_URL or BASE_URL)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Unable to use FILE_STORAGE_ROOT '%s': %s. Falling back to app storage directory.",
            FILE_STORAGE_ROOT,
            exc,
        )
        return LocalStorage(PROOF_DIR, public_base_url=FILE_BASE_URL or BASE_URL)


storage_backend = _build_storage_backend()

app.register_blueprint(admin_bp)
app.register_blueprint(customer_bp)

DEFAULT_BRANDING = {
    "company_name": "Proof Approval System",
    "primary_color": "#000000",
    "background_color": "#ffffff",
    "approve_button_color": "#28a745",
    "reject_button_color": "#dc3545",
    "general_button_color": "#343a40",
    "font_family": "Roboto, sans-serif",
    "email_footer": "",
}


def load_branding() -> dict:
    branding = DEFAULT_BRANDING.copy()
    settings_path = os.path.join(ADMIN_DIR, "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                for key, value in data.items():
                    if key in branding and isinstance(value, str):
                        branding[key] = value.strip() or branding[key]
        except (OSError, json.JSONDecodeError) as exc:
            logging.getLogger(__name__).warning(
                "Unable to load branding settings: %s", exc
            )
    logo_path = os.path.join(UPLOAD_DIR, "logo.png")
    branding["logo_url"] = "/static/uploads/logo.png" if os.path.exists(logo_path) else None
    return branding


def _trim_login_attempts(ip: str) -> list[float]:
    now = time.time()
    cutoff = now - LOGIN_ATTEMPT_WINDOW
    attempts = [ts for ts in _login_failures.get(ip, []) if ts >= cutoff]
    _login_failures[ip] = attempts
    return attempts


def _record_login_failure(ip: str) -> None:
    attempts = _trim_login_attempts(ip)
    attempts.append(time.time())
    _login_failures[ip] = attempts


def _is_login_locked(ip: str) -> bool:
    attempts = _trim_login_attempts(ip)
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def _clear_login_failures(ip: str) -> None:
    _login_failures.pop(ip, None)


def _current_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


@app.before_request
def load_request_context() -> None:
    g.branding = load_branding()
    g.current_user = None
    g.current_customer = None

    user_id = session.get(SESSION_USER_ID)
    if user_id:
        try:
            user_uuid = uuid.UUID(user_id)
        except (ValueError, TypeError):
            session.pop(SESSION_USER_ID, None)
        else:
            user = db.session.get(User, user_uuid)
            if user and user.is_active:
                g.current_user = user
            else:
                session.pop(SESSION_USER_ID, None)
    customer_session_id = session.get(CUSTOMER_SESSION_KEY)
    if customer_session_id:
        try:
            customer_uuid = uuid.UUID(customer_session_id)
        except (ValueError, TypeError):
            session.pop(CUSTOMER_SESSION_KEY, None)
        else:
            customer = db.session.get(Customer, customer_uuid)
            credential = customer.credential if customer else None
            if customer and credential and credential.is_active:
                g.current_customer = customer
            else:
                session.pop(CUSTOMER_SESSION_KEY, None)
# Context processor to make branding data available to all templates
@app.context_processor
def inject_branding():
    return {"branding": g.get("branding") or load_branding()}


@app.context_processor
def inject_current_user():
    return {"current_user": g.get("current_user")}


@app.context_processor
def inject_csrf_token():
    return {
        "csrf_token": session.get("csrf_token", ""),
        "customer_csrf_token": session.get("customer_csrf_token", ""),
        "current_customer": g.get("current_customer"),
    }


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    flash("File too large. Max size is 1GB.", "danger")
    return redirect(request.url)


@app.route("/")
def home():
    """Home route, simple message indicating system is running."""
    return "Proof approval system is running."

@app.route("/proofs/<path:filename>")
def serve_proof(filename):
    """Serves proof files from the PROOF_DIR."""
    return send_from_directory(PROOF_DIR, filename)


@app.route("/storage/local/<path:storage_key>")
def serve_local_storage(storage_key):
    """Serve files stored via the local storage backend."""
    if FILE_STORAGE_BACKEND != "local":
        abort(404)
    try:
        absolute_path = storage_backend.resolve_path(storage_key)
    except ValueError:
        abort(404)
    if not os.path.isfile(absolute_path):
        abort(404)
    directory = os.path.dirname(absolute_path)
    filename = os.path.basename(absolute_path)
    return send_from_directory(directory, filename)


@app.route("/_healthz")
def healthcheck():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    """Handles proof file uploads.
    On POST, saves the file and metadata, then redirects to a success page.
    On GET, renders the upload form.
    """
    active_designers = (
        Designer.query.filter_by(is_active=True)
        .order_by(Designer.display_name.asc())
        .all()
    )
    customers = (
        Customer.query.options(
            joinedload(Customer.credential),
            joinedload(Customer.auth_tokens),
        )
        .order_by(Customer.name.asc())
        .all()
    )
    current_designer = None
    user = g.get("current_user")
    if user and user.role == "designer":
        current_designer = user.designer_profile
        # Ensure designer list includes the current designer even if filtered differently
        if current_designer and current_designer not in active_designers:
            active_designers.append(current_designer)
    self_option_label = None
    SELF_DESIGNER_ID = "__self__"
    if user and user.role == "admin":
        self_option_label = f"Use my account ({user.name})"

    default_notify_subject = default_subject_template()
    default_notify_body = default_body_template()

    def render_upload_form(**extra):
        context = {
            "designers": active_designers,
            "customers": customers,
            "designer_readonly": bool(current_designer),
            "current_designer": current_designer,
            "selected_designer_id": extra.get("selected_designer_id"),
            "selected_customer_id": extra.get("selected_customer_id"),
            "job_name_value": extra.get("job_name_value", ""),
            "notes_value": extra.get("notes_value", ""),
            "notify_customer_checked": extra.get("notify_customer_checked", False),
            "notify_subject_value": extra.get("notify_subject_value", ""),
            "notify_body_value": extra.get("notify_body_value", ""),
            "default_notify_subject_template": default_notify_subject,
            "default_notify_body_template": default_notify_body,
            "self_option_label": self_option_label,
            "recipient_mode": extra.get("recipient_mode_value", "existing"),
            "guest_email_value": extra.get("guest_email_value", ""),
            "guest_name_value": extra.get("guest_name_value", ""),
            "guest_expiry_value": extra.get("guest_expiry_value", ""),
        }
        return render_template("upload.html", **context)

    if request.method == "POST":
        # Get form data and generate a unique job ID
        file = request.files.get('file')
        designer_id = request.form.get("designer_id")
        customer_id = request.form.get("customer_id")
        recipient_mode = (request.form.get("recipient_mode") or "existing").strip().lower()
        guest_email_input = (request.form.get("guest_email") or "").strip()
        guest_email = guest_email_input.lower()
        guest_name = (request.form.get("guest_name") or "").strip()
        guest_expiry_raw = (request.form.get("guest_expiry_hours") or "").strip()
        job_name = (request.form.get("job_name") or "").strip()
        notes = request.form.get("notes") or ""
        notify_flag = (request.form.get("notify_customer") or "").lower() in {"on", "true", "1", "yes"}
        notify_subject = request.form.get("notify_subject", "")
        notify_body = request.form.get("notify_body", "")
        job_id = str(uuid.uuid4())[:8]  # Short unique ID

        if recipient_mode != "guest" and guest_email:
            recipient_mode = "guest"

        form_state = {
            "selected_designer_id": designer_id,
            "selected_customer_id": customer_id,
            "job_name_value": job_name,
            "notes_value": notes,
            "notify_customer_checked": notify_flag,
            "notify_subject_value": notify_subject,
            "notify_body_value": notify_body,
            "recipient_mode_value": recipient_mode,
            "guest_email_value": guest_email_input,
            "guest_name_value": guest_name,
            "guest_expiry_value": guest_expiry_raw,
        }

        guest_expiry_hours = None
        if guest_expiry_raw:
            try:
                guest_expiry_hours = int(guest_expiry_raw)
                if guest_expiry_hours <= 0:
                    raise ValueError
            except ValueError:
                flash("Guest PIN expiry must be a positive number of hours.", "error")
                return render_upload_form(**form_state)

        if recipient_mode == "guest":
            notify_flag = True
            form_state["notify_customer_checked"] = True

        # Resolve designer from session or selection
        designer_record = None
        notify_sender_user = None
        if current_designer:
            designer_record = current_designer
        elif designer_id:
            if designer_id == SELF_DESIGNER_ID and user and user.role == "admin":
                notify_sender_user = user
            else:
                try:
                    designer_uuid = uuid.UUID(designer_id)
                except ValueError:
                    designer_uuid = None
                if designer_uuid:
                    designer_record = db.session.get(Designer, designer_uuid)
        
        if not designer_record and notify_sender_user is None:
            flash("Please select a valid designer before uploading.", "error")
            return render_upload_form(**form_state)

        selected_designer_value = designer_id if designer_id else (str(designer_record.id) if designer_record else None)
        form_state["selected_designer_id"] = selected_designer_value

        customer_record = None
        if recipient_mode != "guest":
            if not customer_id:
                flash("Please select a customer.", "error")
                return render_upload_form(**form_state)
            try:
                customer_uuid = uuid.UUID(customer_id)
                customer_record = db.session.get(Customer, customer_uuid)
            except (ValueError, TypeError):
                customer_record = None
            if not customer_record:
                flash("Please select a valid customer.", "error")
                return render_upload_form(**form_state)
            form_state["selected_customer_id"] = str(customer_record.id)
        else:
            form_state["selected_customer_id"] = ""
            if not guest_email:
                flash("Please provide an email address for the one-off recipient.", "error")
                return render_upload_form(**form_state)
            local_part, sep, domain_part = guest_email.partition("@")
            if not sep or not local_part or "." not in domain_part:
                flash("Please provide a valid email address.", "error")
                return render_upload_form(**form_state)

        if not file:
            flash("No file selected.", "error")
            return render_upload_form(**form_state)

        # Check file extension
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".pdf", ".jpg", ".jpeg", ".png"]:
            flash("Unsupported file type. Please upload PDF or image (JPG, JPEG, PNG).", "error")
            return render_upload_form(**form_state)

        # Secure filename and save the file
        filename = secure_filename(f"{job_id}{ext}")
        try:
            storage_backend.save(file, filename)
        except Exception as e:
            flash(f"Error saving file: {e}", "error")
            return render_upload_form(**form_state)

        guest_access = None
        guest_pin = None

        # Record proof metadata in the database
        try:
            proof = Proof(
                share_id=job_id,
                job_name=job_name or job_id,
                notes=notes,
                status="pending",
                designer_id=designer_record.id if designer_record else None,
                customer_id=customer_record.id if customer_record else None,
            )
            db.session.add(proof)

            absolute_path = storage_backend.resolve_path(filename)
            mime_type, _ = mimetypes.guess_type(filename)
            file_size = os.path.getsize(absolute_path) if os.path.exists(absolute_path) else None
            proof_version = ProofVersion(
                proof=proof,
                storage_path=filename,
                original_filename=file.filename,
                mime_type=mime_type,
                file_size=file_size,
                uploaded_by_id=g.current_user.id if g.get("current_user") else None,
            )
            db.session.add(proof_version)

            if recipient_mode == "guest":
                guest_access, guest_pin = build_guest_access(
                    proof,
                    email=guest_email,
                    name=guest_name,
                    expires_hours=guest_expiry_hours,
                )
                db.session.add(guest_access)

            db.session.commit()
        except SQLAlchemyError as err:
            db.session.rollback()
            flash(f"❌ Failed to persist proof metadata: {err}", "error")
            return render_upload_form(**form_state)

        # Generate the shareable URL for the proof
        if BASE_URL:
            path = url_for("show_proof", job_id=job_id)
            share_url = urljoin(BASE_URL.rstrip("/") + "/", path.lstrip("/"))
        else:
            share_url = url_for("show_proof", job_id=job_id, _external=True)

        guest_entry_url = None
        if guest_access:
            guest_path = url_for("customer.guest_access", token=guest_access.access_token)
            if BASE_URL:
                guest_entry_url = urljoin(BASE_URL.rstrip("/") + "/", guest_path.lstrip("/"))
            else:
                guest_entry_url = url_for("customer.guest_access", token=guest_access.access_token, _external=True)

        notification_status = None
        notification_error = None
        uploader_user = g.get("current_user")
        notification_owner = notify_sender_user or (designer_record.user if designer_record else None)
        sender_email = None
        reply_to_email = None
        if designer_record:
            sender_email = designer_record.email
            reply_to_email = designer_record.reply_to_email
        if not sender_email and notification_owner:
            sender_email = notification_owner.smtp_sender or notification_owner.email
        if not sender_email:
            sender_email = app.config.get("MAIL_DEFAULT_SENDER")
        if not reply_to_email and notification_owner:
            reply_to_email = notification_owner.smtp_reply_to or notification_owner.email
        if not reply_to_email:
            reply_to_email = DEFAULT_REPLY_TO or sender_email

        if guest_access:
            pseudo_customer = SimpleNamespace(
                name=guest_name or guest_email_input or guest_email,
                email=guest_email,
            )
            designer_display_name = (
                designer_record.display_name
                if designer_record
                else (notify_sender_user.name if notify_sender_user else "Your team")
            )
            guest_subject, guest_body_text, guest_body_html = render_notification_content(
                subject_template=notify_subject,
                body_template=notify_body,
                customer=pseudo_customer,
                proof=proof,
                share_url=guest_entry_url or share_url,
                designer_name=designer_display_name,
                invite_link=None,
                extra_context={"guest_pin": guest_pin or ""},
            )
            if guest_pin and guest_pin not in guest_body_text:
                guest_body_text = guest_body_text.rstrip() + f"\n\nOne-time PIN: {guest_pin}"
                if guest_body_html is not None:
                    guest_body_html = guest_body_html.rstrip() + (
                        f"<p>One-time PIN: <strong>{guest_pin}</strong></p>"
                    )
            try:
                send_email_notification(
                    guest_subject,
                    guest_body_text,
                    guest_email,
                    user=notification_owner,
                    fallback_sender=sender_email,
                    fallback_reply_to=reply_to_email,
                    html_body=guest_body_html,
                )
                notification_status = "queued"
            except Exception as exc:
                notification_status = "failed"
                notification_error = str(exc)
                flash("⚠️ Guest notification could not be sent. Share the link and PIN manually.", "warning")
        elif notify_flag and customer_record:
            invite_link = None
            portal_enabled = current_app.config.get("CUSTOMER_LOGIN_ENABLED", False)
            credential = getattr(customer_record, "credential", None)
            if portal_enabled and (not credential or not credential.is_active):
                issued_by_user_id = uploader_user.id if uploader_user else None
                try:
                    invite_link, _ = issue_customer_invite(
                        customer_record,
                        issued_by_user_id=issued_by_user_id,
                        allow_existing=True,
                        suppress_email=True,
                    )
                except InviteAlreadyPendingError:
                    invite_link = None
                except Exception as exc:
                    invite_link = None
                    notification_error = str(exc)
                    flash(
                        "⚠️ Customer invite could not be generated. The notification was sent without an invite link.",
                        "warning",
                    )

            smtp_user = notification_owner
            proof_version = proof.versions[-1] if proof.versions else None
            try:
                queue_customer_notification(
                    proof=proof,
                    proof_version=proof_version,
                    customer=customer_record,
                    uploader=uploader_user,
                    smtp_user=smtp_user,
                    share_url=share_url,
                    subject_template=notify_subject,
                    body_template=notify_body,
                    sender_email=sender_email,
                    reply_to_email=reply_to_email,
                    invite_link=invite_link,
                )
                db.session.commit()
                notification_status = "queued"
            except Exception as exc:
                db.session.rollback()
                notification_status = "failed"
                notification_error = str(exc)
                flash("⚠️ Customer notification could not be queued. Please try again later.", "warning")

        display_url = guest_entry_url or share_url
        notify_success_flag = notify_flag or bool(guest_access)

        return render_template(
            "upload_success.html",
            share_url=display_url,
            job_name=job_name,
            notification_status=notification_status,
            notification_error=notification_error,
            notify_customer=notify_success_flag,
            guest_email=guest_email_input if guest_access else None,
            guest_pin=guest_pin,
            guest_link=guest_entry_url,
            guest_expires_at=guest_access.expires_at if guest_access else None,
        )

    # For GET request, render the upload form
    if current_designer:
        selected_id = str(current_designer.id)
    elif self_option_label:
        selected_id = SELF_DESIGNER_ID
    else:
        selected_id = None
    return render_upload_form(selected_designer_id=selected_id)


@app.route("/proof/<job_id>/new_version", methods=["GET", "POST"])
@login_required
def new_version(job_id):
    proof = Proof.query.filter_by(share_id=job_id).first_or_404()

    if request.method == "POST":
        file = request.files.get('file')
        notes = request.form.get("notes", "")

        if not file:
            flash("No file selected.", "error")
            return render_template("new_version.html", proof=proof)

        # Check file extension
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".pdf", ".jpg", ".jpeg", ".png"]:
            flash("Unsupported file type. Please upload PDF or image (JPG, JPEG, PNG).", "error")
            return render_template("new_version.html", proof=proof)

        # Secure filename and save the file
        filename = secure_filename(f"{proof.share_id}_v{len(proof.versions) + 1}{ext}")
        try:
            storage_backend.save(file, filename)
        except Exception as e:
            flash(f"Error saving file: {e}", "error")
            return render_template("new_version.html", proof=proof)

        # Record proof metadata in the database
        try:
            proof.status = "pending"
            proof_version = ProofVersion(
                proof=proof,
                storage_path=filename,
                original_filename=file.filename,
                mime_type=mimetypes.guess_type(filename)[0],
                file_size=os.path.getsize(storage_backend.resolve_path(filename)),
                uploaded_by_id=g.current_user.id if g.get("current_user") else None,
            )
            db.session.add(proof_version)
            db.session.commit()
        except SQLAlchemyError as err:
            db.session.rollback()
            flash(f"❌ Failed to persist proof metadata: {err}", "error")
            return render_template("new_version.html", proof=proof)

        flash("New version uploaded successfully.", "success")
        return redirect(url_for("show_proof", job_id=proof.share_id))
    return render_template("new_version.html", proof=proof)


@app.route("/proof/<job_id>/compare")
@login_required
def compare_versions(job_id):
    proof = Proof.query.filter_by(share_id=job_id).first_or_404()
    return render_template("compare_versions.html", proof=proof)


@app.route("/proof/<job_id>/annotate")
@login_required
def annotate_proof(job_id):
    proof = Proof.query.filter_by(share_id=job_id).first_or_404()
    return render_template("annotate_proof.html", proof=proof)


@app.route("/proof/<job_id>")
def show_proof(job_id):
    """Displays a proof to the client for review and approval/rejection."""
    login_enabled = current_app.config.get("CUSTOMER_LOGIN_ENABLED", False)
    legacy_enabled = current_app.config.get("LEGACY_PUBLIC_LINKS_ENABLED", True)
    customer_login_url = (
        url_for("customer.login", next=url_for("customer.view_proof", share_id=job_id))
        if login_enabled
        else None
    )
    show_portal_banner = False

    proof = Proof.query.filter_by(share_id=job_id).first()
    meta = None
    file_url = None
    file_extension = ""
    versions = []
    version_options: list[SimpleNamespace] = []
    latest_version_id: str | None = None

    if not proof:
        meta_path = os.path.join(LOG_DIR, f"{job_id}.json")
        if not os.path.exists(meta_path):
            return "Job not found", 404
        with open(meta_path, "r") as f:
            meta = json.load(f)
        filename = meta.get("filename")
        if filename:
            file_url = url_for("serve_proof", filename=filename)
            file_extension = os.path.splitext(filename)[1].lower()
    else:
        versions = list(proof.versions)  # Materialise for repeated access
        latest_version = versions[-1] if versions else None
        designer_name = proof.designer.display_name if proof.designer else None
        if not designer_name:
            candidate_version = latest_version or (versions[0] if versions else None)
            uploader = candidate_version.uploaded_by if candidate_version else None
            if uploader:
                designer_name = uploader.name
        if not designer_name:
            designer_name = "Team"

        meta = {
            "job_id": proof.share_id,
            "job_name": proof.job_name,
            "notes": proof.notes,
            "status": proof.status,
            "designer": designer_name,
            "approver_name": proof.decisions[-1].approver_name if proof.decisions else "",
        }
        if latest_version:
            storage_key = latest_version.storage_path
            meta["filename"] = os.path.basename(storage_key)
            file_url = storage_backend.generate_url(storage_key)
            original = latest_version.original_filename or storage_key
            file_extension = os.path.splitext(original)[1].lower()
            latest_version_id = str(latest_version.id)
        else:
            meta["filename"] = ""

        for version in versions:
            storage_key = version.storage_path
            original = version.original_filename or storage_key
            ext = os.path.splitext(original)[1].lower()
            version_options.append(
                SimpleNamespace(
                    id=str(version.id),
                    file_url=storage_backend.generate_url(storage_key),
                    file_ext=ext,
                    created_at=version.created_at,
                )
            )

    # Load disclaimer text
    disclaimer_path = os.path.join(ADMIN_DIR, "disclaimer.txt")
    disclaimer_text = ""
    if os.path.exists(disclaimer_path):
        with open(disclaimer_path, "r") as f:
            disclaimer_text = f.read().strip()

    guest_authorized_ids = session.get(GUEST_PROOF_SESSION_KEY, [])
    if proof and not proof.customer_id:
        active_guest_links = [ga for ga in proof.guest_accesses if access_is_active(ga)]
        if active_guest_links:
            staff_user = g.get("current_user")
            staff_can_preview = bool(staff_user and staff_user.role in {"admin", "designer"})
            guest_has_access = proof.share_id in guest_authorized_ids
            if not staff_can_preview and not guest_has_access:
                next_url = request.url
                return redirect(url_for("customer.guest_access", token=active_guest_links[0].access_token, next=next_url))

    if proof and proof.customer_id and login_enabled:
        staff_user = g.get("current_user")
        staff_can_preview = bool(staff_user and staff_user.role in {"admin", "designer"})
        customer = g.get("current_customer")
        customer_can_view = bool(customer and customer.id == proof.customer_id)

        if not customer_can_view and not staff_can_preview:
            if legacy_enabled:
                show_portal_banner = True
            else:
                flash("Please sign in to view this proof.", "info")
                if customer_login_url:
                    return redirect(customer_login_url)
                abort(403)
        elif legacy_enabled and not customer_can_view:
            show_portal_banner = True

    # Note: logo_url is now available via branding context processor
    return render_template(
        "proof.html",
        job_id=meta["job_id"],
        job_name=meta.get("job_name", meta["job_id"]),
        proof_file_url=file_url,
        proof_file_extension=file_extension,
        designer=meta.get("designer", "N/A"),
        notes=meta.get("notes", ""),
        status=meta.get("status", "pending"),
        approver_name=meta.get("approver_name", ""),
        disclaimer=disclaimer_text,
        version_options=version_options,
        latest_version_id=latest_version_id or "",
        customer_portal_banner=show_portal_banner,
        customer_login_url=customer_login_url,
        customer_login_enabled=login_enabled,
        legacy_links_enabled=legacy_enabled,
    )



@app.route("/submit", methods=["POST"])
def submit():
    """Handles client's decision (approve/decline) on a proof."""
    job_id = request.form.get("job_id")
    decision = request.form.get("decision")
    comment = request.form.get("client_comment", "").strip()
    approver_name = request.form.get("approver_name", "").strip()
    ip = request.remote_addr
    timestamp = datetime.now().isoformat()
    status = "approved" if decision == "approved" else "declined"

    proof = Proof.query.filter_by(share_id=job_id).first()
    designer_email = None
    designer_name = ""
    job_name_value = job_id
    email_sender = app.config.get("MAIL_DEFAULT_SENDER")
    reply_to = DEFAULT_REPLY_TO or email_sender
    notification_user = None

    login_enabled = current_app.config.get("CUSTOMER_LOGIN_ENABLED", False)
    legacy_enabled = current_app.config.get("LEGACY_PUBLIC_LINKS_ENABLED", True)

    if proof:
        if proof.customer_id and login_enabled and not legacy_enabled:
            staff_user = g.get("current_user")
            staff_can_submit = bool(staff_user and staff_user.role in {"admin", "designer"})
            customer = g.get("current_customer")
            customer_can_submit = bool(customer and customer.id == proof.customer_id)
            if not staff_can_submit and not customer_can_submit:
                flash("Please sign in through the customer portal to respond to this proof.", "error")
                return redirect(
                    url_for("customer.login", next=url_for("customer.view_proof", share_id=job_id))
                )

        guest_authorized_ids = session.get(GUEST_PROOF_SESSION_KEY, [])
        active_guest_links = [ga for ga in proof.guest_accesses if access_is_active(ga)]
        if proof.customer_id is None and active_guest_links:
            staff_user = g.get("current_user")
            staff_can_submit = bool(staff_user and staff_user.role in {"admin", "designer"})
            guest_has_access = proof.share_id in guest_authorized_ids
            if not staff_can_submit and not guest_has_access:
                flash("Please unlock this proof with your guest PIN before responding.", "error")
                return redirect(
                    url_for(
                        "customer.guest_access",
                        token=active_guest_links[0].access_token,
                        next=url_for("show_proof", job_id=job_id),
                    )
                )

        job_name_value = proof.job_name
        uploader_user = proof.versions[-1].uploaded_by if proof.versions else None
        if proof.designer:
            designer_name = proof.designer.display_name or (proof.designer.user.name if proof.designer.user else "")
            designer_email = proof.designer.email or (proof.designer.user.email if proof.designer.user else None)
            notification_user = proof.designer.user
            if proof.designer.reply_to_email:
                reply_to = proof.designer.reply_to_email
            if proof.designer.email:
                email_sender = proof.designer.email
        if not designer_name and uploader_user:
            designer_name = uploader_user.name
        if not designer_email and uploader_user:
            designer_email = uploader_user.email
            notification_user = uploader_user
            if uploader_user.smtp_reply_to:
                reply_to = uploader_user.smtp_reply_to
        if not designer_name:
            designer_name = "Your team"
        if not reply_to:
            reply_to = DEFAULT_REPLY_TO or email_sender

        try:
            proof.status = status
            decision_record = Decision(
                proof=proof,
                proof_version=proof.versions[-1] if proof.versions else None,
                status=status,
                approver_name=approver_name or None,
                client_comment=comment or None,
                client_ip=ip,
            )
            db.session.add(decision_record)
            db.session.commit()
        except SQLAlchemyError as err:
            db.session.rollback()
            print(f"Error updating proof record: {err}")
            flash("Failed to record decision. Please try again.", "error")
            return redirect(url_for("show_proof", job_id=job_id))
    else:
        # Legacy fallback
        meta_path = os.path.join(LOG_DIR, f"{job_id}.json")
        if not os.path.exists(meta_path):
            flash("Job not found.", "error")
            return redirect(url_for('home'))

        with open(meta_path, "r") as f:
            meta = json.load(f)

        designer_name = meta.get("designer_display_name") or meta.get("designer") or ""
        designer_email = meta.get("designer_email")
        job_name_value = meta.get("job_name", job_id)
        if designer_email:
            email_sender = designer_email
            reply_to = designer_email
        meta.update({
            "status": status,
            "timestamp": timestamp,
            "client_comment": comment,
            "approver_name": approver_name
        })
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    branding = load_branding()
    default_sender = email_sender or app.config.get("MAIL_DEFAULT_SENDER")
    to_address = designer_email or default_sender
    if not to_address:
        flash("Decision recorded, but no designer email is configured to notify.", "warning")

    subject = f"{branding['company_name']}: Client has {decision.upper()} job {job_name_value}"
    body = (
        f"Job: {job_name_value}\n"
        f"Decision: {decision.capitalize()}\n"
        f"By: {approver_name}\n"
        f"IP: {ip}\n"
        f"Timestamp: {timestamp}"
    )
    if comment:
        body += f"\n\nClient comment:\n{comment}"

    footer = branding.get("email_footer", "")
    if footer:
        body += f"\n\n---\n{footer}"

    try:
        send_email_notification(
            subject,
            body,
            to_address,
            user=notification_user,
            fallback_sender=default_sender,
            fallback_reply_to=reply_to,
        )
        flash("Decision submitted and designer notified.", "success")
    except Exception as e:
        print(f"Error sending mail: {e}")
        flash("Decision submitted, but failed to send email notification.", "warning")

    return render_template("thanks.html",
        decision=decision,
        designer=designer_name,
        job_name=job_name_value,
        approver_name=approver_name,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    """Handles user login via database-backed credentials."""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        entered_password = (request.form.get("password") or "").strip()
        ip = _current_ip()

        if not email or not entered_password:
            flash("❌ Email and password are required.", "error")
            return render_template("login.html")

        if _is_login_locked(ip):
            flash("❌ Too many login attempts. Please try again later.", "error")
            return render_template("login.html"), 429

        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, entered_password):
            _record_login_failure(ip)
            flash("❌ Invalid credentials", "error")
            return render_template("login.html")

        if not user.is_active:
            flash("❌ Account is inactive. Contact an administrator.", "error")
            return render_template("login.html")

        session.clear()
        session[SESSION_USER_ID] = str(user.id)
        _clear_login_failures(ip)
        session["csrf_token"] = secrets.token_hex(32)
        flash("✅ Logged in successfully!", "success")

        next_url = request.args.get("next")
        if next_url:
            return redirect(next_url)

        destination = "admin.admin_home" if user.role == "admin" else "designer_dashboard"
        return redirect(url_for(destination))
    return render_template("login.html")


@app.route("/logout")
def logout():
    """Logs out the administrator."""
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect("/login")



@app.route("/designer/dashboard")
@login_required(role="designer")
def designer_dashboard():
    user = g.current_user
    designer = user.designer_profile if user else None

    records: list[SimpleNamespace] = []
    if designer:
        proofs = (
            Proof.query.filter(Proof.designer_id == designer.id)
            .order_by(Proof.updated_at.desc(), Proof.created_at.desc())
            .all()
        )
        for proof in proofs:
            latest_decision = proof.decisions[-1] if proof.decisions else None
            decision_ts = latest_decision.created_at if latest_decision and latest_decision.created_at else None
            updated_ts = proof.updated_at or proof.created_at
            records.append(
                SimpleNamespace(
                    job_name=proof.job_name,
                    status=(proof.status or "pending"),
                    decision_timestamp_display=decision_ts.strftime("%Y-%m-%d %H:%M") if decision_ts else "",
                    approver_name=latest_decision.approver_name if latest_decision else "",
                    client_comment=latest_decision.client_comment if latest_decision else "",
                    updated_at_display=updated_ts.strftime("%Y-%m-%d %H:%M") if updated_ts else "",
                    link=url_for("show_proof", job_id=proof.share_id),
                    share_id=proof.share_id,
                )
            )

    smtp_configured = bool(user and user.smtp_host and user.smtp_port)
    last_test_display = (
        user.smtp_last_test_at.strftime("%Y-%m-%d %H:%M UTC")
        if user and user.smtp_last_test_at
        else ""
    )
    if not smtp_configured:
        smtp_status = {
            "level": "warning",
            "message": "SMTP settings are incomplete. Add a host and port before sending notifications.",
        }
    elif user.smtp_last_test_status == "failed":
        message = "Last SMTP test failed"
        if last_test_display:
            message += f" on {last_test_display}"
        if user.smtp_last_error:
            message += f": {user.smtp_last_error}"
        smtp_status = {"level": "error", "message": message}
    elif user.smtp_last_test_status == "success":
        message = "SMTP test succeeded"
        if last_test_display:
            message += f" on {last_test_display}"
        smtp_status = {"level": "success", "message": message}
    else:
        smtp_status = {
            "level": "info",
            "message": "SMTP test has not been run yet for this account.",
        }

    return render_template(
        "designer_dashboard.html",
        proofs=records,
        designer=designer,
        smtp_status=smtp_status,
        smtp_can_test=smtp_configured,
    )


@app.route("/designer/smtp-test", methods=["POST"])
@login_required(role="designer")
def designer_smtp_test():
    user = g.current_user
    if not user:
        abort(403)

    if not user.smtp_host or not user.smtp_port:
        flash("Configure SMTP host and port before sending a test email.", "warning")
        return redirect(url_for("designer_dashboard"))

    target = (request.form.get("test_email") or "").strip() or user.email
    subject = "SMTP Test"
    body = (
        "This is a test email using your personal SMTP settings.\n\n"
        f"Timestamp: {datetime.utcnow().isoformat()}"
    )

    try:
        send_email_notification(
            subject,
            body,
            target,
            user=user,
            fallback_sender=user.smtp_sender or current_app.config.get("MAIL_DEFAULT_SENDER"),
            fallback_reply_to=user.smtp_reply_to or current_app.config.get("MAIL_DEFAULT_REPLY_TO"),
            async_send=False,
            allow_fallback=False,
        )
        user.smtp_last_test_status = "success"
        user.smtp_last_test_at = datetime.utcnow()
        user.smtp_last_error = None
        db.session.commit()
        flash(f"✅ Test email sent to {target}.", "success")
    except Exception as exc:
        user.smtp_last_test_status = "failed"
        user.smtp_last_test_at = datetime.utcnow()
        user.smtp_last_error = str(exc)[:500]
        db.session.commit()
        flash(f"❌ Failed to send test email: {exc}", "error")

    return redirect(url_for("designer_dashboard"))


@app.route("/designer/customers", methods=["GET", "POST"])
@login_required(role="designer")
def designer_customers():
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                name = (request.form.get("name") or "").strip()
                company_name = (request.form.get("company_name") or "").strip()
                email = (request.form.get("email") or "").strip().lower()
                if not name or not email:
                    raise ValueError("Customer name and email are required.")
                if Customer.query.filter_by(email=email).first():
                    raise ValueError("A customer with that email already exists.")
                customer = Customer(name=name, company_name=company_name, email=email)
                db.session.add(customer)
                db.session.commit()
                flash(f"✅ Added customer {name}.", "success")
            elif action == "delete":
                customer_id = request.form.get("customer_id")
                if not customer_id:
                    raise ValueError("Customer identifier required.")
                customer = db.session.get(Customer, uuid.UUID(customer_id))
                if not customer:
                    raise ValueError("Customer not found.")
                db.session.delete(customer)
                db.session.commit()
                flash("✅ Customer removed.", "success")
            else:
                flash("❌ Unknown action.", "error")
        except (ValueError, SQLAlchemyError) as exc:
            db.session.rollback()
            flash(f"❌ {exc}", "error")

    customers = (
        Customer.query.options(
            joinedload(Customer.credential),
            joinedload(Customer.auth_tokens),
        )
        .order_by(Customer.name.asc())
        .all()
    )
    customer_rows = [
        {
            "customer": customer,
            "invite": describe_invite_status(customer),
        }
        for customer in customers
    ]
    portal_enabled = current_app.config.get("CUSTOMER_LOGIN_ENABLED", False)
    return render_template(
        "designer_customers.html",
        customer_rows=customer_rows,
        portal_enabled=portal_enabled,
    )


@app.route("/designer/customers/<uuid:customer_id>/invite", methods=["POST"])
@login_required(role="designer")
def designer_customer_invite(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer:
        abort(404)

    portal_enabled = current_app.config.get("CUSTOMER_LOGIN_ENABLED", False)
    if not portal_enabled:
        flash("Customer login is currently disabled.", "error")
        return redirect(url_for("designer_customers"))

    credential = customer.credential
    if credential and credential.is_active:
        flash("Customer already has an active account.", "info")
        return redirect(url_for("designer_customers"))

    try:
        invite_link, _ = issue_customer_invite(
            customer,
            issued_by_user_id=g.current_user.id,
        )
        db.session.commit()
        flash(f"✅ Invite sent to {customer.email}.", "success")
    except InviteAlreadyPendingError as exc:
        expires = exc.token.expires_at
        expiry_text = f" (expires {expires.strftime('%Y-%m-%d %H:%M %Z')})" if expires else ""
        flash(f"⚠️ An invite is already pending for {customer.email}{expiry_text}.", "warning")
        db.session.rollback()
    except Exception as exc:  # pragma: no cover - defensive
        db.session.rollback()
        flash(f"❌ Failed to send invite: {exc}", "error")

    return redirect(url_for("designer_customers"))


@app.route("/designer/customers/<uuid:customer_id>/edit", methods=["GET", "POST"])
@login_required(role="designer")
def designer_customer_edit(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer:
        abort(404)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        company_name = (request.form.get("company_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        try:
            if not name or not email:
                raise ValueError("Customer name and email are required.")
            existing = Customer.query.filter(Customer.email == email, Customer.id != customer.id).first()
            if existing:
                raise ValueError("Another customer already uses that email.")
            customer.name = name
            customer.company_name = company_name
            customer.email = email
            db.session.commit()
            flash("✅ Customer updated.", "success")
            return redirect(url_for("designer_customers"))
        except (ValueError, SQLAlchemyError) as exc:
            db.session.rollback()
            flash(f"❌ {exc}", "error")

    return render_template("designer_customer_edit.html", customer=customer)


@app.route("/status", methods=["GET", "POST"])
def check_status():
    status = None
    job_name = None
    designer = None
    comment = None
    job_id = None
    error = None

    if request.method == "POST":
        raw = request.form.get("proof_url", "").strip()

        # If full proof URL provided
        if "/proof/" in raw:
            try:
                job_id = raw.rsplit("/proof/", 1)[1].split("?")[0]
            except Exception:
                job_id = None
                error = "Invalid proof link format."
        # If raw alphanumeric ID or job name
        elif re.match(r'^[A-Za-z0-9\-]+$', raw):
            candidate = raw
            proof = Proof.query.filter_by(share_id=candidate).first()
            if proof:
                job_id = proof.share_id
            else:
                proof = Proof.query.filter(Proof.job_name == candidate).first()
                if proof:
                    job_id = proof.share_id
            if not job_id:
                # Fallback to legacy logs if needed
                legacy_path = os.path.join(LOG_DIR, f"{candidate}.json")
                if os.path.exists(legacy_path):
                    job_id = candidate
                else:
                    for fname in os.listdir(LOG_DIR):
                        if fname.endswith(".json"):
                            with open(os.path.join(LOG_DIR, fname), "r") as f:
                                meta = json.load(f)
                            if meta.get("job_name") == candidate:
                                job_id = meta.get("job_id")
                                break
                    if not job_id and not error:
                        error = "No proof found matching that ID or Job Name."
        else:
            error = "Please enter a valid proof link (e.g., containing '/proof/'), a proof ID, or a known Job Name."

        # If we have a job_id and no prior error, load status
        if job_id and not error:
            proof = Proof.query.filter_by(share_id=job_id).first()
            if proof:
                status = (proof.status or "pending").capitalize()
                job_name = proof.job_name
                designer = proof.designer.display_name if proof.designer else ""
                latest_decision = proof.decisions[-1] if proof.decisions else None
                comment = latest_decision.client_comment if latest_decision else ""
            else:
                meta_path = os.path.join(LOG_DIR, f"{job_id}.json")
                if os.path.exists(meta_path):
                    with open(meta_path, "r") as f:
                        meta = json.load(f)
                    status = meta.get("status", "pending").capitalize()
                    job_name = meta.get("job_name", job_id)
                    designer = meta.get("designer", "")
                    comment = meta.get("client_comment", "")
                else:
                    error = "No proof found for the provided link."

    return render_template(
        "status_check.html",
        job_id=job_id,
        job_name=job_name,
        designer=designer,
        status=status,
        comment=comment,
        error=error,
    )



@app.route("/theme.css")
def theme_css():
    """Dynamically generates CSS based on branding settings."""
    s = load_branding() # Load current branding settings
    css = (
        f":root {{"
        f"--bg-color: {s['background_color']};"
        f"--text-color: #000000;" # Assuming text is always black for contrast
        f"--primary-color: {s['primary_color']};"
        f"--approve-btn-color: {s['approve_button_color']};"
        f"--reject-btn-color: {s['reject_button_color']};"
        f"--font-family: {s.get('font_family', 'Roboto, sans-serif')};"
        f"--general-btn-color: {s['general_button_color']};" # Changed to general_button_color
        f"}}"
        # Basic body styling to apply font and background
        f"body {{"
        f"  font-family: var(--font-family);"
        f"  background-color: var(--bg-color);"
        f"  color: var(--text-color);"
        f"}}"
        # Basic button styling using branding colors
        f"button, .button, input[type='submit'] {{"
        f"  padding: 10px 20px;"
        f"  border-radius: 5px;"
        f"  border: none;"
        f"  cursor: pointer;"
        f"  font-size: 1em;"
        f"  background-color: var(--general-btn-color);" # Used general_button_color
        f"  color: white;" # Ensure text is white by default for all buttons
        f"}}"
        f"button.approve, .button.approve, input[type='submit'].approve {{"
        f"  background-color: var(--approve-btn-color);"
        f"  color: white;"
        f"}}"
        f"button.reject, .button.reject, input[type='submit'].reject {{"
        f"  background-color: var(--reject-btn-color);"
        f"  color: white;"
        f"}}"
        # Styling for the submit-button used in admin forms (now explicitly uses general-btn-color)
        f"button.submit-button, .submit-button {{"
        f"  background-color: var(--general-btn-color);" # Changed to general_button_color
        f"  color: white;"
        f"}}"
        f"a {{"
        f"  color: var(--primary-color);"
        f"  text-decoration: none;"
        f"}}"
        f"a:hover {{"
        f"  text-decoration: underline;"
        f"}}"
        f".flash-message {{"
        f"  padding: 10px;"
        f"  margin-bottom: 15px;"
        f"  border-radius: 5px;"
        f"}}"
        f".flash-message.success {{"
        f"  background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb;"
        f"}}"
        f".flash-message.error {{"
        f"  background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb;"
        f"}}"
        f".flash-message.info {{"
        f"  background-color: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb;"
        f"}}"
        f".flash-message.warning {{"
        f"  background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba;"
        f"}}"
        f".logo {{"
        f"    max-width: 150px;"
        f"    height: auto;"
        f"    margin-bottom: 20px;"
        f"}}"
    )
    return Response(css, mimetype="text/css")


def _slugify_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")
    return slug or "designer"


def _parse_iso_timestamp(raw: str):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


@app.cli.command("create-user")
@click.option("--email", prompt=True, help="Email address for the user.")
@click.option("--name", prompt=True, help="Display name for the user.")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option(
    "--role",
    type=click.Choice(["admin", "designer"]),
    default="admin",
    show_default=True,
)
@click.option(
    "--designer-display-name",
    default="",
    help="Optional display name for designer profile (defaults to user name).",
)
@click.option(
    "--designer-reply-to",
    default="",
    help="Optional reply-to email for designer notifications.",
)
def create_user(email, name, password, role, designer_display_name, designer_reply_to):
    """Create a user (and optional designer profile) in the database."""
    email = email.strip().lower()
    name = name.strip()
    reply_to = designer_reply_to.strip() or email

    with app.app_context():
        if User.query.filter_by(email=email).first():
            raise click.ClickException(f"A user with email {email} already exists.")

        user = User(
            email=email,
            name=name,
            password_hash=generate_password_hash(password),
            role=role,
            is_active=True,
        )
        db.session.add(user)

        if role == "designer":
            display_name = designer_display_name.strip() or name
            designer = Designer(
                user=user,
                display_name=display_name,
                email=email,
                reply_to_email=reply_to,
                is_active=True,
            )
            db.session.add(designer)

        db.session.commit()

    click.echo(f"Created {role} user {email}.")


@app.cli.command("reset-password")
@click.option("--email", prompt=True, help="Email address for the account.")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def reset_password_cli(email, password):
    """Reset an existing user's password."""
    email = email.strip().lower()

    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            raise click.ClickException(f"No user found with email {email}.")

        user.password_hash = generate_password_hash(password)
        db.session.commit()

    click.echo(f"Password updated for {email}.")


@app.cli.command("invite-customer")
@click.argument("email")
@click.option("--hours-valid", default=72, show_default=True, type=int, help="Hours before the invite link expires.")
@click.option("--no-send", is_flag=True, help="Generate the invite link without emailing the customer.")
def invite_customer_cli(email, hours_valid, no_send):
    """Generate and optionally email a customer portal invitation."""
    target_email = email.strip().lower()

    with app.app_context():
        customer = Customer.query.filter(func.lower(Customer.email) == target_email).first()
        if not customer:
            raise click.ClickException(f"No customer found with email {target_email}.")

        raw_token = issue_customer_token(customer, "invite", hours_valid=hours_valid)
        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            raise click.ClickException(f"Failed to create invite: {exc}")

        if current_app.config.get("PUBLIC_BASE_URL"):
            base = current_app.config["PUBLIC_BASE_URL"].rstrip("/") + "/"
            invite_path = url_for("customer.accept_invite", token=raw_token).lstrip("/")
            invite_link = urljoin(base, invite_path)
        else:
            invite_link = url_for("customer.accept_invite", token=raw_token, _external=True)

        if no_send:
            click.echo("Invite generated but email not sent (--no-send).")
        else:
            send_customer_token_email(customer, "invite", invite_link)
            click.echo(f"Invite email queued for {customer.email}.")

        click.echo(f"Activation link: {invite_link}")


@app.cli.command("import-legacy-data")
@click.option(
    "--log-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=str),
    default=LOG_DIR,
    show_default=True,
    help="Directory containing legacy JSON job files.",
)
@click.option(
    "--proofs-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=str),
    default=PROOF_DIR,
    show_default=True,
    help="Directory where legacy proof binaries are stored.",
)
@click.option(
    "--approvals-csv",
    type=click.Path(file_okay=False, dir_okay=False, path_type=str),
    default="",
    help="Optional path to approvals.csv; defaults to <log-dir>/approvals.csv when omitted.",
)
@click.option(
    "--email-domain",
    default="example.com",
    show_default=True,
    help="Domain to use when synthesising designer email addresses.",
)
@click.option(
    "--dry-run/--commit",
    default=False,
    help="Preview import without committing changes.",
)
def import_legacy_data(log_dir, proofs_dir, approvals_csv, email_domain, dry_run):
    """Import legacy JSON/CSV proof data into the database."""
    from pathlib import Path
    import mimetypes
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    from app.models import User, Designer, Proof, ProofVersion, Decision

    log_path = Path(log_dir)
    proofs_path = Path(proofs_dir)
    csv_path = Path(approvals_csv) if approvals_csv else log_path / "approvals.csv"

    jobs = {}
    for meta_file in sorted(log_path.glob("*.json")):
        try:
            with meta_file.open() as handle:
                meta = json.load(handle)
        except (json.JSONDecodeError, OSError) as err:
            click.echo(f"Skipping {meta_file.name}: {err}")
            continue

        job_id = str(meta.get("job_id", "")).strip()
        if not job_id:
            click.echo(f"Skipping {meta_file.name}: missing job_id.")
            continue
        jobs[job_id] = meta

    created_users = created_designers = created_proofs = created_versions = created_decisions = 0
    skipped_existing = 0
    missing_files = []
    missing_proofs_for_decisions = []

    with app.app_context():
        session = db.session
        email_in_use = set(session.scalars(select(User.email)).all())
        designers_by_name = {
            designer.display_name.lower(): designer
            for designer in session.scalars(select(Designer)).all()
        }
        proofs_by_share_id = {
            proof.share_id: proof for proof in session.scalars(select(Proof)).all()
        }

        default_password_hash = generate_password_hash("changeme")

        for job_id, meta in jobs.items():
            if job_id in proofs_by_share_id:
                skipped_existing += 1
                continue

            designer_name = (meta.get("designer") or "").strip()
            if not designer_name:
                click.echo(f"Skipping {job_id}: no designer recorded.")
                continue

            designer_key = designer_name.lower()
            designer = designers_by_name.get(designer_key)

            if not designer:
                base_slug = _slugify_name(designer_name)
                candidate = f"{base_slug}@{email_domain}"
                counter = 1
                while candidate in email_in_use:
                    counter += 1
                    candidate = f"{base_slug}{counter}@{email_domain}"

                user = User(
                    email=candidate,
                    name=designer_name,
                    password_hash=default_password_hash,
                    role="designer",
                )
                designer = Designer(
                    user=user,
                    display_name=designer_name,
                    email=candidate,
                    reply_to_email=candidate,
                    is_active=True,
                )
                session.add(user)
                session.add(designer)

                email_in_use.add(candidate)
                designers_by_name[designer_key] = designer
                created_users += 1
                created_designers += 1

            proof = Proof(
                share_id=job_id,
                job_name=meta.get("job_name") or job_id,
                notes=meta.get("notes"),
                status=meta.get("status", "pending"),
                designer=designer,
            )

            timestamp = _parse_iso_timestamp(meta.get("timestamp"))
            if timestamp:
                proof.created_at = timestamp
                proof.updated_at = timestamp

            session.add(proof)
            created_proofs += 1
            proofs_by_share_id[job_id] = proof

            filename = meta.get("filename")
            if filename:
                storage_path = filename
                file_path = proofs_path / filename
                mime_type, _ = mimetypes.guess_type(filename)
                file_size = None
                if file_path.exists():
                    file_size = file_path.stat().st_size
                else:
                    missing_files.append(filename)
                    click.echo(f"Missing file for {job_id}: {filename}")

                version = ProofVersion(
                    proof=proof,
                    storage_path=storage_path,
                    original_filename=filename,
                    mime_type=mime_type,
                    file_size=file_size,
                    uploaded_by=designer.user if designer.user else None,
                )
                if timestamp:
                    version.created_at = timestamp
                    version.updated_at = timestamp
                session.add(version)
                created_versions += 1

        session.flush()

        csv_records = []
        if csv_path.exists():
            try:
                with csv_path.open() as handle:
                    reader = csv.DictReader(handle)
                    csv_records = list(reader)
            except OSError as err:
                click.echo(f"Unable to read {csv_path}: {err}")

        existing_decision_keys = {
            (
                str(decision.proof_id),
                decision.status,
                decision.approver_name or "",
                decision.client_comment or "",
                decision.created_at.isoformat() if decision.created_at else "",
            )
            for decision in session.scalars(select(Decision)).all()
        }

        for row in csv_records:
            job_id = (row.get("Job ID") or row.get("job_id") or "").strip()
            if not job_id:
                continue

            proof = proofs_by_share_id.get(job_id)
            if not proof:
                missing_proofs_for_decisions.append(job_id)
                continue

            status = (row.get("Decision") or "").strip().lower() or "pending"
            approver = (row.get("Approver Name") or "").strip()
            comment = (row.get("Client Comment") or "").strip()
            client_ip = (row.get("IP Address") or "").strip() or (row.get("IP") or "").strip()

            decision_time = _parse_iso_timestamp((row.get("Timestamp") or "").strip())

            key = (
                str(proof.id),
                status,
                approver,
                comment,
                decision_time.isoformat() if decision_time else "",
            )
            if key in existing_decision_keys:
                continue

            decision = Decision(
                proof=proof,
                proof_version=proof.versions[0] if proof.versions else None,
                status=status,
                approver_name=approver,
                client_comment=comment,
                client_ip=client_ip,
            )
            if decision_time:
                decision.created_at = decision_time
                decision.updated_at = decision_time

            session.add(decision)
            existing_decision_keys.add(key)
            created_decisions += 1

        if dry_run:
            session.rollback()
        else:
            try:
                session.commit()
            except SQLAlchemyError as err:
                session.rollback()
                click.echo(f"Import failed: {err}")
                return

    click.echo(f"Legacy jobs processed: {len(jobs)}")
    click.echo(f"  Users created: {created_users}")
    click.echo(f"  Designers created: {created_designers}")
    click.echo(f"  Proofs created: {created_proofs}")
    click.echo(f"  Versions created: {created_versions}")
    click.echo(f"  Decisions created: {created_decisions}")
    click.echo(f"  Proofs skipped (already present): {skipped_existing}")
    if missing_files:
        click.echo(f"  Missing proof files: {len(set(missing_files))} (see logs above)")
    if missing_proofs_for_decisions:
        click.echo(f"  Decisions with no proof match: {len(set(missing_proofs_for_decisions))}")

    if dry_run:
        click.echo("No changes committed (dry run).")


if __name__ == "__main__":
    # Run the Flask application
    # In a production environment, use a WSGI server like Gunicorn or uWSGI
    app.run(host="0.0.0.0", port=5000, debug=True) # debug=True for development, set to False for production
