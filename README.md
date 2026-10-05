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