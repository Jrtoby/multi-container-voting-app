# Multi-Container Voting App

A Dockerized voting application built as a Cloud/DevOps capstone project.

## Project Status

Phase 1 - Application Development

## Docker Setup

This project can be run using Docker Compose.

### Services

The application consists of four services:

- Flask web application
- Node.js background worker
- PostgreSQL database
- Redis

### Environment Configuration

A `.env.example` file is provided as a template for environment configuration.

Create a local environment file from the example:

``bash
cp .env.example .env

### Prerequisites
- Docker and Docker Compose installed.

### Steps
1. Clone the repository.
2. Ensure `.env` files are set up in the `app/` and `worker/` directories.
3. Build and start all services:
   ```bash
   sudo docker-compose up -d --build

## Running the Automated Tests

The project includes a comprehensive test suite built with `pytest`. The tests are designed to be completely service-free (no Docker, PostgreSQL, or Redis required) by using SQLite and `fakeredis`.

### Prerequisites
Make sure you are in the `app/` directory and your virtual environment is activated:
```bash
cd /var/www/voting-app
git pull origin main
cd app
source venv/bin/activate
pip install -r requirements.txt

Execute the following command to run all tests:

```bash
python -m pytest tests/ -v
```

Test Structure

· tests/conftest.py: Shared pytest fixtures (sets up in-memory DB and Redis).
· tests/test_auth.py: Tests registration, login, logout, and access control.
· tests/test_redis.py: Tests the vote queue hand-off and results caching logic.
· tests/helpers.py: Reusable test utilities (create_user, seed_poll, etc.).

```


