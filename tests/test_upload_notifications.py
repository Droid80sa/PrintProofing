import io
import re

import pytest
from werkzeug.security import generate_password_hash

from app.app import app, SESSION_USER_ID
from app.extensions import db
from app.guest_access import pin_is_valid
from app.models import (
    Customer,
    CustomerAuthToken,
    CustomerCredential,
    CustomerNotification,
    Designer,
    Proof,
    ProofGuestAccess,
    User,
)
from app.storage import LocalStorage


@pytest.fixture
def upload_app(tmp_path):
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()

    app.config.update(
        TESTING=True,
        MAIL_SUPPRESS_SEND=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'test.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        CUSTOMER_LOGIN_ENABLED=False,
        FILE_STORAGE_ROOT=str(storage_dir),
    )

    import importlib

    app_module = importlib.import_module("app.app")

    original_storage = getattr(app_module, "storage_backend", None)
    app_module.storage_backend = LocalStorage(str(storage_dir))

    with app.app_context():
        engine = db.engine
        db.metadata.drop_all(bind=engine)
        db.metadata.create_all(bind=engine)

    yield

    with app.app_context():
        db.session.remove()
        engine = db.engine
        db.metadata.drop_all(bind=engine)

    app_module.storage_backend = original_storage


@pytest.fixture
def client(upload_app):
    with app.test_client() as test_client:
        yield test_client


def _create_accounts():
    user = User(
        email="designer@example.com",
        name="Lead Designer",
        password_hash=generate_password_hash("password123"),
        role="designer",
    )
    designer = Designer(
        user=user,
        display_name="Lead Designer",
        email="designer@example.com",
        reply_to_email="studio@example.com",
        is_active=True,
    )
    customer = Customer(
        name="Acme Corp",
        company_name="Acme",
        email="client@example.com",
    )
    db.session.add_all([user, designer, customer])
    db.session.commit()
    return user.id, designer.id, customer.id


def _login_session(client, user_id):
    with client.session_transaction() as session:
        session[SESSION_USER_ID] = str(user_id)
        session["csrf_token"] = "token"


def _post_upload(client, designer_id, customer_id, *, notify=False, subject="", body=""):
    data = {
        "designer_id": str(designer_id),
        "customer_id": str(customer_id),
        "job_name": "Brand Refresh",
        "notes": "Initial concept",
        "csrf_token": "token",
        "notify_subject": subject,
        "notify_body": body,
    }
    if notify:
        data["notify_customer"] = "on"

    data["file"] = (io.BytesIO(b"%PDF-1.4 fake"), "proof.pdf")

    response = client.post(
        "/upload",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    return response


def test_upload_without_notification_does_not_create_log(client, monkeypatch):
    with app.app_context():
        user_id, designer_id, customer_id = _create_accounts()

    _login_session(client, user_id)

    response = _post_upload(client, designer_id, customer_id, notify=False)
    assert response.status_code == 200
    assert b"Proof Uploaded Successfully" in response.data

    with app.app_context():
        assert CustomerNotification.query.count() == 0


def test_upload_with_notification_creates_log_and_sends(monkeypatch, client):
    with app.app_context():
        user_id, designer_id, customer_id = _create_accounts()

    def immediate(func, *args, **kwargs):
        kwargs.pop("meta", None)
        func(*args, **kwargs)

    from app.email_queue import EMAIL_QUEUE

    monkeypatch.setattr(EMAIL_QUEUE, "enqueue", immediate)

    _login_session(client, user_id)

    response = _post_upload(client, designer_id, customer_id, notify=True)
    assert response.status_code == 200
    assert b"Customer notification" in response.data

    with app.app_context():
        notifications = CustomerNotification.query.all()
        assert len(notifications) == 1
        notification = notifications[0]
        customer = db.session.get(Customer, customer_id)
        designer = db.session.get(Designer, designer_id)
        assert notification.recipient_email == customer.email
        assert notification.status in {"queued", "sent"}
        assert notification.subject
        assert "Brand Refresh" in notification.subject
        assert notification.body
        assert notification.proof.share_id in notification.body
        assert notification.sender_email == designer.email


def test_upload_with_custom_message(monkeypatch, client):
    with app.app_context():
        user_id, designer_id, customer_id = _create_accounts()

    from app.email_queue import EMAIL_QUEUE

    monkeypatch.setattr(
        EMAIL_QUEUE,
        "enqueue",
        lambda func, *args, **kwargs: func(*args, **{k: v for k, v in kwargs.items() if k != "meta"})
    )

    _login_session(client, user_id)

    custom_subject = "Proof ready for {{customer_name}}"
    custom_body = "Hello {{customer_name}},\nSee the proof here: {{proof_link}}\nThanks, {{designer_name}}"

    response = _post_upload(
        client,
        designer_id,
        customer_id,
        notify=True,
        subject=custom_subject,
        body=custom_body,
    )
    assert response.status_code == 200

    with app.app_context():
        notification = CustomerNotification.query.order_by(CustomerNotification.created_at.desc()).first()
        assert notification is not None
        assert notification.subject == "Proof ready for Acme Corp"
        assert "http" in notification.body
        assert "Acme Corp" in notification.body
        assert "{{" not in notification.body


def test_upload_creates_guest_access(monkeypatch, client):
    with app.app_context():
        user_id, designer_id, _customer_id = _create_accounts()

    monkeypatch.setattr("app.guest_access.generate_guest_token", lambda: "guest-token")
    monkeypatch.setattr("app.guest_access.generate_guest_pin", lambda: "123456")

    sent_email = {}

    def fake_send(subject, body, recipient, **kwargs):
        sent_email["subject"] = subject
        sent_email["body"] = body
        sent_email["recipient"] = recipient
        sent_email["html"] = kwargs.get("html_body")

    monkeypatch.setattr("app.utils.send_email_notification", fake_send)
    import importlib

    app_module = importlib.import_module("app.app")
    monkeypatch.setattr(app_module, "send_email_notification", fake_send)

    _login_session(client, user_id)

    data = {
        "designer_id": str(designer_id),
        "customer_id": "",
        "recipient_mode": "guest",
        "guest_email": "guest@example.com",
        "guest_name": "Guest Reviewer",
        "job_name": "Guest Review",
        "notes": "",
        "csrf_token": "token",
    }
    data["file"] = (io.BytesIO(b"%PDF-1.4 guest"), "proof.pdf")

    response = client.post(
        "/upload",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert b"Guest access PIN" in response.data
    assert b"123456" in response.data

    with app.app_context():
        proof = Proof.query.order_by(Proof.created_at.desc()).first()
        assert proof is not None
        assert proof.customer_id is None

        guest_access = ProofGuestAccess.query.filter_by(email="guest@example.com").first()
        assert guest_access is not None
        assert pin_is_valid(guest_access, "123456")

    assert sent_email.get("recipient") == "guest@example.com"
    assert "guest-token" in sent_email.get("body", "")
    assert "123456" in sent_email.get("body", "")


def test_guest_link_flow(monkeypatch, client):
    with app.app_context():
        user_id, designer_id, _customer_id = _create_accounts()

    monkeypatch.setattr("app.guest_access.generate_guest_token", lambda: "guest-token-flow")
    monkeypatch.setattr("app.guest_access.generate_guest_pin", lambda: "654321")

    _login_session(client, user_id)

    data = {
        "designer_id": str(designer_id),
        "customer_id": "",
        "recipient_mode": "guest",
        "guest_email": "flow@example.com",
        "guest_name": "Flow Tester",
        "job_name": "Guest Flow",
        "notes": "",
        "csrf_token": "token",
    }
    data["file"] = (io.BytesIO(b"%PDF-1.4 flow"), "proof.pdf")

    response = client.post(
        "/upload",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 200

    match = re.search(r'value="(http://[^"]+/customer/guest/[^"]+)"', response.get_data(as_text=True))
    assert match, "Expected guest link in upload success response"
    guest_link = match.group(1)
    assert guest_link.endswith("guest-token-flow")

    guest_client = app.test_client()
    get_resp = guest_client.get(guest_link)
    assert get_resp.status_code == 200
    csrf_match = re.search(r'name="csrf_token" value="([a-f0-9]+)"', get_resp.get_data(as_text=True))
    assert csrf_match, "Expected CSRF token in guest form"
    csrf_token = csrf_match.group(1)

    post_resp = guest_client.post(
        guest_link,
        data={"pin": "654321", "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert post_resp.status_code == 302
    assert post_resp.headers["Location"].endswith("/proof/" + post_resp.headers["Location"].split("/proof/")[-1])

    proof_resp = guest_client.get(post_resp.headers["Location"])
    assert proof_resp.status_code == 200
    assert b"Guest Flow" in proof_resp.data


def test_admin_upload_notify_self(monkeypatch, client):
    with app.app_context():
        admin = User(
            email="admin-upload@example.com",
            name="Admin Uploader",
            password_hash=generate_password_hash("adminpass"),
            role="admin",
            is_active=True,
        )
        admin.smtp_host = "smtp.example.com"
        admin.smtp_port = 587
        admin.smtp_username = "admin"
        admin.smtp_password = "secret"
        admin.smtp_use_tls = True
        admin.smtp_sender = "notifications@example.com"
        admin.smtp_reply_to = "notifications@example.com"
        customer = Customer(name="Contoso", company_name="Contoso Ltd", email="client@contoso.com")
        db.session.add_all([admin, customer])
        db.session.commit()
        admin_id = str(admin.id)
        customer_id = str(customer.id)

    def immediate(func, *args, **kwargs):
        kwargs.pop("meta", None)
        func(*args, **kwargs)

    from app.email_queue import EMAIL_QUEUE

    monkeypatch.setattr(EMAIL_QUEUE, "enqueue", immediate)

    with client.session_transaction() as session:
        session[SESSION_USER_ID] = admin_id
        session["csrf_token"] = "token"

    data = {
        "csrf_token": "token",
        "designer_id": "__self__",
        "customer_id": customer_id,
        "job_name": "Admin Upload",
        "notes": "",
        "notify_customer": "on",
        "notify_subject": "",
        "notify_body": "",
        "file": (io.BytesIO(b"%PDF-1.4 admin"), "proof.pdf"),
    }

    response = client.post("/upload", data=data, content_type="multipart/form-data", follow_redirects=False)
    assert response.status_code == 200

    with app.app_context():
        notification = CustomerNotification.query.order_by(CustomerNotification.created_at.desc()).first()
        assert notification is not None
        assert notification.sender_email == "notifications@example.com"
        assert notification.recipient_email == customer.email


def test_upload_notification_includes_invite_link_when_portal_enabled(monkeypatch, client):
    with app.app_context():
        user_id, designer_id, customer_id = _create_accounts()

    app.config["CUSTOMER_LOGIN_ENABLED"] = True

    from app.email_queue import EMAIL_QUEUE

    monkeypatch.setattr(
        EMAIL_QUEUE,
        "enqueue",
        lambda func, *args, **kwargs: func(*args, **{k: v for k, v in kwargs.items() if k != "meta"}),
    )

    _login_session(client, user_id)

    response = _post_upload(client, designer_id, customer_id, notify=True)
    assert response.status_code == 200

    with app.app_context():
        notification = CustomerNotification.query.order_by(CustomerNotification.created_at.desc()).first()
        assert notification is not None
        assert "/customer/invite/" in notification.body
        tokens = CustomerAuthToken.query.filter_by(customer_id=customer_id, purpose="invite").all()
        assert len(tokens) == 1


def test_upload_notification_skips_invite_when_customer_has_credentials(monkeypatch, client):
    with app.app_context():
        user_id, designer_id, customer_id = _create_accounts()
        credential = CustomerCredential(
            customer_id=customer_id,
            password_hash=generate_password_hash("AnotherSecret123"),
            is_active=True,
        )
        db.session.add(credential)
        db.session.commit()

    app.config["CUSTOMER_LOGIN_ENABLED"] = True

    from app.email_queue import EMAIL_QUEUE

    monkeypatch.setattr(
        EMAIL_QUEUE,
        "enqueue",
        lambda func, *args, **kwargs: func(*args, **{k: v for k, v in kwargs.items() if k != "meta"}),
    )

    _login_session(client, user_id)

    response = _post_upload(client, designer_id, customer_id, notify=True)
    assert response.status_code == 200

    with app.app_context():
        notification = CustomerNotification.query.order_by(CustomerNotification.created_at.desc()).first()
        assert notification is not None
        assert "/customer/invite/" not in notification.body
        assert CustomerAuthToken.query.filter_by(customer_id=customer_id).count() == 0
