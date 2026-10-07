"""Registration, login, logout and access control."""
from models import User, db

from helpers import create_user, login


def test_register_creates_hashed_user(app, client):
    response = client.post(
        "/register",
        data={"username": "bob", "password": "hunter2!"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Registration successful" in response.data

    with app.app_context():
        user = User.query.filter_by(username="bob").one()
        assert user.password_hash != "hunter2!"
        assert user.check_password("hunter2!")


def test_register_rejects_duplicate_username(app, client):
    create_user(app, "bob")

    response = client.post(
        "/register",
        data={"username": "bob", "password": "another-password"},
        follow_redirects=True,
    )
    assert b"Username already exists" in response.data

    with app.app_context():
        assert User.query.filter_by(username="bob").count() == 1


def test_login_with_correct_password(client):
    create_user(client.application, "carol")

    response = login(client, "carol")
    assert response.status_code == 200
    assert b"Hello, carol!" in response.data


def test_login_with_wrong_password(client):
    create_user(client.application, "dave")

    response = login(client, "dave", password="wrong-password")
    assert response.status_code == 200
    assert b"Invalid username or password" in response.data
    assert b"Hello, dave!" not in response.data


def test_login_with_unknown_user(client):
    response = login(client, "nobody")
    assert b"Invalid username or password" in response.data


def test_logout_clears_session(client):
    create_user(client.application, "erin")
    login(client, "erin")
    assert b"Hello, erin!" in client.get("/vote").data

    client.get("/logout", follow_redirects=True)
    # Now signed out: protected pages bounce to the login form.
    response = client.get("/vote")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_vote_requires_login(client):
    response = client.get("/vote")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_requires_login(client):
    response = client.get("/admin")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_results_page_is_public(client):
    """Results are readable anonymously; votes are not."""
    assert client.get("/results").status_code == 200
