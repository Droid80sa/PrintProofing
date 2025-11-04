import csv
import json
import os
import uuid
from datetime import datetime
from io import StringIO
import io

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    abort,
    g,
    session,
    Response,
    current_app,
)
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Customer, Designer, NotificationTemplate, Proof, User
from app.user_import import import_users_from_csv
from app.utils import login_required, _user_smtp_settings, send_email_notification  # Import necessary functions from app.utils
from app.customer_bp import (
    InviteAlreadyPendingError,
    describe_invite_status,
    issue_customer_invite,
)
from app.customer_notifications import (
    CUSTOMER_UPLOAD_TEMPLATE_KEY,
    DEFAULT_BODY_TEMPLATE,
    DEFAULT_SUBJECT_TEMPLATE,
    PLACEHOLDER_TOKENS,
    default_body_template,
    default_subject_template,
)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route("/dashboard")
@login_required(role="admin")
def admin_dashboard():
    """Displays a dashboard of all proofs for administrators."""
    proofs = (
        Proof.query.order_by(Proof.updated_at.desc(), Proof.created_at.desc())
        .all()
    )

    job_entries = []
    for proof in proofs:
        latest_decision = proof.decisions[-1] if proof.decisions else None
        latest_version = proof.versions[-1] if proof.versions else None
        updated_at = proof.updated_at or proof.created_at
        created_at = proof.created_at
        decision_timestamp = latest_decision.created_at if latest_decision and latest_decision.created_at else None
        designer_name = proof.designer.display_name if proof.designer else None
        designer_email = proof.designer.user.email if proof.designer and proof.designer.user else ""
        if not designer_name and latest_version and latest_version.uploaded_by:
            designer_name = latest_version.uploaded_by.name
            if not designer_email and latest_version.uploaded_by.email:
                designer_email = latest_version.uploaded_by.email

        job_entries.append({
            "job_id": proof.share_id,
            "job_name": proof.job_name,
            "designer": designer_name or "Team",
            "designer_email": designer_email,
            "status": proof.status.capitalize() if proof.status else "Pending",
            "created_at": created_at,
            "created_at_display": created_at.strftime("%Y-%m-%d %H:%M") if created_at else "",
            "updated_at": updated_at,
            "updated_at_display": updated_at.strftime("%Y-%m-%d %H:%M") if updated_at else "",
            "decision_timestamp": decision_timestamp,
            "decision_timestamp_display": decision_timestamp.strftime("%Y-%m-%d %H:%M") if decision_timestamp else "",
            "approver_name": latest_decision.approver_name if latest_decision else "—",
            "client_comment": latest_decision.client_comment if latest_decision else "",
            "version_count": len(proof.versions),
            "link": url_for("show_proof", job_id=proof.share_id),
            "latest_file_name": latest_version.original_filename if latest_version else "",
        })

    # Legacy fallback logic removed for brevity in Blueprint, assuming data is migrated

    status_counts = {
        "total": len(job_entries),
        "approved": sum(1 for item in job_entries if item["status"].lower() == "approved"),
        "pending": sum(1 for item in job_entries if item["status"].lower() == "pending"),
        "declined": sum(1 for item in job_entries if item["status"].lower() == "declined"),
    }

    return render_template("admin_dashboard.html", jobs=job_entries, counts=status_counts)


@admin_bp.route("/users", methods=["GET", "POST"])
@login_required(role="admin")
def admin_users():
    """Admin view for managing users and designer profiles."""
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                email = (request.form.get("email") or "").strip().lower()
                name = (request.form.get("name") or "").strip()
                role = request.form.get("role") or "designer"
                password = (request.form.get("password") or "").strip()
                display_name = (request.form.get("designer_display_name") or name).strip()
                reply_to = (request.form.get("designer_reply_to") or email).strip()

                if not email or not name or not password:
                    raise ValueError("Email, name, and password are required.")

                if User.query.filter_by(email=email).first():
                    raise ValueError("A user with that email already exists.")

                user = User(
                    email=email,
                    name=name,
                    password_hash=generate_password_hash(password),
                    role=role,
                    is_active=True,
                )
                db.session.add(user)

                if role == "designer":
                    designer = Designer(
                        user=user,
                        display_name=display_name or name,
                        email=email,
                        reply_to_email=reply_to or email,
                        is_active=True,
                    )
                    db.session.add(designer)

                db.session.commit()
                flash(f"✅ Created {role} account for {email}.", "success")

            elif action == "toggle":
                user_id = request.form.get("user_id")
                if not user_id:
                    raise ValueError("Missing user identifier.")

                user = db.session.get(User, uuid.UUID(user_id))
                if not user:
                    raise ValueError("User not found.")

                user.is_active = not user.is_active
                db.session.commit()
                status = "activated" if user.is_active else "deactivated"
                flash(f"✅ User {user.email} {status}.", "success")

            elif action == "reset_password":
                user_id = request.form.get("user_id")
                new_password = (request.form.get("new_password") or "").strip()
                if not user_id or not new_password:
                    raise ValueError("User and new password are required.")

                user = db.session.get(User, uuid.UUID(user_id))
                if not user:
                    raise ValueError("User not found.")

                user.password_hash = generate_password_hash(new_password)
                db.session.commit()
                flash(f"✅ Password reset for {user.email}.", "success")

            elif action == "import_csv":
                uploaded = request.files.get("csv_file")
                delimiter_choice = request.form.get("delimiter") or "auto"
                skip_existing = request.form.get("skip_existing") == "1"

                if not uploaded or not uploaded.filename:
                    raise ValueError("Select a CSV file to upload.")

                raw = uploaded.read()
                if not raw:
                    raise ValueError("Uploaded CSV is empty.")

                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = raw.decode("utf-8")

                delimiter = None if delimiter_choice == "auto" else delimiter_choice
                summary = import_users_from_csv(
                    io.StringIO(text),
                    delimiter=delimiter,
                    skip_existing=skip_existing,
                    dry_run=False,
                )
                flash(
                    f"✅ Imported {summary.created} user(s); skipped {summary.skipped}.",
                    "success",
                )

            elif action == "update_role":
                user_id = request.form.get("user_id")
                new_role = request.form.get("role")
                if not user_id or new_role not in ("admin", "designer"):
                    raise ValueError("Valid user and role are required.")

                user = db.session.get(User, uuid.UUID(user_id))
                if not user:
                    raise ValueError("User not found.")

                if user.id == g.current_user.id:
                    raise ValueError("You cannot change your own role.")

                if user.role == new_role:
                    flash("No role change needed.", "info")
                else:
                    if new_role == "designer" and not user.designer_profile:
                        designer = Designer(
                            user=user,
                            display_name=user.name,
                            email=user.email,
                            reply_to_email=user.email,
                            is_active=True,
                        )
                        db.session.add(designer)
                    elif new_role == "admin" and user.designer_profile:
                        db.session.delete(user.designer_profile)

                    user.role = new_role
                    db.session.commit()
                    flash(f"✅ Updated role for {user.email} to {new_role}.", "success")

            elif action == "delete":
                user_id = request.form.get("user_id")
                if not user_id:
                    raise ValueError("User identifier required.")

                user = db.session.get(User, uuid.UUID(user_id))
                if not user:
                    raise ValueError("User not found.")

                if user.id == g.current_user.id:
                    raise ValueError("You cannot delete your own account.")

                if user.role == "admin" and User.query.filter_by(role="admin", is_active=True).count() == 1:
                    raise ValueError("Cannot delete the last active admin.")

                db.session.delete(user)
                db.session.commit()
                flash(f"✅ Deleted user {user.email}.", "success")

            else:
                flash("❌ Unknown action.", "error")

        except (ValueError, SQLAlchemyError) as err:
            db.session.rollback()
            flash(f"❌ {err}", "error")

    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", users=users)


@admin_bp.route("/users/<uuid:user_id>/edit", methods=["GET", "POST"])
@login_required(role="admin")
def admin_user_edit(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        role = request.form.get("role") or user.role
        designer_reply_to = (request.form.get("designer_reply_to") or "").strip()

        smtp_host = (request.form.get("smtp_host") or "").strip() or None
        smtp_port_raw = request.form.get("smtp_port")
        smtp_port = int(smtp_port_raw) if smtp_port_raw else None
        smtp_username = (request.form.get("smtp_username") or "").strip() or None
        smtp_password = request.form.get("smtp_password")
        smtp_sender = (request.form.get("smtp_sender") or "").strip() or None
        smtp_reply_to = (request.form.get("smtp_reply_to") or "").strip() or None
        smtp_use_tls = "smtp_use_tls" in request.form
        smtp_use_ssl = "smtp_use_ssl" in request.form

        if not name or not email:
            flash("Name and email are required.", "error")
            return render_template("admin_user_edit.html", user=user)

        existing = User.query.filter(User.email == email, User.id != user.id).first()
        if existing:
            flash("Another user already uses that email.", "error")
            return render_template("admin_user_edit.html", user=user)

        user.name = name
        user.email = email
        user.role = role
        user.smtp_host = smtp_host
        user.smtp_port = smtp_port
        user.smtp_username = smtp_username
        if smtp_password:
            user.smtp_password = smtp_password
        user.smtp_sender = smtp_sender
        user.smtp_reply_to = smtp_reply_to
        user.smtp_use_tls = smtp_use_tls
        user.smtp_use_ssl = smtp_use_ssl

        if role == "designer":
            if user.designer_profile is None:
                designer = Designer(
                    user=user,
                    display_name=name,
                    email=email,
                    reply_to_email=designer_reply_to or email,
                    is_active=True,
                )
                db.session.add(designer)
            else:
                user.designer_profile.display_name = name
                user.designer_profile.email = email
                user.designer_profile.reply_to_email = designer_reply_to or email
        else:
            if user.designer_profile:
                db.session.delete(user.designer_profile)

        try:
            db.session.commit()
            flash("✅ User updated.", "success")
            return redirect(url_for("admin.admin_users"))
        except SQLAlchemyError as err:
            db.session.rollback()
            flash(f"❌ Failed to update user: {err}", "error")

    return render_template("admin_user_edit.html", user=user)


@admin_bp.route("/users/<uuid:user_id>/smtp-test", methods=["POST"])
@login_required(role="admin")
def admin_user_smtp_test(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)

    test_email = (request.form.get("test_email") or "").strip()
    if not test_email:
        flash("Please provide a test recipient email.", "error")
        return redirect(url_for("admin.admin_user_edit", user_id=user_id))

    subject = "SMTP Test"
    body = (
        f"SMTP settings for {user.email} appear to be working.\n\n"
        f"Timestamp: {datetime.utcnow().isoformat()}"
    )

    try:
        send_email_notification(
            subject,
            body,
            test_email,
            user=user,
            fallback_sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
            async_send=False,
            allow_fallback=False,
        )
        user.smtp_last_test_status = "success"
        user.smtp_last_test_at = datetime.utcnow()
        user.smtp_last_error = None
        db.session.commit()
        flash("✅ Test email sent.", "success")
    except Exception as exc:
        user.smtp_last_test_status = "failed"
        user.smtp_last_test_at = datetime.utcnow()
        user.smtp_last_error = str(exc)[:500]
        db.session.commit()
        flash(f"❌ Failed to send test email: {exc}", "error")

    return redirect(url_for("admin.admin_user_edit", user_id=user_id))


@admin_bp.route("/customers", methods=["GET", "POST"])
@login_required(role="admin")
def admin_customers():
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                name = (request.form.get("name") or "").strip()
                company_name = (request.form.get("company_name") or "").strip()
                email = (request.form.get("email") or "").strip().lower()

                if not name or not email:
                    raise ValueError("Name and email are required.")

                if Customer.query.filter_by(email=email).first():
                    raise ValueError("A customer with that email already exists.")

                customer = Customer(
                    name=name,
                    company_name=company_name,
                    email=email,
                )
                db.session.add(customer)
                db.session.commit()
                flash(f"✅ Created customer {name}.", "success")

            elif action == "delete":
                customer_id = request.form.get("customer_id")
                if not customer_id:
                    raise ValueError("Customer identifier required.")

                customer = db.session.get(Customer, uuid.UUID(customer_id))
                if not customer:
                    raise ValueError("Customer not found.")

                db.session.delete(customer)
                db.session.commit()
                flash(f"✅ Deleted customer {customer.name}.", "success")

            else:
                flash("❌ Unknown action.", "error")

        except (ValueError, SQLAlchemyError) as err:
            db.session.rollback()
            flash(f"❌ {err}", "error")

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
        "admin_customers.html",
        customer_rows=customer_rows,
        portal_enabled=portal_enabled,
    )


@admin_bp.route("/customers/<uuid:customer_id>/edit", methods=["GET", "POST"])
@login_required(role="admin")
def admin_customer_edit(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer:
        abort(404)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        company_name = (request.form.get("company_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()

        if not name or not email:
            flash("Name and email are required.", "error")
            return render_template("admin_customer_edit.html", customer=customer)

        existing = Customer.query.filter(Customer.email == email, Customer.id != customer.id).first()
        if existing:
            flash("Another customer already uses that email.", "error")
            return render_template("admin_customer_edit.html", customer=customer)

        customer.name = name
        customer.company_name = company_name
        customer.email = email

        try:
            db.session.commit()
            flash("✅ Customer updated.", "success")
            return redirect(url_for("admin.admin_customers"))
        except SQLAlchemyError as err:
            db.session.rollback()
            flash(f"❌ Failed to update customer: {err}", "error")

    invite_status = describe_invite_status(customer)
    portal_enabled = current_app.config.get("CUSTOMER_LOGIN_ENABLED", False)
    return render_template(
        "admin_customer_edit.html",
        customer=customer,
        invite_status=invite_status,
        portal_enabled=portal_enabled,
    )


@admin_bp.route("/customers/<uuid:customer_id>/invite", methods=["POST"])
@login_required(role="admin")
def admin_customer_invite(customer_id):
    redirect_to = request.form.get("redirect") or url_for("admin.admin_customers")
    customer = db.session.get(Customer, customer_id)
    if not customer:
        abort(404)

    portal_enabled = current_app.config.get("CUSTOMER_LOGIN_ENABLED", False)
    if not portal_enabled:
        flash("Customer login is currently disabled.", "error")
        return redirect(redirect_to)

    credential = customer.credential
    if credential and credential.is_active:
        flash("Customer already has an active account.", "info")
        return redirect(redirect_to)

    try:
        issue_customer_invite(
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

    return redirect(redirect_to)


@admin_bp.route("/export")
@login_required(role="admin")
def export_csv():
    """Exports all approval data as a CSV file."""
    # Define CSV field names
    fieldnames = ["job_id", "job_name", "designer", "status", "timestamp", "client_comment", "approver_name"]
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    proofs = Proof.query.order_by(Proof.created_at.asc()).all()
    for proof in proofs:
        latest_decision = proof.decisions[-1] if proof.decisions else None
        writer.writerow({
            "job_id": proof.share_id,
            "job_name": proof.job_name,
            "designer": proof.designer.display_name if proof.designer else "",
            "status": proof.status,
            "timestamp": latest_decision.created_at.isoformat() if latest_decision and latest_decision.created_at else "",
            "client_comment": latest_decision.client_comment if latest_decision else "",
            "approver_name": latest_decision.approver_name if latest_decision else "",
        })

    output.seek(0) # Rewind the StringIO buffer to the beginning
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=proof-approvals.csv"}
    )


@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required(role="admin")
def admin_settings():
    """Allows administrators to configure branding settings."""
    admin_dir = current_app.config.get("ADMIN_DIR") or os.path.join(current_app.root_path, "admin")
    settings_path = os.path.join(admin_dir, "settings.json")

    if request.method == "POST":
        # Keys that are expected to be strings from the form
        string_keys = [
            "company_name", "primary_color", "email_footer",
            "background_color", "approve_button_color",
            "reject_button_color", "font_family", "general_button_color" # Added general_button_color
        ]

        for key in string_keys:
            # Safely get the value, ensuring it's treated as a string before stripping
            form_value = request.form.get(key)
            if form_value is not None:
                g.branding[key] = str(form_value).strip()
            # If form_value is None, it means the field wasn't submitted,
            # so we keep the existing setting or default.

        try:
            with open(settings_path, "w") as f:
                json.dump(g.branding, f, indent=2)
            flash("✅ Settings updated successfully!", "success")
        except Exception as e:
            flash(f"❌ Error saving settings: {e}", "error")

    return render_template("admin_settings.html", settings=g.branding)


@admin_bp.route("/notifications", methods=["GET", "POST"])
@login_required(role="admin")
def admin_notifications():
    template = NotificationTemplate.query.filter_by(key=CUSTOMER_UPLOAD_TEMPLATE_KEY).first()

    if request.method == "POST":
        if request.form.get("csrf_token") != session.get("csrf_token"):
            flash("❌ Invalid session token. Please try again.", "error")
            return redirect(url_for("admin.admin_notifications"))

        action = (request.form.get("action") or "save").strip().lower()

        if action == "reset":
            if template:
                db.session.delete(template)
                db.session.commit()
            flash("✅ Email template reset to defaults.", "success")
            return redirect(url_for("admin.admin_notifications"))

        subject_template = (request.form.get("subject_template") or "").strip()
        body_template = request.form.get("body_template") or ""

        if not subject_template:
            flash("❌ Subject is required.", "error")
        elif not body_template.strip():
            flash("❌ Email body is required.", "error")
        else:
            try:
                if not template:
                    template = NotificationTemplate(key=CUSTOMER_UPLOAD_TEMPLATE_KEY)
                    db.session.add(template)
                template.subject_template = subject_template
                template.body_template = body_template
                template.updated_by_user_id = getattr(g.current_user, "id", None)
                db.session.commit()
                flash("✅ Email template saved.", "success")
                return redirect(url_for("admin.admin_notifications"))
            except SQLAlchemyError as err:
                db.session.rollback()
                flash(f"❌ Failed to save template: {err}", "error")

    effective_subject = template.subject_template if template else default_subject_template()
    effective_body = template.body_template if template else default_body_template()

    return render_template(
        "admin_notifications.html",
        subject_template=effective_subject,
        body_template=effective_body,
        using_custom_template=template is not None,
        placeholder_tokens=PLACEHOLDER_TOKENS,
        default_subject=DEFAULT_SUBJECT_TEMPLATE,
        default_body=DEFAULT_BODY_TEMPLATE,
    )


@admin_bp.route("/disclaimer", methods=["GET", "POST"])
@login_required(role="admin")
def admin_disclaimer():
    """Allows administrators to edit the disclaimer text."""
    admin_dir = current_app.config.get("ADMIN_DIR") or os.path.join(current_app.root_path, "admin")
    disclaimer_path = os.path.join(admin_dir, "disclaimer.txt")

    if request.method == "POST":
        new_disclaimer_text = request.form.get("disclaimer", "")
        try:
            with open(disclaimer_path, "w") as f:
                f.write(new_disclaimer_text.strip())
            flash("✅ Disclaimer updated successfully!", "success")
        except Exception as e:
            flash(f"❌ Error saving disclaimer: {e}", "error")

    # Always read the current text from the file before rendering the template
    # This ensures that after a POST, the page displays the newly saved content.
    current_text = ""
    if os.path.exists(disclaimer_path):
        with open(disclaimer_path, "r") as f:
            current_text = f.read()

    return render_template("admin_disclaimer.html", disclaimer=current_text)


@admin_bp.route("/logo", methods=["GET", "POST"])
@login_required(role="admin")
def upload_logo():
    """Allows administrators to upload a company logo."""
    upload_dir = current_app.config.get("UPLOAD_DIR") or os.path.join(current_app.root_path, "static", "uploads")
    logo_path = os.path.join(upload_dir, "logo.png") # Standard path for the logo
    message = ""

    if request.method == "POST":
        file = request.files.get("logo")
        if file and file.filename: # Check if a file was actually submitted
            # Check for allowed extensions
            allowed_extensions = (".png", ".jpg", ".jpeg", ".svg")
            if file.filename.lower().endswith(allowed_extensions):
                try:
                    # Before saving, ensure the directory exists (already done at app startup, but good practice)
                    os.makedirs(upload_dir, exist_ok=True)
                    file.save(logo_path)
                    message = "✅ Logo uploaded successfully."
                    flash(message, "success")
                except Exception as e:
                    message = f"❌ Error saving logo: {e}"
                    flash(message, "error")
            else:
                message = "❌ Please upload a valid image file (PNG, JPG, JPEG, SVG)."
                flash(message, "error")
        else:
            message = "❌ No file selected for upload."
            flash("❌ No file selected for upload.", "warning")

    logo_exists = os.path.exists(logo_path)
    return render_template("admin_logo.html", message=message, logo_exists=logo_exists)


@admin_bp.route("/")
@login_required(role="admin")
def admin_home():
    """Admin home page."""
    return render_template("admin_home.html")


@admin_bp.route("/css", methods=["GET", "POST"])
@login_required(role="admin")
def edit_css():
    """Allows administrators to edit custom CSS."""
    base_dir = current_app.config.get("BASE_DIR") or current_app.root_path
    css_path = os.path.join(base_dir, "static", "style.css")
    current_css = ""
    if request.method == "POST":
        new_css = request.form.get("css", "")
        try:
            with open(css_path, "w") as f:
                f.write(new_css.strip())
            current_css = new_css
            flash("✅ Custom CSS updated successfully!", "success")
        except Exception as e:
            flash(f"❌ Error saving CSS: {e}", "error")
    else:
        # Load current custom CSS for GET request
        if os.path.exists(css_path):
            with open(css_path, "r") as f:
                current_css = f.read()

    return render_template("admin_css.html", css=current_css)
