# Copilot Instructions for Proofs App

## Project Overview
This is a Flask-based proof approval system that enables designers to upload proofs (PDF/images) for client review. The system manages client approvals/declines, sends email notifications, and provides white-label branding capabilities.

## Core Architecture
- **Database**: PostgreSQL with SQLAlchemy ORM
  - Key models: `User`, `Designer`, `Proof`, `ProofVersion`, `Decision` in `app/models.py`
  - Migrations managed by Alembic in `alembic/versions/`
- **Authentication**: Session-based with role support (admin/designer)
- **File Storage**: Local filesystem (`app/proofs/`) with abstraction via `LocalStorage` class
- **Email**: SMTP with per-user configuration support, async queue
- **Frontend**: Jinja2 templates with dynamic theming via `/theme.css`

## Key Workflows
1. **Proof Upload**:
   ```python
   # See app/app.py POST /upload
   # Files saved under random ID, metadata in DB
   # Returns shareable client URL
   ```

2. **Client Review**:
   ```python
   # See app/app.py GET /proof/<share_id>
   # Renders proof preview + approval form
   # POST /submit handles decision + emails
   ```

3. **Admin Operations**:
   - Settings management in `app/admin/settings.json`
   - User/Designer management via web UI
   - White-label branding configuration
   - CSV export capabilities

## Development Setup
```bash
# Initial setup
./setup.sh  # Creates venv + .env

# Database
docker compose run --rm web alembic upgrade head

# Create admin user
docker compose run --rm web flask --app app.app create-user --email admin@example.com --name "Admin" --role admin

# Run app
docker compose up --build
```

## Project Conventions
1. **Database Updates**:
   - Always use Alembic migrations (`alembic revision -m "description"`)
   - Run migrations before app startup

2. **Email Configuration**:
   - Global defaults in `.env`
   - Per-user SMTP override in User model
   - All emails queued via `EMAIL_QUEUE`

3. **File Paths**:
   - Storage root configurable via `FILE_STORAGE_ROOT`
   - CDN support via `FILE_BASE_URL`
   - Public links use `PUBLIC_BASE_URL`

4. **Security**:
   - Login throttling (5 attempts/5 minutes)
   - CSRF protection on all forms
   - Role-based access control (admin/designer)

## Integration Points
1. **Storage Backend**: `LocalStorage` class in `app/storage.py`
2. **Email Queue**: `EMAIL_QUEUE` in `app/email_queue.py`
3. **External URLs**: Configuration via environment variables:
   - `PUBLIC_BASE_URL`: Public-facing URLs
   - `FILE_BASE_URL`: Asset serving (optional CDN)
   - `FILE_STORAGE_ROOT`: External storage mount

## Common Tasks
1. **Adding User**:
   ```bash
   flask --app app.app create-user --email user@example.com --name "Name" --role designer
   ```

2. **Reset Password**:
   ```bash
   flask --app app.app reset-password --email user@example.com --password "newpass123"
   ```

3. **Import Legacy Data**:
   ```bash
   flask --app app.app import-legacy-data --email-domain example.com
   ```

## Testing & Debugging
- No automated tests yet (priority enhancement needed)
- Check email delivery via admin UI "Send Test Email"
- Monitor `app/logs/` for operational data
- Use `docker compose logs -f` for runtime issues

This system is transitioning from file-based storage (JSON/CSV) to a proper database. When adding features, prefer database-driven approaches over file operations.