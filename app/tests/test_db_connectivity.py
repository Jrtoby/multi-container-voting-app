"""The application must be able to reach its primary datastore."""
from sqlalchemy import text

from models import User, db

from helpers import create_user


def test_select_one(db):
    db.session.execute(text("SELECT 1"))


def test_user_roundtrip(app, db):
    user_id = create_user(app, "db-roundtrip")
    fetched = db.session.query(User).filter_by(id=user_id).one()
    assert fetched.username == "db-roundtrip"
    assert fetched.check_password("s3cret-password")
    # The stored value must be a hash, never the plaintext.
    assert fetched.password_hash != "s3cret-password"


def test_health_endpoint_reports_database_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "healthy"
    assert body["checks"]["database"] == "ok"
