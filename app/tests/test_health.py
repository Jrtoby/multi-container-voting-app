"""The /health endpoint is the compose healthcheck and the deployment
healthcheck, so it must check both dependencies and fail loudly."""
import app as app_module
from models import db


def test_healthy(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body == {
        "status": "healthy",
        "checks": {"database": "ok", "redis": "ok"},
    }


def test_database_failure_returns_500(app, client, monkeypatch):

    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("connection refused")

        def remove(self):
            # Flask-SQLAlchemy tears the session down after every request.
            pass

    monkeypatch.setattr(db, "session", BrokenSession())

    response = client.get("/health")
    assert response.status_code == 500
    body = response.get_json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"].startswith("fail:")
    assert body["checks"]["redis"] == "ok"


def test_redis_failure_returns_500(client, monkeypatch):

    def broken_ping():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(app_module.r, "ping", broken_ping)

    response = client.get("/health")
    assert response.status_code == 500
    body = response.get_json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"].startswith("fail:")
