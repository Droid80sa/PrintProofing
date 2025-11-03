# Proof Approval System – Agent Brief

## Project Snapshot
- Flask-based proof approval platform with authentication (admin/designer roles), async email notifications, and branded client review workflow.
- Persistence handled by PostgreSQL via SQLAlchemy; proofs/decisions stored relationally with Alembic migrations.
- File storage abstracted behind pluggable backends: local filesystem (default, supports NFS) or Amazon S3 with presigned URLs.
- Per-user SMTP credentials (designers/admins) configurable via admin UI; background email queue logs deliveries to `app/logs/email.log`.
- Dockerized deployment using Gunicorn (non-root user) and health-check endpoint (`/_healthz`); JSON logging to stdout driven by `LOG_LEVEL`.

## Repository Layout
- `app/app.py` – primary Flask app (routes, auth, storage/email services, logging configuration, CLI utilities).
- `app/models.py` – SQLAlchemy models (`User`, `Designer`, `Proof`, `ProofVersion`, `Decision`).
- `app/storage.py` – storage backends (`LocalStorage`, `S3Storage`).
- `app/email_queue.py` – lightweight threaded email worker with logging.
- `app/templates/` – Jinja templates for admin, designer, and client views (upload, dashboards, settings, etc.).
- `app/static/` – CSS/brand assets; `theme.css` served dynamically from settings.
- `app/logs/` & `app/proofs/` – runtime directories ignored by Git (`.gitkeep` placeholders only).
- `alembic/` – database migrations (`alembic.ini`, `versions/`).
- `Dockerfile`, `docker-compose.yml`, `setup.sh` – container build/run scripts (Gunicorn entrypoint, Postgres service, health check, initial `.env`).
- `.env.example` – documented environment variables for mail, DB, storage, logging.

## Core Workflows
- **Upload** (`POST /upload`): Authenticated users select/auto-populate designer, upload proofs (async progress bar). Files saved via configured storage backend; metadata stored in DB; success view shows shareable link (respects `PUBLIC_BASE_URL`).
- **Client Review** (`GET /proof/<job_id>`): Renders latest proof version (iframe/image download fallback), notes, disclaimer, and decision form.
- **Submission Handling** (`POST /submit`): Persists decision history (DB `Decision` records), updates proof status, enqueues email notification with per-user SMTP settings and structured logging.
- **Admin Dashboard** (`/admin/dashboard`): Filterable/searchable view with audit timestamps, approver info, quick export, aggregate insight cards.
- **Designer Dashboard** (`/designer/dashboard`): Designers see only owned proofs with filters and activity timeline.
- **Admin Tools**: User management (create/edit/delete, SMTP config/test), branding, disclaimers, logo/CSS editing, CSV export, settings.
- **Public Status** (`/status`): Clients check proof status via link/ID/job name; integrates with DB (legacy JSON fallback).
- **Health Check** (`/_healthz`): JSON heartbeat for orchestration.
- **CLI Utilities**: `create-user`, `reset-password`, and `import-legacy-data` (migrate JSON/CSV into DB & storage).

## Configuration & Runtime
- Environment management via `.env` (`python-dotenv`). Key vars: SMTP (`MAIL_*`), optional per-user overrides (stored in DB), `PUBLIC_BASE_URL`, storage (`FILE_STORAGE_BACKEND`, `FILE_STORAGE_ROOT`, S3 settings), DB (`DATABASE_URL`), logging (`LOG_LEVEL`).
- Docker setup runs Gunicorn as non-root `appuser`; compose file maps port `5010->5000`, includes Postgres service and health check.
- Logging: JSON to stdout; email worker writes to `app/logs/email.log`. Toggle verbosity with `LOG_LEVEL`.
- Background email queue ensures fast responses while delivering mail asynchronously; errors logged and fall back to global SMTP settings.

## Current State & Observations
- Customer management, version history, and admin blueprint refactor are in place; legacy runtime directories remain ignored.
- A pytest scaffold (`tests/test_app.py`) verifies the basic app health; broader automated coverage is still pending.
- The client proof view now handles multiple versions gracefully, but customer access continues to rely on public links pending the planned login experience.
- Upload flow still lacks advanced validation (virus scan, MIME hardening) and optional features such as per-customer email notifications.
- S3 backend remains optional; structured logging exists but no external monitoring (Sentry/Otel) is configured yet.
- Runtime configuration now exposes key paths (admin/upload/log directories) to blueprints via `current_app.config`.

## Agent's Work Log

### Phase 1: Customer Integration
- **1.1: Created `Customer` Model**: Added a new `Customer` table to `app/models.py` with fields for `name`, `company_name`, and `email`.
- **1.2: Generated Database Migration for Customer**: Created and applied a new Alembic migration script for the `Customer` model.
- **1.3: Associated `Proof` with `Customer`**: Added a foreign key to the `Proof` model to link it to a `Customer`, and made `designer_id` nullable.
- **1.4: Generated Database Migration for Association**: Created and applied a new Alembic migration script for the `proofs.customer_id` column.
- **1.5: Updated Upload Process**: Modified the `/upload` route in `app/app.py` and `upload.html` template to allow selecting a `Customer` when uploading a new proof.
- **1.6: Implemented Customer Management UI**: Created `admin_customers.html` and `admin_customer_edit.html` templates, and added routes for CRUD operations for customers in `app/admin_bp.py`. Updated `admin_nav.html` with links to customer management.

### Phase 2: Proof Versioning
- **2.1: Implemented "New Version" Upload**: Created a new route `/proof/<job_id>/new_version` and `new_version.html` template to allow designers to upload new versions. Updated `admin_dashboard.html` and `designer_dashboard.html` with "New Version" links.
- **2.2: Displayed Version History**: Modified the `show_proof` function in `app/app.py` to fetch all `ProofVersion`s and passed them to `proof.html`. Updated `proof.html` to display a version selection dropdown and handle version switching.
- **2.3: (Advanced) Side-by-Side Version Comparison (Placeholder)**: Created a new route `/proof/<job_id>/compare` and `compare_versions.html` template as a placeholder. Added a "Compare Versions" button to `proof.html`.

### Phase 3: Advanced Features & Refinements
- **3.1: (Advanced) On-Proof Annotations (Placeholder)**: Created a new route `/proof/<job_id>/annotate` and `annotate_proof.html` template as a placeholder. Added an "Add Annotations" button to `proof.html`.
- **3.2: Improved Security (Placeholder)**: Added a placeholder note for a planned customer login system in `proof.html`; future work will replace this with real authentication.
- **3.3: Refactored Codebase**: Created `app/admin_bp.py` and moved admin-related routes into it. Registered `admin_bp` in `app/app.py` and updated `url_for` calls in templates to use the Blueprint name.
- **3.4: Established Testing Framework**: Installed `pytest`, created `tests/` directory, and added a basic `tests/test_app.py` to test the home route.

### Bug Fixes during development:
- Fixed `FileNotFoundError: 'alembic/script.py.mako'` by creating the missing template file.
- Resolved Alembic database state issues by using `alembic stamp` and deleting old migration files.
- Fixed `SyntaxError: '(' was never closed` in `app/app.py` by correcting a missing parenthesis.
- Fixed `NameError: name 'app' is not defined` by ensuring `app = Flask(__name__)` is defined before its usage.
- Fixed `IndentationError: unexpected indent` in `app/app.py`.
- Fixed `ImportError: cannot import name 'login_required' from partially initialized module 'app.app'` (circular import) by moving common functions (`login_required`, `_user_smtp_settings`, `send_email_notification`) to `app/utils.py` and updating imports.
- Fixed multiple `/login` and blueprint-related 500s by reintroducing configuration bootstrap, exposing branding/storage helpers, and normalising `url_for` usage throughout admin templates.
- Hardened storage initialisation for read-only environments and updated proof rendering logic to avoid Jinja filter errors on version selection.

## Suggested Next Steps
1. **Customer Login Experience:** Design and implement the authenticated client portal (models, flows, UI), replacing public links where feasible.
2. **Customer Email Notifications:** Add an optional branded-email workflow to proof uploads with a popup editor, leveraging the selected designer’s SMTP settings.
3. **Supporting Improvements:** Expand automated tests, surface SMTP validation feedback, and document rollout steps (including customer communications) for the new capabilities.
4. **Optional Enhancements:** Revisit placeholder features (version comparison/annotations) once core security and email objectives are met.
