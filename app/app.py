import os
import json
import logging
import redis
import click
from functools import wraps
from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import text
from models import db, User, Poll, Vote


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line — the same shape app/entrypoint.sh and the
    Node worker emit, so `docker compose logs web` is machine-parseable."""

    def format(self, record):
        entry = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def _configure_logging():
    """Attach a stdout-redirected JSON handler to the root logger.

    Guarded so it never clobbers handlers a server or test runner already
    installed; gunicorn captures stderr either way.
    """
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    root.addHandler(handler)


_configure_logging()
logger = logging.getLogger("voting.web")


# Single source of truth for the poll the app is seeded with. Normally created by
# `flask seed-poll` from app/entrypoint.sh; /vote falls back to it if the table
# is somehow empty.
DEFAULT_POLL = {
    "question": "Which framework is better?",
    "option_a": "Flask",
    "option_b": "Node.js",
}

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-key')
# The fallbacks below suit a run outside Docker. docker-compose.yml always
# injects the real values, so inside a container these are never used.
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'postgresql+psycopg2://voting_user:supersecretpassword@localhost:5432/voting_db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# 'localhost' inside a container is the container itself, so REDIS_HOST must be
# overridable — docker-compose.yml sets it to the 'redis' service name.
r = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    db=0,
    decode_responses=True,
)

db.init_app(app)
# Owns the schema. Alembic reads the engine from app.extensions['migrate'], which
# is what app/migrations/env.py expects.
migrate = Migrate(app, db)

# Rejects any POST that does not carry a valid per-session CSRF token. Every
# form template emits <input type="hidden" name="csrf_token"> via {{ csrf_token() }}.
# Disabled under TESTING so the suite can post plain dicts; test_security.py
# re-enables it to prove the guard actually fires.
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def admin_required(view):
    """Authentication is not authorisation.

    /admin needs BOTH a signed-in session AND the is_admin role:
      * anonymous        -> the dedicated admin login page (/admin/login)
      * signed-in normal -> 403, logged as a denied access attempt
    The role check reads user.is_admin, which only `flask create-admin` can
    ever set — registration never grants it.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('admin_login'))
        if not current_user.is_admin:
            logger.warning(
                "admin access denied: user_id=%s username=%s",
                current_user.id, current_user.username,
            )
            abort(403)
        return view(*args, **kwargs)

    return wrapped

# --- Routes ---

@app.route('/')
def index():
    return redirect(url_for('vote'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        logger.info("user registered: username=%s", username)
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and user.check_password(request.form.get('password')):
            login_user(user)
            logger.info("login succeeded: username=%s", user.username)
            return redirect(url_for('vote'))
        logger.warning("login failed: username=%s", request.form.get('username'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/vote', methods=['GET', 'POST'])
@login_required
def vote():
    poll = Poll.query.first()
    if not poll:
        # Fallback for a database emptied underneath a running app; the normal
        # path is `flask seed-poll` at boot.
        poll = Poll(**DEFAULT_POLL)
        db.session.add(poll)
        db.session.commit()

    if request.method == 'POST':
        choice = request.form.get('choice')
        # The queue message becomes a NOT NULL row, so never enqueue junk.
        if choice not in ('A', 'B'):
            logger.warning(
                "vote rejected: user_id=%s sent invalid choice=%r",
                current_user.id, choice,
            )
            flash('Please choose one of the options.')
            return redirect(url_for('vote'))
        # Enforce one vote per user
        existing_vote = Vote.query.filter_by(user_id=current_user.id, poll_id=poll.id).first()
        if existing_vote:
            logger.warning(
                "vote rejected: user_id=%s already voted on poll_id=%s",
                current_user.id, poll.id,
            )
            flash('You have already voted!')
        else:
            # Instead of writing to DB, push to Redis Queue
            vote_data = {
                'user_id': current_user.id,
                'poll_id': poll.id,
                'choice': choice
            }
            r.lpush('vote_queue', json.dumps(vote_data))
            logger.info(
                "vote queued: user_id=%s poll_id=%s choice=%s",
                current_user.id, poll.id, choice,
            )
            flash('Vote submitted! It will be processed shortly.')
        return redirect(url_for('results'))
    
    return render_template('vote.html', poll=poll)

@app.route('/results')
def results():
    poll = Poll.query.first()
    if not poll:
        return render_template('results.html', poll=None)
    
 # Check if we have cached results in Redis
    cached_results = r.get('results_cache')
    if cached_results:
        logger.info("results served from cache")
        data = json.loads(cached_results)
        return render_template('results.html', poll=poll, votes_a=data['votes_a'], votes_b=data['votes_b'])

    logger.info("results served from database")
    votes_a = Vote.query.filter_by(poll_id=poll.id, choice='A').count()
    votes_b = Vote.query.filter_by(poll_id=poll.id, choice='B').count()

 # Save to Redis cache for 10 seconds
    r.setex('results_cache', 10, json.dumps({'votes_a': votes_a, 'votes_b': votes_b}))

    return render_template('results.html', poll=poll, votes_a=votes_a, votes_b=votes_b)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Dedicated sign-in door for the admin section.

    Separate from /login on purpose: only accounts provisioned with the
    is_admin role are accepted here, and the credential check plus the role
    check happen together so a valid *user* password is never enough.
    """
    if current_user.is_authenticated:
        return redirect(url_for('admin') if current_user.is_admin else url_for('vote'))

    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.is_admin and user.check_password(password):
            login_user(user)
            logger.info("admin login succeeded: username=%s", username)
            return redirect(url_for('admin'))
        # One message for bad credentials and for missing role alike — the
        # page must not reveal which admin accounts exist.
        logger.warning("admin login denied: username=%s", username)
        flash('Invalid admin username or password')
    return render_template('admin_login.html')


@app.route('/admin')
@admin_required
def admin():
    total_users = User.query.count()
    total_votes = Vote.query.count()
    return render_template('admin.html', total_users=total_users, total_votes=total_votes)


@app.errorhandler(403)
def forbidden(error):
    return render_template(
        'error.html',
        code=403,
        message='Admin access required. This area is restricted to administrator accounts.',
    ), 403

@app.route('/health')
def health():
    """Readiness probe for Docker Compose, load balancers and the deploy
    workflow: both dependencies are checked, because /vote needs Redis and
    everything else needs Postgres."""
    checks = {}
    try:
        db.session.execute(text('SELECT 1'))
        checks['database'] = 'ok'
    except Exception as e:
        logger.error("health check failed: database unreachable: %s", e)
        checks['database'] = f'fail: {e}'
    try:
        r.ping()
        checks['redis'] = 'ok'
    except Exception as e:
        logger.error("health check failed: redis unreachable: %s", e)
        checks['redis'] = f'fail: {e}'

    healthy = all(value == 'ok' for value in checks.values())
    return {"status": "healthy" if healthy else "unhealthy", "checks": checks}, 200 if healthy else 500

@app.cli.command('seed-poll')
def seed_poll():
    """Create the default poll if the table is empty. Safe to run on every boot."""
    if Poll.query.first():
        print('poll already present; nothing to seed')
        return
    db.session.add(Poll(**DEFAULT_POLL))
    db.session.commit()
    print('seeded default poll')


@app.cli.command('create-admin')
@click.option('--username', default=None, help='Admin account name (default: $ADMIN_USERNAME).')
@click.option('--password', default=None, help='Admin password (default: $ADMIN_PASSWORD).')
def create_admin(username, password):
    """Create or promote the administrator account.

    The only code path that ever sets is_admin=True, so admin credentials are
    provisioned separately from public registration. With no arguments it reads
    ADMIN_USERNAME / ADMIN_PASSWORD from the environment (docker-compose.yml
    passes them from .env); if no password is available it exits 0 with a
    notice, which keeps /admin locked by default and never fails the boot.
    Safe to run repeatedly — existing admins are left untouched.
    """
    username = username or os.getenv('ADMIN_USERNAME', '')
    password = password or os.getenv('ADMIN_PASSWORD', '')

    if not username or not password:
        print(
            'ADMIN_USERNAME / ADMIN_PASSWORD not set; skipping admin '
            'provisioning — /admin stays locked until an admin is created.'
        )
        return

    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, is_admin=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        logger.info("admin created: username=%s", username)
        print(f'created admin account "{username}"')
        return

    changed = False
    if not user.is_admin:
        user.is_admin = True
        changed = True
    if not user.check_password(password):
        # The environment is the source of truth for the bootstrap account,
        # so a rotated ADMIN_PASSWORD takes effect on the next boot.
        user.set_password(password)
        changed = True
    if changed:
        db.session.commit()
        logger.info("admin provisioned: username=%s", username)
        print(f'account "{username}" is now an admin')
    else:
        print(f'admin account "{username}" already up to date')

# The schema is owned by Alembic, not by db.create_all(). create_all() never
# ALTERs an existing table, so on any deployment whose postgres_data volume
# already existed it would silently ignore every later column or index change.
# app/entrypoint.sh runs `flask db upgrade` before the server starts, and stamps
# 0001 rather than head when it adopts a pre-migration volume.

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
