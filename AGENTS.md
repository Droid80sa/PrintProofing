# Repository Guidelines

## Release Snapshot
- Latest regression run (`venv/bin/python -m pytest`) passes 21 tests.
- Guest-review workflow, admin notifications, and branding updates considered stable for this milestone.

## Project Structure & Module Organization
- `app/` holds the Flask application: blueprints live in `admin_bp.py` and `customer_bp.py`, shared helpers in `extensions.py`, `storage.py`, and `utils.py`, while HTML templates and static assets sit under `app/templates/` and `app/static/` (compiled CSS in `app/static/dist/`).
- `tests/` contains pytest suites that depend on the bundled SQLite fixture `tests/test_app.sqlite`; keep new tests in this tree and name files `test_*.py`.
- Front-end styles start from `frontend/tailwind.css` and compile into the `app/static/dist/` bundle; database migrations live in `alembic/` alongside `alembic.ini`.
- One-off guest review flows live in `app/guest_access.py` with views under `app/templates/customer/guest_access.html`; their persistence sits in the `proof_guest_accesses` table.

## Build, Test, and Development Commands
- `./setup.sh` provisions the virtualenv, installs `app/requirements.txt`, and scaffolds a default `.env`.
- `docker compose up --build` launches the web app, worker, and Postgres stack; use `docker compose run --rm web alembic upgrade head` to apply migrations.
- `npm run build:css` compiles Tailwind once, while `npm run watch:css` keeps styles rebuilding in development.
- Run backend tests with `pytest` from the project root; for Playwright visual checks use `npm run test:visual` (requires `npx playwright install` on first run).

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and descriptive snake_case for Python modules, mirroring existing filenames (`customer_notifications.py`, `email_queue.py`).
- Prefer Flask blueprints for new routes and keep CLI commands inside `app/app.py` alongside existing Click integrations.
- Tailwind utility classes drive styling; extend `tailwind.config.js` rather than scattering ad-hoc CSS, and store static uploads under `app/static/uploads/`.
- When sending ad-hoc proofs, pass extra context (e.g. `guest_pin`) into `render_notification_content` so emails can surface required tokens.

## Testing Guidelines
- Pytest discovers tests named `test_*.py`; mirror current patterns by using fixtures in `conftest.py` and the SQLite test database to keep runs isolated.
- Target critical workflows (proof upload, customer invitations, SMTP validation) and add regression-focused assertions when touching those areas.
- Update Playwright snapshots only after confirming the UI.

## Commit & Pull Request Guidelines
- Use concise, imperative commit subjects (e.g., `Add customer invite expiry validation`) and group related changes per commit for easier review.
- Reference issue numbers in the body when applicable and summarize backend/frontend impacts in bullet points.
- Pull requests should outline motivation, list key changes, note schema or env tweaks, and include screenshots or terminal output when touching UI or CLI flows.

## Environment & Security Notes
- Never commit real credentials; rely on the `.env` template from `setup.sh` and document any new variables in `env.txt`.
- Sensitive customer files default to local storage under `app/proofs/`; validate access controls when introducing alternative storage backends via `FILE_STORAGE_BACKEND`.
