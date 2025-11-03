import pytest
from werkzeug.security import generate_password_hash

from app.app import app, SESSION_USER_ID
from app.extensions import db
from app.models import Customer, Designer, User


@pytest.fixture
def designer_customer_app(tmp_path):
    app.config.update(
        TESTING=True,
        MAIL_SUPPRESS_SEND=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'designer.db'}",
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
def client(designer_customer_app):
    with app.test_client() as test_client:
        yield test_client


def _create_designer(email: str = "designer@example.com", name: str = "Designer") -> str:
    user = User(
        email=email,
        name=name,
        password_hash=generate_password_hash("secret"),
        role="designer",
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()
    designer = Designer(
        user=user,
        display_name=name,
        email=email,
        reply_to_email=email,
        is_active=True,
    )
    db.session.add(designer)
    db.session.commit()
    return str(user.id)


def test_designer_can_manage_customers(client):
    with app.app_context():
        designer_id = _create_designer()

    with client.session_transaction() as session:
        session[SESSION_USER_ID] = designer_id
        session["csrf_token"] = "token"

    response = client.post(
        "/designer/customers",
        data={
            "csrf_token": "token",
            "action": "create",
            "name": "Acme Corp",
            "company_name": "Acme",
            "email": "hello@acme.com",
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 302)

    with app.app_context():
        customer = Customer.query.filter_by(email="hello@acme.com").first()
        assert customer is not None
        customer_id = str(customer.id)

    response = client.post(
        f"/designer/customers/{customer_id}/edit",
        data={
            "csrf_token": "token",
            "name": "Acme Holdings",
            "company_name": "Acme Holdings",
            "email": "hello@acme.com",
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 302)

    with app.app_context():
        updated = Customer.query.filter_by(email="hello@acme.com").first()
        assert updated.name == "Acme Holdings"

    response = client.post(
        "/designer/customers",
        data={
            "csrf_token": "token",
            "action": "delete",
            "customer_id": customer_id,
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 302)

    with app.app_context():
        assert Customer.query.filter_by(email="hello@acme.com").first() is None
