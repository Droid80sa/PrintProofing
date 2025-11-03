import html
import os
import re
import uuid
from datetime import datetime
from typing import Optional

from flask import current_app

from app.email_queue import EMAIL_QUEUE
from app.extensions import db
from app.models import (
    Customer,
    CustomerNotification,
    NotificationTemplate,
    Proof,
    ProofVersion,
    User,
)
from app.utils import send_email_notification


DEFAULT_SUBJECT_TEMPLATE = "New proof ready: {{job_name}}"
DEFAULT_BODY_TEMPLATE = (
    "Hi {{customer_name}},\n\n"
    "A new proof \"{{job_name}}\" is ready for your review.\n"
    "You can view it here: {{proof_link}}\n\n"
    "If you have feedback, feel free to leave a comment directly on the approval page.\n\n"
    "Regards,\n"
    "{{designer_name}}"
)

CUSTOMER_UPLOAD_TEMPLATE_KEY = "customer_upload"
PLACEHOLDER_TOKENS = (
    "{{customer_name}}",
    "{{job_name}}",
    "{{proof_link}}",
    "{{designer_name}}",
    "{{invite_link}}",
    "{{guest_pin}}",
)


def _template_from_env(var_name: str, fallback: str) -> str:
    value = os.getenv(var_name)
    if value:
        return value
    return fallback


def _configured_template() -> Optional[NotificationTemplate]:
    try:
        return NotificationTemplate.query.filter_by(key=CUSTOMER_UPLOAD_TEMPLATE_KEY).first()
    except Exception:  # pragma: no cover - table may not exist during migrations
        return None


def default_subject_template() -> str:
    configured = _configured_template()
    if configured and configured.subject_template:
        return configured.subject_template
    return _template_from_env("CUSTOMER_NOTIFY_DEFAULT_SUBJECT", DEFAULT_SUBJECT_TEMPLATE)


def default_body_template() -> str:
    configured = _configured_template()
    if configured and configured.body_template:
        return configured.body_template
    return _template_from_env("CUSTOMER_NOTIFY_DEFAULT_BODY", DEFAULT_BODY_TEMPLATE)


_HTML_BREAK_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _looks_like_html(value: str) -> bool:
    stripped = value.strip()
    return bool(_HTML_TAG_PATTERN.search(stripped))


def _html_to_text(value: str) -> str:
    text = _HTML_BREAK_PATTERN.sub("\n", value)
    text = _HTML_TAG_PATTERN.sub("", text)
    return html.unescape(text).strip()


def _render_template(template: str, context: dict[str, str]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def render_notification_content(
    *,
    subject_template: Optional[str],
    body_template: Optional[str],
    customer: Customer,
    proof: Proof,
    share_url: str,
    designer_name: str,
    invite_link: Optional[str] = None,
    extra_context: Optional[dict[str, str]] = None,
) -> tuple[str, str, Optional[str]]:
    subject_tpl = subject_template.strip() if subject_template else ""
    body_tpl = body_template.strip() if body_template else ""

    if not subject_tpl:
        subject_tpl = default_subject_template()
    if not body_tpl:
        body_tpl = default_body_template()

    context = {
        "customer_name": customer.name or customer.email,
        "job_name": proof.job_name,
        "proof_link": share_url,
        "designer_name": designer_name,
    }
    if invite_link:
        context["invite_link"] = invite_link
    else:
        context["invite_link"] = ""
    if extra_context:
        for key, value in extra_context.items():
            context[key] = value
    subject = _render_template(subject_tpl, context)
    body = _render_template(body_tpl, context)

    if invite_link:
        invite_link = invite_link.strip()
        if invite_link and invite_link not in body:
            if _looks_like_html(body):
                body = body.rstrip() + (
                    "<p>Set up your customer portal account here: "
                    f"<a href=\"{invite_link}\" target=\"_blank\" rel=\"noopener\">Activate account</a>"  # noqa: E501
                    "</p>"
                )
            else:
                normalized = body.rstrip()
                if normalized:
                    normalized += "\n\n"
                body = normalized + (
                    "Set up your customer portal account here: "
                    f"{invite_link}"
                )

    if _looks_like_html(body):
        body_html = body
        body_text = _html_to_text(body_html)
    else:
        body_html = None
        body_text = body

    return subject, body_text, body_html


def _deliver_notification(notification_id: str) -> None:
    """Worker entry point for sending a queued customer notification."""
    with current_app.app_context():
        try:
            notification_uuid = uuid.UUID(notification_id)
        except ValueError:
            return

        notification = db.session.get(CustomerNotification, notification_uuid)
        if not notification:
            return

        user = notification.smtp_user
        fallback_sender = notification.sender_email or current_app.config.get("MAIL_DEFAULT_SENDER")
        fallback_reply = notification.reply_to_email or current_app.config.get("MAIL_DEFAULT_REPLY_TO")

        body_content = notification.body
        html_body = body_content if _looks_like_html(body_content) else None
        body_text = _html_to_text(body_content) if html_body else body_content

        try:
            send_email_notification(
                notification.subject,
                body_text,
                notification.recipient_email,
                user=user,
                fallback_sender=fallback_sender,
                fallback_reply_to=fallback_reply,
                async_send=False,
                allow_fallback=True,
                html_body=html_body,
            )
            notification.status = "sent"
            notification.sent_at = datetime.utcnow()
            notification.error_message = None
        except Exception as exc:  # pragma: no cover - defensive fallback path
            notification.status = "failed"
            notification.error_message = str(exc)[:500]
        finally:
            db.session.commit()


def queue_customer_notification(
    *,
    proof: Proof,
    proof_version: ProofVersion,
    customer: Customer,
    uploader: Optional[User],
    smtp_user: Optional[User],
    share_url: str,
    subject_template: Optional[str],
    body_template: Optional[str],
    sender_email: Optional[str],
    reply_to_email: Optional[str],
    invite_link: Optional[str] = None,
) -> CustomerNotification:
    if not customer.email:
        raise ValueError("Customer email is required to send notifications.")

    designer_name = proof.designer.display_name if proof.designer else (uploader.name if uploader else "Your team")
    subject, body_text, body_html = render_notification_content(
        subject_template=subject_template,
        body_template=body_template,
        customer=customer,
        proof=proof,
        share_url=share_url,
        designer_name=designer_name,
        invite_link=invite_link,
    )
    stored_body = body_html or body_text

    notification = CustomerNotification(
        proof=proof,
        proof_version=proof_version,
        customer=customer,
        sent_by=uploader,
        smtp_user=smtp_user,
        subject=subject,
        body=stored_body,
        recipient_email=customer.email,
        sender_email=sender_email,
        reply_to_email=reply_to_email,
        status="queued",
        queued_at=datetime.utcnow(),
    )
    db.session.add(notification)
    db.session.flush()  # ensure ID assigned before queuing

    EMAIL_QUEUE.enqueue(
        _deliver_notification,
        str(notification.id),
        meta={
            "notification_id": str(notification.id),
            "proof_id": str(proof.id),
            "customer_email": customer.email,
            "subject": subject,
            "has_html": bool(body_html),
        },
    )
    return notification
