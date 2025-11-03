import uuid

import pytest
from werkzeug.security import generate_password_hash

from app.app import app, SESSION_USER_ID
from app.extensions import db
from app.models import Customer, CustomerAuthToken, Designer, User


@pytest.fixture
def invite_app(tmp_path, monkeypatch):
    app.config.update(
        TESTING=True,
        MAIL_SUPPRESS_SEND=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'invite.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        CUSTOMER_LOGIN_ENABLED=True,
    )

    from app.email_queue import EMAIL_QUEUE

    def immediate(func, *args, **kwargs):
        kwargs.pop("meta", None)
        func(*args, **kwargs)

    monkeypatch.setattr(EMAIL_QUEUE, "enqueue", immediate)

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
def client(invite_app):
    with app.test_client() as test_client:
        yield test_client


def _create_admin_and_customer():
    admin = User(
        email="admin@example.com",
        name="Admin",
        password_hash=generate_password_hash("secret"),
        role="admin",
        is_active=True,
    )
    customer = Customer(
        name="Portal Client",
        company_name="Portal Inc",
        email="client@example.com",
    )
    db.session.add_all([admin, customer])
    db.session.commit()
    return admin, customer


def _create_designer_and_customer():
    user = User(
        email="designer@example.com",
        name="Designer",
        password_hash=generate_password_hash("secret"),
        role="designer",
        is_active=True,
    )
    designer = Designer(
        user=user,
        display_name="Designer",
        email="designer@example.com",
        reply_to_email="studio@example.com",
        is_active=True,
    )
    customer = Customer(
        name="Invite Client",
        company_name="Invite LLC",
        email="invite@example.com",
    )
    db.session.add_all([user, designer, customer])
    db.session.commit()
    return user, customer


def _login_session(client, user_id: str):
    with client.session_transaction() as session:
        session[SESSION_USER_ID] = user_id
        session["csrf_token"] = "token"


def test_admin_can_send_customer_invite(client):
    with app.app_context():
        admin, customer = _create_admin_and_customer()
        admin_id = str(admin.id)
        customer_id = str(customer.id)

    _login_session(client, admin_id)

    response = client.post(
        f"/admin/customers/{customer_id}/invite",
        data={"csrf_token": "token", "redirect": "/admin/customers"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    with app.app_context():
        tokens = CustomerAuthToken.query.filter_by(
            customer_id=uuid.UUID(customer_id),
            purpose="invite",
        ).all()
        assert len(tokens) == 1
        assert tokens[0].issued_by_user_id == uuid.UUID(admin_id)


def test_admin_invite_prevents_duplicate_pending(client):
    with app.app_context():
        admin, customer = _create_admin_and_customer()
        admin_id = str(admin.id)
        customer_id = str(customer.id)

    _login_session(client, admin_id)

    client.post(
        f"/admin/customers/{customer_id}/invite",
        data={"csrf_token": "token", "redirect": "/admin/customers"},
    )
    response = client.post(
        f"/admin/customers/{customer_id}/invite",
        data={"csrf_token": "token", "redirect": "/admin/customers"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    with app.app_context():
        tokens = CustomerAuthToken.query.filter_by(
            customer_id=uuid.UUID(customer_id),
            purpose="invite",
        ).all()
        assert len(tokens) == 1


def test_designer_can_send_customer_invite(client):
    with app.app_context():
        designer_user, customer = _create_designer_and_customer()
        designer_id = str(designer_user.id)
        customer_id = str(customer.id)

    _login_session(client, designer_id)

    response = client.post(
        f"/designer/customers/{customer_id}/invite",
        data={"csrf_token": "token"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    with app.app_context():
        tokens = CustomerAuthToken.query.filter_by(
            customer_id=uuid.UUID(customer_id),
            purpose="invite",
        ).all()
        assert len(tokens) == 1
        assert tokens[0].issued_by_user_id == uuid.UUID(designer_id)
