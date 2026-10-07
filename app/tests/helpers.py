"""Plain-function helpers shared by the test modules.

Kept out of conftest.py so test files can import them by name; conftest is
loaded by pytest itself and its contents are not meant to be a library.
"""
from models import Poll, User, Vote, db

import app as app_module


def create_user(app, username="alice", password="s3cret-password"):
    """Register a user directly through the model layer. Returns the id."""
    with app.app_context():
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        db.session.refresh(user)
        return user.id


def seed_poll(app):
    """Create the default poll if absent. Returns the poll id."""
    with app.app_context():
        poll = Poll.query.first()
        if poll is None:
            poll = Poll(**app_module.DEFAULT_POLL)
            db.session.add(poll)
            db.session.commit()
            db.session.refresh(poll)
        return poll.id


def add_vote(app, user_id, poll_id, choice):
    """Write a vote straight to the database, bypassing the Redis queue."""
    with app.app_context():
        vote = Vote(user_id=user_id, poll_id=poll_id, choice=choice)
        db.session.add(vote)
        db.session.commit()
        return vote.id


def login(client, username, password="s3cret-password"):
    """Perform a real POST /login so the session cookie is set."""
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
