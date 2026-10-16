"""CSRF protection and the `flask create-admin` provisioning command.

CSRF is disabled in conftest's `app` fixture for the rest of the suite; the
`csrf_enabled` fixture below turns it back on to prove the guard fires.
"""
import re

import pytest

from helpers import create_user

from models import User


@pytest.fixture()
def csrf_enabled(app):
    app.config["WTF_CSRF_ENABLED"] = True
    yield app
    app.config["WTF_CSRF_ENABLED"] = False


def _csrf_token(client, path):
    page = client.get(path)
    match = re.search(rb'name="csrf_token"\s+value="([^"]+)"', page.data)
    assert match, f"no csrf_token field rendered on {path}"
    return match.group(1).decode()


def test_post_without_csrf_token_is_rejected(csrf_enabled, client):
    response = client.post(
        "/login",
        data={"username": "anyone", "password": "anything"},
    )
    assert response.status_code == 400


def test_register_post_without_csrf_token_is_rejected(csrf_enabled, client):
    response = client.post(
        "/register",
        data={"username": "anyone", "password": "anything"},
    )
    assert response.status_code == 400


def test_vote_post_without_csrf_token_is_rejected(csrf_enabled, client):
    create_user(client.application, "csrf-voter")
    token = _csrf_token(client, "/login")
    client.post(
        "/login",
        data={"username": "csrf-voter", "password": "s3cret-password", "csrf_token": token},
    )

    response = client.post("/vote", data={"choice": "A"})
    assert response.status_code == 400


def test_login_with_valid_csrf_token_succeeds(csrf_enabled, client):
    create_user(client.application, "csrf-ok")
    token = _csrf_token(client, "/login")

    response = client.post(
        "/login",
        data={"username": "csrf-ok", "password": "s3cret-password", "csrf_token": token},
    )
    assert response.status_code == 302
    assert "/vote" in response.headers["Location"]


# --- flask create-admin ---


def test_cli_create_admin_creates_role(app):
    runner = app.test_cli_runner()
    result = runner.invoke(
        args=["create-admin", "--username", "root", "--password", "root-password"]
    )
    assert result.exit_code == 0
    assert 'created admin account "root"' in result.output

    with app.app_context():
        user = User.query.filter_by(username="root").one()
        assert user.is_admin is True
        assert user.check_password("root-password")


def test_cli_create_admin_is_idempotent(app):
    runner = app.test_cli_runner()
    args = ["create-admin", "--username", "root", "--password", "root-password"]
    runner.invoke(args=args)
    result = runner.invoke(args=args)

    assert result.exit_code == 0
    assert "already up to date" in result.output
    with app.app_context():
        assert User.query.filter_by(username="root").count() == 1


def test_cli_create_admin_promotes_existing_user(app):
    create_user(app, "promoted")
    runner = app.test_cli_runner()
    result = runner.invoke(
        args=["create-admin", "--username", "promoted", "--password", "new-password"]
    )

    assert result.exit_code == 0
    with app.app_context():
        user = User.query.filter_by(username="promoted").one()
        assert user.is_admin is True
        assert user.check_password("new-password")


def test_cli_create_admin_reads_environment(app, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "env-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "env-password")

    result = app.test_cli_runner().invoke(args=["create-admin"])
    assert result.exit_code == 0
    with app.app_context():
        user = User.query.filter_by(username="env-admin").one()
        assert user.is_admin is True


def test_cli_create_admin_skips_when_unconfigured(app, monkeypatch):
    """No ADMIN_PASSWORD in the environment: exit 0, create nothing, so a
    default boot keeps /admin locked instead of failing or inventing a
    weak credential."""
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    result = app.test_cli_runner().invoke(args=["create-admin"])
    assert result.exit_code == 0
    assert "skipping admin provisioning" in result.output
    with app.app_context():
        assert User.query.count() == 0
