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

```bash
cp .env.example .env

## Running the Application with Docker

### Prerequisites
- Docker and Docker Compose installed.

### Steps
1. Clone the repository.
2. Ensure `.env` files are set up in the `app/` and `worker/` directories.
3. Build and start all services:
   ```bash
   sudo docker-compose up --build -d
