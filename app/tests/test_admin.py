"""Admin authorisation: /admin is admin-only, with its own login door.

The bug these tests lock down: /admin used to sit behind @login_required
alone, so ANY registered user could open it. The contract now is
authentication (signed-in session) AND authorisation (user.is_admin).
"""
from helpers import create_admin, create_user, login

from models import User


def test_anonymous_admin_redirects_to_admin_login(client):
    response = client.get("/admin")
    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_admin_login_page_renders(client):
    response = client.get("/admin/login")
    assert response.status_code == 200
    assert b"Admin Login" in response.data


def test_logged_in_normal_user_cannot_open_admin(app, client):
    """The reported vulnerability: a random authenticated user hits /admin."""
    create_user(app, "mallory")
    login(client, "mallory")

    response = client.get("/admin")
    assert response.status_code == 403
    assert b"Total Registered Users" not in response.data


def test_normal_user_cannot_log_in_through_admin_door(app, client):
    """Valid user credentials must be useless on /admin/login."""
    create_user(app, "mallory", password="her-own-password")

    response = client.post(
        "/admin/login",
        data={"username": "mallory", "password": "her-own-password"},
    )
    assert response.status_code == 200
    assert b"Invalid admin username or password" in response.data
    # No session was established: /admin still bounces to the admin login.
    follow_up = client.get("/admin")
    assert follow_up.status_code == 302
    assert "/admin/login" in follow_up.headers["Location"]


def test_admin_logs_in_through_admin_door(app, client):
    create_admin(app, "root", password="root-password")

    response = client.post(
        "/admin/login",
        data={"username": "root", "password": "root-password"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Admin Dashboard" in response.data
    assert b"Total Registered Users" in response.data


def test_wrong_admin_password_is_rejected(app, client):
    create_admin(app, "root", password="root-password")

    response = client.post(
        "/admin/login",
        data={"username": "root", "password": "wrong"},
    )
    assert response.status_code == 200
    assert b"Invalid admin username or password" in response.data
    assert client.get("/admin").status_code == 302


def test_role_decides_access_not_the_login_door(app, client):
    """An admin who signed in through the *normal* /login still passes the
    role check — /admin gates on is_admin, not on which form was used."""
    create_admin(app, "root", password="root-password")
    login(client, "root", password="root-password")

    assert client.get("/admin").status_code == 200


def test_registration_never_grants_admin_role(app, client):
    client.post(
        "/register",
        data={"username": "fresh", "password": "fresh-password"},
        follow_redirects=True,
    )
    with app.app_context():
        user = User.query.filter_by(username="fresh").one()
        assert user.is_admin is False


def test_admin_nav_link_hidden_from_normal_users(app, client):
    create_user(app, "nav-guest")
    login(client, "nav-guest")

    assert b'href="/admin"' not in client.get("/vote").data


def test_admin_nav_link_shown_to_admins(app, client):
    create_admin(app, "nav-admin")
    login(client, "nav-admin")

    assert b'href="/admin"' in client.get("/vote").data
