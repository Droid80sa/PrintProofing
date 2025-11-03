# Gemini Agent Instructions for Proofs App

This document provides essential guidance for working on the Proofs App codebase. For a more detailed project breakdown, see `AGENT.md`.

## 1. Project Overview & Tech Stack

This is a Flask-based application for managing and approving design proofs.

- **Backend:** Flask, SQLAlchemy (PostgreSQL), Alembic
- **Frontend:** Jinja2 templates, basic CSS
- **File Storage:** Pluggable backend for local filesystem or AWS S3 (`app/storage.py`).
- **Async Tasks:** A simple, in-process threaded queue for sending emails (`app/email_queue.py`).
- **Deployment:** Docker and Gunicorn.

The main application logic is in the monolithic `app/app.py`. The database models are defined in `app/models.py`.

## 2. Development Workflow

The entire development environment is managed with Docker Compose.

### Initial Setup

1.  **Run the setup script:** This creates the `.env` file and installs dependencies into a virtual environment.
    ```bash
    ./setup.sh
    ```
2.  **Build and start the services:**
    ```bash
    docker compose up --build
    ```
    The application will be available at [http://localhost:5010](http://localhost:5010).

### Common Tasks

- **Apply Database Migrations:** After changing `app/models.py`, you need to generate and apply a migration.
    ```bash
    # Generate a new migration script
    docker compose run --rm web alembic revision --autogenerate -m "Your migration message"

    # Apply the migration
    docker compose run --rm web alembic upgrade head
    ```

- **Create a User:** Users are managed via the database. Use the built-in Flask CLI command.
    ```bash
    docker compose run --rm web flask --app app.app create-user --email admin@example.com --name "Admin" --role admin
    ```

## 3. Making Code Changes

- **Backend Logic:** Most routes and business logic are in `app/app.py`. For new features, consider if they can be grouped into a new file or a Flask Blueprint.
- **Database Models:** Modify `app/models.py` to change the schema. Remember to generate a migration afterward.
- **Frontend:** Templates are in `app/templates/`. The application uses a main `base.html` and extends it. Custom CSS is in `app/static/style.css`.
- **Dependencies:** Add new Python packages to `app/requirements.txt` and rebuild the Docker image.

## 4. Storage Abstraction

The application can store files locally or on S3. The `storage_backend` object in `app/app.py` is an instance of either `LocalStorage` or `S3Storage` from `app/storage.py`. Use this object to interact with files (e.g., `storage_backend.save(...)`, `storage_backend.generate_url(...)`).

## 5. Testing

There is currently no automated test suite. When adding new features or fixing bugs, please add corresponding tests using `pytest`. You will need to set up the testing framework.
