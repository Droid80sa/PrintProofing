import pytest
from werkzeug.security import generate_password_hash

import app.admin_bp as admin_bp_module
from app.app import app, SESSION_USER_ID
from app.extensions import db
from app.models import Designer, User
import sys


@pytest.fixture
def smtp_app(tmp_path):
    app.config.update(
        TESTING=True,
        MAIL_SUPPRESS_SEND=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'test.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    with app.app_context():
        engine = db.engine
        db.metadata.drop_all(bind=engine)
        db.metadata.create_all(bind=engine)

    yield

    with app.app_context():
        db.session.remove()
        engine = db.engine
        db.metadata.drop_all(bind=engine)


@pytest.fixture
def client(smtp_app):
    with app.test_client() as test_client:
        yield test_client


def _create_user(role="designer", **kwargs):
    user = User(
        email=kwargs.get("email", "user@example.com"),
        name=kwargs.get("name", "User"),
        password_hash=generate_password_hash("secret"),
        role=role,
        is_active=True,
    )
    user.smtp_host = kwargs.get("smtp_host", "smtp.example.com")
    user.smtp_port = kwargs.get("smtp_port", 587)
    user.smtp_username = kwargs.get("smtp_username", "user")
    user.smtp_password = kwargs.get("smtp_password", "pass")
    user.smtp_use_tls = kwargs.get("smtp_use_tls", True)
    user.smtp_sender = kwargs.get("smtp_sender", user.email)
    user.smtp_reply_to = kwargs.get("smtp_reply_to", user.email)
    db.session.add(user)
    db.session.flush()
    if role == "designer":
        designer = Designer(
            user=user,
            display_name=user.name,
            email=user.email,
            reply_to_email=user.email,
            is_active=True,
        )
        db.session.add(designer)
    db.session.commit()
    return user.id


def test_admin_smtp_test_success(monkeypatch, client):
    with app.app_context():
        admin_id = _create_user(role="admin", email="admin@example.com", name="Admin")
        target_user_id = _create_user(role="designer", email="designer@example.com", name="Designer")

    sent = {}

    def fake_send(subject, body, to_address, **kwargs):
        sent.update({"subject": subject, "body": body, "to": to_address, **kwargs})

    monkeypatch.setattr(admin_bp_module, "send_email_notification", fake_send)

    with client.session_transaction() as session:
        session[SESSION_USER_ID] = str(admin_id)
        session["csrf_token"] = "token"

    response = client.post(
        f"/admin/users/{target_user_id}/smtp-test",
        data={"csrf_token": "token", "test_email": "test@example.com"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        refreshed = db.session.get(User, target_user_id)
        assert refreshed.smtp_last_test_status == "success"
        assert refreshed.smtp_last_test_at is not None
        assert refreshed.smtp_last_error is None


def test_admin_smtp_test_failure(monkeypatch, client):
    with app.app_context():
        admin_id = _create_user(role="admin", email="admin2@example.com", name="Admin")
        target_user_id = _create_user(role="designer", email="designer2@example.com", name="Designer")

    def failing_send(*args, **kwargs):
        raise RuntimeError("SMTP authentication failed")

    monkeypatch.setattr(admin_bp_module, "send_email_notification", failing_send)

    with client.session_transaction() as session:
        session[SESSION_USER_ID] = str(admin_id)
        session["csrf_token"] = "token"

    response = client.post(
        f"/admin/users/{target_user_id}/smtp-test",
        data={"csrf_token": "token", "test_email": "test@example.com"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        refreshed = db.session.get(User, target_user_id)
        assert refreshed.smtp_last_test_status == "failed"
        assert refreshed.smtp_last_test_at is not None
        assert refreshed.smtp_last_error.startswith("SMTP authentication failed")


def test_designer_smtp_test_success(monkeypatch, client):
    with app.app_context():
        designer_id = _create_user(role="designer", email="designer3@example.com", name="Designer 3")

    monkeypatch.setattr(sys.modules["app.app"], "send_email_notification", lambda *args, **kwargs: None)

    with client.session_transaction() as session:
        session[SESSION_USER_ID] = str(designer_id)
        session["csrf_token"] = "token"

    response = client.post(
        "/designer/smtp-test",
        data={"csrf_token": "token", "test_email": "alt@example.com"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        refreshed = db.session.get(User, designer_id)
        assert refreshed.smtp_last_test_status == "success"
        assert refreshed.smtp_last_error is None


def test_designer_smtp_test_failure(monkeypatch, client):
    with app.app_context():
        designer_id = _create_user(role="designer", email="designer4@example.com", name="Designer 4")

    def raise_error(*args, **kwargs):
        raise RuntimeError("Invalid credentials")

    monkeypatch.setattr(sys.modules["app.app"], "send_email_notification", raise_error)

    with client.session_transaction() as session:
        session[SESSION_USER_ID] = str(designer_id)
        session["csrf_token"] = "token"

    response = client.post(
        "/designer/smtp-test",
        data={"csrf_token": "token", "test_email": "alt@example.com"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        refreshed = db.session.get(User, designer_id)
        assert refreshed.smtp_last_test_status == "failed"
        assert refreshed.smtp_last_error.startswith("Invalid credentials")
