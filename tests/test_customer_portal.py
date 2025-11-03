import pytest
from werkzeug.security import generate_password_hash

from app.app import app
from app.customer_bp import CUSTOMER_SESSION_KEY
from app.extensions import db
from app.models import Customer, CustomerCredential, Proof, ProofVersion


@pytest.fixture
def app_with_db(tmp_path):
    test_db = tmp_path / "test.db"
    app.config.update(
        TESTING=True,
        MAIL_SUPPRESS_SEND=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{test_db}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        CUSTOMER_LOGIN_ENABLED=True,
        LEGACY_PUBLIC_LINKS_ENABLED=False,
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
def client(app_with_db):
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def customer_record(app_with_db):
    with app.app_context():
        customer = Customer(
            name="Jane Doe",
            company_name="Acme Co",
            email="jane@example.com",
        )
        credential = CustomerCredential(
            customer=customer,
            password_hash=generate_password_hash("Sup3rSecret123"),
            is_active=True,
        )
        proof = Proof(
            share_id="share123",
            job_name="Brand Guide",
            status="pending",
            customer=customer,
        )
        version = ProofVersion(
            proof=proof,
            storage_path="share123.pdf",
            original_filename="share123.pdf",
        )
        db.session.add_all([customer, credential, proof, version])
        db.session.commit()

        return {
            "email": customer.email,
            "password": "Sup3rSecret123",
            "share_id": proof.share_id,
            "job_name": proof.job_name,
        }


def _login_customer(client, email, password):
    response = client.get("/customer/login")
    assert response.status_code == 200
    with client.session_transaction() as session:
        csrf_token = session["customer_csrf_token"]

    response = client.post(
        "/customer/login",
        data={"email": email, "password": password, "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/customer/dashboard")
    with client.session_transaction() as session:
        assert CUSTOMER_SESSION_KEY in session


def test_customer_routes_disabled_when_feature_off(client):
    app.config["CUSTOMER_LOGIN_ENABLED"] = False
    response = client.get("/customer/login")
    assert response.status_code == 404
    app.config["CUSTOMER_LOGIN_ENABLED"] = True


def test_proof_requires_login_when_enforced(client, customer_record):
    response = client.get(f"/proof/{customer_record['share_id']}")
    assert response.status_code == 302
    assert "/customer/login" in response.headers["Location"]


def test_customer_can_login_and_view_proof(client, customer_record):
    _login_customer(client, customer_record["email"], customer_record["password"])

    response = client.get(
        f"/customer/proof/{customer_record['share_id']}",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert f"Job: {customer_record['job_name']}".encode() in response.data


def test_customer_submission_updates_proof(client, customer_record):
    _login_customer(client, customer_record["email"], customer_record["password"])

    post_response = client.post(
        "/submit",
        data={
            "job_id": customer_record["share_id"],
            "decision": "approved",
            "approver_name": "Jane",
            "client_comment": "Looks great",
        },
        follow_redirects=True,
    )
    assert post_response.status_code == 200
    assert b"Thank you" in post_response.data

    with app.app_context():
        proof = Proof.query.filter_by(share_id=customer_record["share_id"]).first()
        assert proof is not None
        assert proof.status == "approved"
        assert proof.decisions
        assert proof.decisions[-1].approver_name == "Jane"
