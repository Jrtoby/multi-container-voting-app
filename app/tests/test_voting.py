"""Voting flow: queue hand-off plus one-vote-per-user enforcement.

The web tier never writes votes itself — it LPUSHes to Redis and the Node
worker does the INSERT. These tests therefore assert on the queue, and cover
the database-level backstop separately.
"""
import json

import pytest
from sqlalchemy.exc import IntegrityError

from models import Vote, db

from helpers import add_vote, create_user, login, seed_poll


def test_vote_is_queued_not_written(app, client, redis_client):
    user_id = create_user(app, "voter-1")
    poll_id = seed_poll(app)
    login(client, "voter-1")

    response = client.post(
        "/vote", data={"choice": "A"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert b"Vote submitted" in response.data

    # On the queue for the worker...
    assert redis_client.llen("vote_queue") == 1
    queued = json.loads(redis_client.lpop("vote_queue"))
    assert queued == {"user_id": user_id, "poll_id": poll_id, "choice": "A"}

    # ...and not yet in the database.
    with app.app_context():
        assert Vote.query.count() == 0


def test_vote_choice_b_is_queued(app, client, redis_client):
    create_user(app, "voter-b")
    seed_poll(app)
    login(client, "voter-b")

    client.post("/vote", data={"choice": "B"}, follow_redirects=True)

    queued = json.loads(redis_client.lpop("vote_queue"))
    assert queued["choice"] == "B"


def test_second_vote_rejected_once_recorded(app, client, redis_client):
    """Enforcement reads the vote table, so the worker must have drained the
    queue first — that is the production sequence, and we replicate it here."""
    user_id = create_user(app, "voter-2")
    poll_id = seed_poll(app)
    login(client, "voter-2")

    client.post("/vote", data={"choice": "A"}, follow_redirects=True)
    # Simulate the worker draining the queue and writing the row.
    redis_client.lpop("vote_queue")
    add_vote(app, user_id, poll_id, "A")

    response = client.post("/vote", data={"choice": "B"}, follow_redirects=True)
    assert b"already voted" in response.data

    # The rejected vote must not be queued for the worker either.
    assert redis_client.llen("vote_queue") == 0
    with app.app_context():
        assert Vote.query.count() == 1


def test_invalid_choice_is_never_queued(app, client, redis_client):
    """A missing/garbage choice would become a NOT NULL violation in the
    worker, so the web tier must refuse to enqueue it."""
    create_user(app, "voter-junk")
    seed_poll(app)
    login(client, "voter-junk")

    for payload in ({}, {"choice": ""}, {"choice": "Z"}):
        response = client.post("/vote", data=payload, follow_redirects=True)
        assert response.status_code == 200
        assert b"Please choose one of the options" in response.data

    assert redis_client.llen("vote_queue") == 0
    with app.app_context():
        assert Vote.query.count() == 0


def test_database_rejects_duplicate_user_poll(app):
    """Even if the queue is replayed or two votes race, the unique
    constraint on (user_id, poll_id) is the final backstop."""
    user_id = create_user(app, "voter-3")
    poll_id = seed_poll(app)
    add_vote(app, user_id, poll_id, "A")

    with app.app_context():
        db.session.add(Vote(user_id=user_id, poll_id=poll_id, choice="B"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_vote_creates_default_poll_when_missing(app, client, redis_client):
    """A database emptied under a running app still serves /vote."""
    create_user(app, "voter-4")
    login(client, "voter-4")

    response = client.get("/vote")
    assert response.status_code == 200
    assert b"Which framework is better?" in response.data


def test_vote_requires_login(client):
    response = client.post("/vote", data={"choice": "A"})
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
