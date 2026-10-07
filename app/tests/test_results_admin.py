"""Results page (DB path, cache path) and the admin dashboard."""
import json

from helpers import add_vote, create_user, login, seed_poll


def test_results_without_poll(client):
    response = client.get("/results")
    assert response.status_code == 200
    assert b"No polls available yet" in response.data


def test_results_counts_votes_from_database(app, client, redis_client):
    poll_id = seed_poll(app)
    user_a = create_user(app, "count-a")
    user_b = create_user(app, "count-b")
    user_c = create_user(app, "count-c")
    add_vote(app, user_a, poll_id, "A")
    add_vote(app, user_b, poll_id, "A")
    add_vote(app, user_c, poll_id, "B")

    response = client.get("/results")
    assert response.status_code == 200
    assert b"Flask: 2 votes" in response.data
    assert b"Node.js: 1 votes" in response.data

    # A cache miss must populate the cache for the next reader.
    assert redis_client.get("results_cache") is not None
    assert 0 < redis_client.ttl("results_cache") <= 10


def test_results_served_from_cache(app, client, redis_client):
    """Cache hit wins over the database: seed a cache value that deliberately
    disagrees with the table, and the page must show the cached numbers."""
    poll_id = seed_poll(app)
    user = create_user(app, "cache-user")
    add_vote(app, user, poll_id, "A")
    redis_client.setex(
        "results_cache", 10, json.dumps({"votes_a": 99, "votes_b": 0})
    )

    response = client.get("/results")
    assert b"Flask: 99 votes" in response.data
    assert b"Node.js: 0 votes" in response.data


def test_results_cache_hit_does_not_rewrite_cache(client, redis_client):
    """A hit must skip the DB branch entirely — proven by the TTL surviving
    untouched (the miss branch would SETEX it back to a fresh 10s)."""
    seed_poll(client.application)
    redis_client.setex("results_cache", 10, json.dumps({"votes_a": 1, "votes_b": 1}))
    redis_client.expire("results_cache", 3)

    assert client.get("/results").status_code == 200
    assert 0 < redis_client.ttl("results_cache") <= 3


def test_admin_shows_totals(app, client):
    poll_id = seed_poll(app)
    create_user(app, "admin-user-1")
    voter_id = create_user(app, "admin-user-2")
    add_vote(app, voter_id, poll_id, "A")

    login(client, "admin-user-1")
    response = client.get("/admin")
    assert response.status_code == 200
    assert b"Total Registered Users: 2" in response.data
    assert b"Total Votes Cast: 1" in response.data


def test_admin_requires_login(client):
    response = client.get("/admin")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
