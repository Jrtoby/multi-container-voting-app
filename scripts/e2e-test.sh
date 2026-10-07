#!/usr/bin/env bash
#
# End-to-end test of the complete Docker Compose environment (phase 5).
#
# Boots the full stack (postgres + redis + web + worker), then drives it over
# HTTP exactly as a browser would:
#   1. every container reports healthy and /health says both deps are ok
#   2. register + login + vote -> message shown, item lands on vote_queue
#   3. the worker drains the queue and the vote reaches Postgres
#   4. /results reflects the vote once the cache expires
#   5. a second vote is rejected (one vote per user)
#   6. /admin totals match
#   7. web + worker logs are the structured JSON we ship
# Finally it tears the containers down.
#
# All count assertions are DELTAS against a baseline read at startup, so the
# script passes against a database volume that already holds earlier data.
# The postgres_data volume is never removed.
#
# The service-free suites (app/tests, worker/tests) do NOT need Docker; this
# script is the complement that proves the containers wire together.
#
# Usage:
#   ./scripts/e2e-test.sh
#   KEEP_STACK=1 ./scripts/e2e-test.sh    # leave the stack running
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:5000}"
KEEP_STACK="${KEEP_STACK:-}"
READY_TIMEOUT="${READY_TIMEOUT:-180}"
WORKER_TIMEOUT="${WORKER_TIMEOUT:-45}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COOKIE_JAR="$(mktemp)"
STAMP="$(date +%Y%m%d%H%M%S)"
USERNAME="e2e-$STAMP"
PASSWORD="e2e-password-1!"

CHECKS=0
FAILURES=0

step() { printf '\n==> %s\n' "$1"; }

# assert_eq <actual> <expected> <message>
assert_eq() {
  CHECKS=$((CHECKS + 1))
  if [ "$1" = "$2" ]; then
    printf '  [PASS] %s\n' "$3"
  else
    FAILURES=$((FAILURES + 1))
    printf '  [FAIL] %s (got %s, want %s)\n' "$3" "$1" "$2"
  fi
}

# assert_ok <0 for success | non-zero for failure> <message>
assert_ok() {
  CHECKS=$((CHECKS + 1))
  if [ "$1" -eq 0 ]; then
    printf '  [PASS] %s\n' "$2"
  else
    FAILURES=$((FAILURES + 1))
    printf '  [FAIL] %s\n' "$2"
  fi
}

# assert_contains <haystack> <regex> <message>
assert_contains() {
  CHECKS=$((CHECKS + 1))
  if printf '%s' "$1" | grep -Eq "$2"; then
    printf '  [PASS] %s\n' "$3"
  else
    FAILURES=$((FAILURES + 1))
    printf '  [FAIL] %s\n' "$3"
  fi
}

# request <path> [--form "k=v k=v"] [--no-redirect]
# Sets STATUS and BODY (and LOCATION for form posts).
#
# Form posts never pass -L: curl 8.13 re-issues the redirect target as POST
# *without a body*, so Flask would see an empty form (bad login, choice=null
# votes). We read the 3xx Location and issue the follow-up GET ourselves,
# exactly like a browser. STATUS keeps the POST's own status code.
STATUS=""
BODY=""
LOCATION=""
request() {
  local path="$1" form="" no_redirect=""
  shift || true
  while [ $# -gt 0 ]; do
    case "$1" in
      --form) form="$2"; shift 2 ;;
      --no-redirect) no_redirect="1"; shift ;;
      *) shift ;;
    esac
  done

  local out hdr code post_code
  out="$(mktemp)"
  local args=(-sS -o "$out" -w '%{http_code}' -b "$COOKIE_JAR" -c "$COOKIE_JAR")
  if [ -n "$form" ]; then
    hdr="$(mktemp)"
    args+=(-D "$hdr" -X POST --data "$form")
    code="$(curl "${args[@]}" "$BASE_URL$path" 2>/dev/null || echo 000)"
    STATUS="$code"
    LOCATION="$(grep -i '^location:' "$hdr" | tail -n 1 | sed -e 's/^[Ll]ocation:[[:space:]]*//' -e 's/\r$//')"
    rm -f "$hdr"
    if [ -n "$LOCATION" ] && [ -z "$no_redirect" ]; then
      post_code="$STATUS"
      local loc="$LOCATION"
      request "${LOCATION#"$BASE_URL"}"
      STATUS="$post_code"
      LOCATION="$loc"
    else
      BODY="$(cat "$out")"
    fi
  else
    if [ -z "$no_redirect" ]; then args+=(-L); fi
    code="$(curl "${args[@]}" "$BASE_URL$path" 2>/dev/null || echo 000)"
    STATUS="$code"
    LOCATION=""
    BODY="$(cat "$out")"
  fi
  rm -f "$out"
}

# wait_until <timeout_seconds> <command...>
wait_until() {
  local timeout="$1"
  shift
  local deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  printf '  [WARN] timed out after %ss waiting for %s\n' "$timeout" "$*"
  return 1
}

all_healthy() {
  local ps
  ps="$(docker compose -f "$ROOT/docker-compose.yml" ps --format '{{.Service}} {{.Status}}' 2>/dev/null || true)"
  local service
  for service in db redis web worker; do
    printf '%s\n' "$ps" | grep -E "^$service " | grep -q 'healthy' || return 1
  done
}

sql_scalar() {
  docker compose -f "$ROOT/docker-compose.yml" exec -T db \
    psql -U "$DB_USER" -d "$DB_NAME" -tAc "$1" 2>/dev/null | tail -n 1 | tr -d '[:space:]'
}

compose_capture() {
  docker compose -f "$ROOT/docker-compose.yml" "$@" 2>/dev/null || true
}

results_show_counts() {
  request "/results"
  printf '%s' "$BODY" | grep -Eq "Flask: $EXPECT_A votes" &&
    printf '%s' "$BODY" | grep -Eq "Node.js: $EXPECT_B votes"
}

cleanup() {
  if [ -n "$KEEP_STACK" ]; then
    printf '\nStack left running (KEEP_STACK=1). Stop it with: docker compose down\n'
    return
  fi
  printf '\n==> Tearing the stack down (postgres_data volume is kept)\n'
  docker compose -f "$ROOT/docker-compose.yml" down >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$ROOT"
rm -f "$COOKIE_JAR"

step 'Starting the full stack (docker compose up -d --build)'
docker compose up -d --build

step "Waiting up to ${READY_TIMEOUT}s for all four containers to be healthy"
if wait_until "$READY_TIMEOUT" all_healthy; then
  assert_ok 0 'db, redis, web and worker all report healthy'
else
  assert_ok 1 'db, redis, web and worker all report healthy'
  step 'Diagnostics'
  docker compose ps || true
  printf '\n-- last 40 web log lines --\n'
  docker compose logs --no-color --tail=40 web || true
  printf '\nE2E FAILED: stack never became healthy\n'
  exit 1
fi

# Credentials come from the container, so a custom .env is honoured.
DB_USER="$(compose_capture exec -T db printenv POSTGRES_USER | tail -n 1 | tr -d '[:space:]')"
DB_NAME="$(compose_capture exec -T db printenv POSTGRES_DB | tail -n 1 | tr -d '[:space:]')"

step 'Baseline counts (assertions below are deltas against these)'
BASE_USERS="$(sql_scalar 'SELECT count(*) FROM "user"')"
BASE_VOTES="$(sql_scalar 'SELECT count(*) FROM vote')"
BASE_A="$(sql_scalar "SELECT count(*) FROM vote WHERE choice = 'A'")"
BASE_B="$(sql_scalar "SELECT count(*) FROM vote WHERE choice = 'B'")"
printf '  users=%s votes=%s (A=%s, B=%s)\n' "$BASE_USERS" "$BASE_VOTES" "$BASE_A" "$BASE_B"

EXPECT_A=$((BASE_A + 1))
EXPECT_B="$BASE_B"
EXPECT_VOTES=$((BASE_VOTES + 1))

step 'GET /health reports both dependencies'
request "/health"
assert_eq "$STATUS" 200 'status code 200'
assert_contains "$BODY" '"status"[[:space:]]*:[[:space:]]*"healthy"' 'body says status=healthy'
assert_contains "$BODY" '"database"[[:space:]]*:[[:space:]]*"ok"' 'database check is ok'
assert_contains "$BODY" '"redis"[[:space:]]*:[[:space:]]*"ok"' 'redis check is ok'

step "Register a fresh user ($USERNAME)"
request "/register" --form "username=$USERNAME&password=$PASSWORD"
assert_eq "$STATUS" 302 'register redirects with 302'
assert_contains "$LOCATION" '/login' 'register redirects to /login'
assert_contains "$BODY" 'Registration successful' 'registration succeeded'

step 'Log in'
request "/login" --form "username=$USERNAME&password=$PASSWORD"
assert_eq "$STATUS" 302 'login redirects with 302'
assert_contains "$LOCATION" '/vote' 'login redirects to /vote'
assert_contains "$BODY" "Hello, $USERNAME!" "session established (Hello, $USERNAME! shown)"

step 'GET /vote renders the seeded poll'
request "/vote"
assert_eq "$STATUS" 200 'status code 200'
assert_contains "$BODY" 'Which framework is better\?' 'seeded poll question present'

step 'Cast a vote (choice A) — queued for the worker, never written directly'
request "/vote" --form 'choice=A'
assert_eq "$STATUS" 302 'vote redirects with 302'
assert_contains "$LOCATION" '/results' 'vote redirects to /results'
assert_contains "$BODY" 'Vote submitted' 'vote accepted and queued'

step 'Worker drains vote_queue and inserts into Postgres'
if wait_until "$WORKER_TIMEOUT" results_show_counts; then
  assert_ok 0 "/results shows Flask: $EXPECT_A / Node.js: $EXPECT_B (worker insert + cache refresh)"
else
  assert_ok 1 "/results shows Flask: $EXPECT_A / Node.js: $EXPECT_B (worker insert + cache refresh)"
fi

step 'Queue is empty and the row is in the database'
QUEUE_LEN="$(compose_capture exec -T redis redis-cli llen vote_queue | tail -n 1 | tr -d '[:space:]')"
assert_eq "$QUEUE_LEN" 0 'vote_queue is empty'

ROWS="$(sql_scalar 'SELECT count(*) FROM vote')"
assert_eq "$ROWS" "$EXPECT_VOTES" 'vote table holds baseline+1 rows'

step 'A second vote must be rejected'
request "/vote" --form 'choice=B'
assert_eq "$STATUS" 302 'second vote rejected with a redirect'
assert_contains "$BODY" 'already voted' 'second vote rejected with "already voted"'

ROWS="$(sql_scalar 'SELECT count(*) FROM vote')"
assert_eq "$ROWS" "$EXPECT_VOTES" 'still baseline+1 rows after the rejected vote'

step 'Admin dashboard totals'
request "/admin"
assert_eq "$STATUS" 200 'status code 200'
assert_contains "$BODY" "Total Registered Users: $((BASE_USERS + 1))" 'admin counts the new registration'
assert_contains "$BODY" "Total Votes Cast: $EXPECT_VOTES" 'admin counts the processed vote'

step 'Logs are structured JSON on both services'
WORKER_LOGS="$(compose_capture logs --no-color worker)"
WEB_LOGS="$(compose_capture logs --no-color web)"
assert_contains "$WORKER_LOGS" 'vote saved to database' 'worker logged "vote saved to database"'
assert_contains "$WORKER_LOGS" '"logger"[[:space:]]*:[[:space:]]*"voting.worker"' 'worker log lines are structured JSON'
assert_contains "$WEB_LOGS" 'vote queued' 'web logged the queue hand-off'
assert_contains "$WEB_LOGS" '"logger"[[:space:]]*:[[:space:]]*"voting.web"' 'web log lines are structured JSON'

rm -f "$COOKIE_JAR"
trap - EXIT

printf '\n'
if [ "$FAILURES" -gt 0 ]; then
  printf 'E2E FAILED: %s of %s checks failed\n' "$FAILURES" "$CHECKS"
  cleanup
  exit 1
fi
printf 'E2E PASSED: all %s checks passed\n' "$CHECKS"
cleanup
