import os
import json
import redis
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import text
from models import db, User, Poll, Vote

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql+psycopg2://voting_user:group12cohort8@localhost:5432/voting_db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Connect to Redis (running locally on this server)
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

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
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and user.check_password(request.form.get('password')):
            login_user(user)
            return redirect(url_for('vote'))
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
        # Create a default poll if none exists
        poll = Poll(question="Which framework is better?", option_a="Flask", option_b="Node.js")
        db.session.add(poll)
        db.session.commit()

    if request.method == 'POST':
        choice = request.form.get('choice')
        # Enforce one vote per user
        existing_vote = Vote.query.filter_by(user_id=current_user.id, poll_id=poll.id).first()
        if existing_vote:
            flash('You have already voted!')
        else:
            # Instead of writing to DB, push to Redis Queue
            vote_data = {
                'user_id': current_user.id,
                'poll_id': poll.id,
                'choice': choice
            }
            r.lpush('vote_queue', json.dumps(vote_data))
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
        print("Serving from Redis Cache!")
        data = json.loads(cached_results)
        return render_template('results.html', poll=poll, votes_a=data['votes_a'], votes_b=data['votes_b'])
    
    print("Serving from Database!")
    votes_a = Vote.query.filter_by(poll_id=poll.id, choice='A').count()
    votes_b = Vote.query.filter_by(poll_id=poll.id, choice='B').count()

 # Save to Redis cache for 10 seconds
    r.setex('results_cache', 10, json.dumps({'votes_a': votes_a, 'votes_b': votes_b}))

    return render_template('results.html', poll=poll, votes_a=votes_a, votes_b=votes_b)

@app.route('/admin')
@login_required
def admin():
    total_users = User.query.count()
    total_votes = Vote.query.count()
    return render_template('admin.html', total_users=total_users, total_votes=total_votes)

@app.route('/health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
        return {"status": "healthy"}, 200
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}, 500

# Create tables on first run
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
