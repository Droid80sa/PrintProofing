import smtplib
import ssl

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from typing import Optional

from flask import abort, current_app, flash, g, redirect, request, url_for

from app.models import User
from app.email_queue import EMAIL_QUEUE


def login_required(f=None, *, role=None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user = g.get("current_user")
            if not user:
                flash("Please log in to access this page.", "info")
                return redirect(url_for("login", next=request.path))
            if role and user.role != role:
                abort(403)
            return func(*args, **kwargs)

        return wrapper

    if f is None:
        return decorator
    return decorator(f)


def customer_login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        customer = g.get("current_customer")
        if not customer:
            flash("Please sign in to access this page.", "info")
            return redirect(url_for("customer.login", next=request.path))
        return func(*args, **kwargs)

    return wrapper


def _user_smtp_settings(user: Optional[User]) -> Optional[dict]:
    if not user or not user.smtp_host or not user.smtp_port:
        return None
    return {
        "host": user.smtp_host,
        "port": user.smtp_port,
        "username": user.smtp_username,
        "password": user.smtp_password,
        "use_tls": bool(user.smtp_use_tls),
        "use_ssl": bool(user.smtp_use_ssl),
        "sender": user.smtp_sender or user.email,
        "reply_to": user.smtp_reply_to or user.email,
    }


def _send_via_custom_smtp(
    subject: str,
    body: str,
    to_address: str,
    smtp_config: dict,
    *,
    html_body: Optional[str] = None,
) -> None:
    host = smtp_config["host"]
    port = smtp_config["port"]
    username = smtp_config.get("username")
    password = smtp_config.get("password")
    use_tls = smtp_config.get("use_tls")
    use_ssl = smtp_config.get("use_ssl")
    sender = smtp_config.get("sender")
    reply_to = smtp_config.get("reply_to")

    if not sender:
        raise ValueError("Custom SMTP configuration requires a sender address")

    if html_body is not None:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(body, "plain", "utf-8"))
        message.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        message = MIMEText(body, "plain", "utf-8")

    message["From"] = sender
    message["To"] = to_address
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to

    serialized = message.as_string().encode("utf-8")

    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, context=context) as server:
            if username and password:
                server.login(username, password)
            server.sendmail(sender, [to_address], serialized)
    else:
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            if use_tls:
                server.starttls(context=context)
                server.ehlo()
            if username and password:
                server.login(username, password)
            server.sendmail(sender, [to_address], serialized)


def _send_email_sync(
    subject: str,
    body: str,
    to_address: str,
    *,
    smtp_config: Optional[dict],
    fallback_sender: Optional[str],
    fallback_reply_to: Optional[str],
    allow_fallback: bool = True,
    html_body: Optional[str] = None,
) -> None:
    sender = fallback_sender or current_app.config.get("MAIL_DEFAULT_SENDER")
    reply_to = fallback_reply_to or current_app.config.get("MAIL_DEFAULT_REPLY_TO") or sender

    if smtp_config:
        smtp_config = smtp_config.copy()
        smtp_config.setdefault("sender", sender)
        smtp_config.setdefault("reply_to", reply_to)
        try:
            _send_via_custom_smtp(
                subject,
                body,
                to_address,
                smtp_config,
                html_body=html_body,
            )
            return
        except Exception as exc:
            print(f"Custom SMTP send failed ({smtp_config.get('host')}): {exc}.")
            if not allow_fallback:
                raise

    if not sender:
        raise RuntimeError("No sender configured for email notification")

    with current_app.app_context():
        # Assuming mail object is initialized globally or passed
        # For now, we'll assume mail is accessible via current_app.extensions['mail'] or similar
        # This part might need adjustment based on how Flask-Mail is truly initialized and accessed
        from flask_mail import Message, Mail
        mail = Mail(current_app)
        msg = Message(subject, recipients=[to_address], reply_to=reply_to)
        msg.body = body
        msg.sender = sender
        if html_body is not None:
            msg.html = html_body
        mail.send(msg)


def send_email_notification(
    subject: str,
    body: str,
    to_address: str,
    *,
    user: Optional[User] = None,
    fallback_sender: Optional[str] = None,
    fallback_reply_to: Optional[str] = None,
    async_send: bool = True,
    allow_fallback: bool = True,
    html_body: Optional[str] = None,
) -> None:
    smtp_config = _user_smtp_settings(user)
    if async_send:
        EMAIL_QUEUE.enqueue(
            _send_email_sync,
            subject,
            body,
            to_address,
            smtp_config=smtp_config,
            fallback_sender=fallback_sender,
            fallback_reply_to=fallback_reply_to,
            allow_fallback=allow_fallback,
            html_body=html_body,
            meta={"to": to_address, "subject": subject},
        )
    else:
        _send_email_sync(
            subject,
            body,
            to_address,
            smtp_config=smtp_config,
            fallback_sender=fallback_sender,
            fallback_reply_to=fallback_reply_to,
            allow_fallback=allow_fallback,
            html_body=html_body,
        )
