## Multi-Container Voting App
![CI](https://github.com/Jrtoby/multi-container-voting-app/actions/workflows/ci.yml/badge.svg)

A Dockerised, multi-service voting application built with Flask, Node.js, PostgreSQL and Redis, featuring a fully automated CI/CD pipeline.
**🌐 Live URL:** [http://15.240.192.34:5000](http://15.240.192.34:5000)

## 👥 Team Members
* **Okafor, Sopuluchukwu.T**  (Infrastructure, Integration & Env [py, node.js, P.SQL, Redis, Docker], Version Control management [PR review, conflict & Merge main], CI/CD pipeline secret & ssh key, Documentation.                       
* **Oshioriamhe, Ughiovhe.J** (Docker_compose, Env, pytest & Troubleshooting)          
* **Martins, Ebinum**         (CI Build/Push)
* **Alex, Chimnonolu.A**      (CI Testing )
* **Christopher, Solomon.O**  (Web/Worker Docker_compose update)
* **Takang, Desmond**         (CD Deployment)
* **Oluwasogo, Koselu.P**     (Flask Dockerfile & Env)
* **Ayomide, Aruna.D**        (Node_Worker Dockerfile & Env)

## Problem statement
**Observation:** 
- Traditional monolithic apps crash under heavy traffic. If 1,000 users vote simultaneously, the database locks up, and the app becomes unresponsive.
- The Manual Deployment Problem: Manually deploying updates is slow, error-prone, and requires downtime.

**The Solution:** 
- We need asynchronous processing, caching, containerization, and a fully automated deployment pipeline.

## 🎯 Project Objectives
*   Build a secure, scalable web-based voting platform where users can register, authenticate, and cast a single vote.
*   Implement asynchronous processing to decouple vote submission from database writes, ensuring the application remains responsive under heavy load.
*   Implement caching to speed up results retrieval and reduce database read load.
*   Health-check endpoint for each service, application monitoring and logging.
*   Establish a fully automated CI/CD pipeline from GitHub to AWS EC2 to eliminate manual deployment errors.

## 🏗️ Architecture
![Architecture Diagram](docs/architecture2.jpg)
![Architecture Diagram](docs/architecture.jpg) 

*   **Flask (`web`)**: Handles HTTP routing, UI rendering, authentication, and vote submission. It acts as the API layer.
*   **Node.js (`worker`)**: Background worker that continuously drains the Redis queue and writes votes to PostgreSQL asynchronously.
*   **PostgreSQL (`db`)**: Persistent relational storage for users, polls, and votes.
*   **Redis (`redis`)**: Acts as both a message broker (vote queue) and a caching layer (results cache) to optimize performance.
*   **CI/CD** Built a fully functional CI/CD pipeline that deploys to AWS automatically. Once the workflow file is updated, the pipeline will automatically trigger again.

Watching the Actions tab. You should see:

- test job: Green ✅
- build job: Green ✅
- deploy job: Green ✅

## 🛠️ Tech Stack
*   **Frontend**: HTML5 Templates
*   **Backend**: Python (Flask), Node.js
*   **Database**: PostgreSQL 15, Redis 7
*   **DevOps**: Docker, Docker Compose, GitHub Actions, AWS EC2

## 🚀 Local Development (Without Docker)
1. Clone the repository and navigate to the `app` directory.
2. Install dependencies: `cd app && pip install -r requirements.txt`
3. Set up environment variables: Copy `.env.example` to `.env` and fill in the values.
4. Run tests: `python -m pytest tests/ -v`
5. Start the app locally: `flask run --host=0.0.0.0`

### Microservices in Action (Asynchronous Processing)
This screenshot demonstrates the asynchronous architecture working in real-time. The left pane shows the Flask web server receiving HTTP requests (login, register, vote). The right pane shows the Node.js worker running as a separate service. When a user votes, Flask pushes the vote to the Redis queue (`vote_queue`) and immediately returns a success page. The Node.js worker then pulls the vote from the queue and safely writes it to PostgreSQL in the background, preventing database lockups under high traffic.
![Microservices ](docs/screenshots/microservices.png)

### Running the Automated Tests
The project includes a comprehensive test suite built with `pytest`. The tests are designed to be completely service-free (no Docker, PostgreSQL, or Redis required) by using SQLite and `fakeredis`.

### Prerequisites
Make sure you are in the `app/` directory and your virtual environment is activated:
```bash
cd /var/www/voting-app
git pull origin main
cd app
source venv/bin/activate
pip install -r requirements.txt
```
Execute the following command to run all tests:

```bash
python -m pytest tests/ -v
```
![PYtest](docs/screenshots/pytest.png)
![PYtest](docs/screenshots/pytest1.png)

## 🐳 Running with Docker Compose
1. Clone the repository: `git clone https://github.com/Jrtoby/multi-container-voting-app.git`
2. Ensure you have a `.env` file in `app/` and `worker/` (or use the root `.env`).
3. Build and start: `sudo docker compose up -d --build`
4. Access the app at `http://15.240.192.34:5000`

### Production Deployment with Docker Compose
The application is fully containerized. Below is a screenshot of our Docker Compose environment running all four services (web, worker, db, redis) with health checks passing.
![Docker Compose Status](docs/screenshots/docker_compose_status.png)

## ☁️ Deployment (CI/CD Pipeline)
Our pipeline automatically runs on every push to `main`:
1. **Test**: Runs the `pytest` suite (SQLite + `fakeredis` for fast, isolated testing) **and** the Node.js worker test suite (`node --test`).
2. **Build**: Builds Docker images for the Flask web app and Node.js worker, pushing them to Docker Hub.
3. **Deploy**: SSH into the AWS EC2 instance, pulls the latest images, and restarts the containers using Docker Compose.
![GitHub Actions Pipeline](docs/screenshots/pipeline.png)
GitHub Actions Pipeline

## 🔐 Environment Variables
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_HOST` | Redis hostname (use `redis` in Docker) |
| `SECRET_KEY` | Flask session secret key |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Database bootstrap credentials |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Bootstrap admin account for `/admin` (see Security below) |
| `DOCKER_USERNAME` | GitHub Secret for Docker Hub |
| `DOCKER_PASSWORD` | GitHub Secret for Docker Hub PAT |
| `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY` | GitHub Secrets for AWS deployment |

## 🔒 Security & Admin Access
Authentication is **not** authorisation. Public registration only ever creates
standard users (`is_admin = false`); the `/admin` dashboard is restricted to
administrator accounts and is protected on three levels:

* **Separate admin sign-in** — `/admin/login` is a dedicated door that checks
  the credentials *and* the `is_admin` role together, so a valid normal-user
  password is rejected there.
* **Role gate** — `/admin` is wrapped in `admin_required`: anonymous visitors
  are redirected to `/admin/login`, and a signed-in non-admin receives `403`.
* **CSRF protection** — every POST form carries a per-session token
  (`Flask-WTF`), so cross-site form submissions are rejected with `400`.

Provision the admin account with the CLI (it is also run automatically at boot
from `ADMIN_USERNAME`/`ADMIN_PASSWORD`):

```bash
docker compose exec web flask create-admin --username admin --password 'choose-a-strong-one'
```

Leave `ADMIN_PASSWORD` empty to keep `/admin` locked — no admin account exists
until you create one.

## 🔧 Troubleshooting
- **Port Conflict (5432/6379)**: Stop local PostgreSQL/Redis services (`sudo systemctl stop postgresql redis-server`).
- **Docker build fails**: docker compose logs
- **Pipeline fails at Deploy**: Ensure `EC2_SSH_KEY` in GitHub Secrets contains the entire private key, and that `sudo docker` permissions are not required on the server.
- **Votes not appearing**: Check the Node.js worker logs (`docker logs voting-app-worker-1`) to ensure it is successfully connecting to Redis and PostgreSQL.

## 🧗 Challenges Encountered & Solutions
*   **Merge Conflicts**: Collaborators edited the same `docker-compose.yml` file. Resolved by carefully reviewing the code in GitHub and merging the optimized `npm ci` build logic.
*   **YAML Indentation**: GitHub Actions failed due to incorrect indentation in `ci.yml`. Fixed by aligning the `build` job under the `jobs` hierarchy. (diagnosed the issue by reading the Github Action error logs, corrected the indentation and successfully re-ran the pipeline.)
*   **Deployment Permissions**: The pipeline failed with `sudo: A terminal is required to authenticate`. Solved by granting passwordless Docker group access to the deploy user on EC2 (granting the deployment user Docker group privileges `sudo usermod -aG docker $USER` ) and removing `sudo` from the deployment pipeline script.
*   **Port Conflicts**: Local PostgreSQL and Redis interfered with Docker. Fixed by removing exposed ports for these services in the Docker network, db:5432 / Redis: 6379

## Future Improvements
*   Migrate from Docker Compose to Kubernetes (K8s) for better scaling.
*   Put the web tier behind a load balancer (nginx/HAProxy) so `web` can scale
    horizontally like the `worker` already does (`deploy.replicas: 2`).
*   Implement Prometheus and Grafana for advanced monitoring and alerting.
*   Add OAuth2 social login (Google/GitHub) to improve user experience.
*   Move the WTF CSRF secret/session store to Redis for multi-replica sessions.

## 📸 Screenshots

![DockerHub Images](docs/screenshots/dockerhub.png)
DockerHub Images

![Live Voting App](docs/screenshots/app.png)
Live Voting App
