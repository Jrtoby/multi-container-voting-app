"""The application must be able to reach Redis (queue + results cache)."""
import json

import app as app_module


def test_redis_ping(redis_client):
    assert redis_client.ping() is True


def test_queue_roundtrip(redis_client):
    """The exact hand-off the /vote route performs, read back the way the
    worker's BRPOP would see it."""
    vote = {"user_id": 1, "poll_id": 1, "choice": "A"}
    redis_client.lpush("vote_queue", json.dumps(vote))

    raw = redis_client.rpop("vote_queue")
    assert json.loads(raw) == vote
    assert redis_client.llen("vote_queue") == 0


def test_cache_roundtrip(redis_client):
    """SET/GET with a TTL, the way /results caches its aggregates."""
    redis_client.setex("results_cache", 10, json.dumps({"votes_a": 3, "votes_b": 2}))

    cached = json.loads(redis_client.get("results_cache"))
    assert cached == {"votes_a": 3, "votes_b": 2}
    ttl = redis_client.ttl("results_cache")
    assert 0 < ttl <= 10


def test_app_module_uses_the_fake(redis_client):
    """The autouse fixture must have replaced the module-level client, so no
    test can silently talk to a real Redis."""
    assert app_module.r is redis_client


def test_health_endpoint_reports_redis_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "healthy"
    assert body["checks"]["redis"] == "ok"
