# Proof Approval System

A lightweight Flask-based proof approval tool with branding support, email notifications, customer management, and client response tracking.

## Features

- PDF/image proof upload with shareable client links
- Customer association for each proof plus full admin CRUD management
- Approval/Decline with optional client comment and per-version history
- Designer notifications via async email queue with per-user SMTP overrides
- Admin dashboard with status tracking, filters, audit indicators, and CSV export
- White-label branding (colors, fonts, logos, disclaimers, CSS overrides)
- Secure customer login portal with invite/reset workflow and configurable rollout toggles
- Optional customer notifications on upload with customizable templates and delivery logging
- In-app customer management available to both admins and designers
- Legacy JSON/CSV import helpers for smooth migrations

## Setup

```bash
git clone https://github.com/yourusername/proofs-app.git
cd proofs-app
chmod +x setup.sh
./setup.sh
```

Then run:

```bash
docker compose up --build
```

Visit [http://localhost:5010](http://localhost:5010)

## Production Deployment

The repository now includes a production-ready image and Compose file that bakes
Tailwind assets, runs migrations, and keeps proof uploads on a dedicated volume.

1. Copy `.env.example` to `.env` and update secrets such as `DATABASE_URL`,
   `MAIL_DEFAULT_SENDER`, and any storage configuration (`FILE_STORAGE_*`).
2. Build the image (this compiles Python dependencies and Tailwind CSS):

   ```bash
   docker compose -f docker-compose.prod.yml build
   ```

3. Start the stack:

   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```

   The `web` container waits for Postgres, applies Alembic migrations (set
   `RUN_MIGRATIONS=false` to skip), and exposes port 5010 by default.

4. Create an initial admin account once the containers are healthy:

   ```bash
   docker compose -f docker-compose.prod.yml run --rm web \
     flask --app app.app create-user --email admin@example.com --name "Site Admin" --role admin
   ```

5. Persisted data lives in two volumes:
   - `proofs_media` for uploaded proofs (mounted at `/mnt/proofs` inside the
     container).
- `postgres_data` for the Postgres cluster.

For remote deployments, push the built image to your registry and reuse the same
`docker-compose.prod.yml` (or translate it to your orchestration platform).
Set `DATABASE_URL` to your production database; when pointing at a managed
Postgres instance you can remove the bundled `db` service.

### Bulk-import designers

Create a CSV with at least `email` and `password` columns (optional: `name`,
`display_name`, `role`, `reply_to`, `smtp_host`, `smtp_port`, `smtp_username`,
`smtp_password`, `smtp_sender`, `smtp_reply`). For semicolon-delimited files use
the default command; pass `--delimiter ','` for comma-separated files:

```bash
docker compose -f docker-compose.prod.yml run --rm \
  --entrypoint python \
  -v "$(pwd)/designers.csv:/tmp/designers.csv:ro" \
  web scripts/import_designers.py --csv /tmp/designers.csv
```

Add `--dry-run` to preview changes or `--skip-existing` to ignore duplicate
emails gracefully.

## Front-End Assets

Tailwind CSS powers the refreshed UI. Install the Node dev dependencies once and build the stylesheet:

```bash
npm install
npm run build:css
```

During development you can keep Tailwind in watch mode:

```bash
npm run watch:css
```

The compiled bundle lives at `app/static/dist/main.css` and is served automatically by the templates.

_Tip_: add a `pre-commit` or CI step that runs `npm run build:css` so fresh styles ship with every commit.

## Database Migrations

Apply migrations before running the app (inside the container or your local environment):

```bash
# using Docker
docker compose run --rm web alembic upgrade head

# or locally inside the venv
alembic upgrade head
```

## Create an Admin or Designer Account

Accounts live in the database. Use the CLI to create one after running migrations:

```bash
docker compose run --rm web flask --app app.app create-user --email admin@example.com --name "Site Admin" --role admin
```

For designers, specify `--role designer` and optional display/reply-to overrides.
To rotate a password from the command line:

```bash
docker compose run --rm web flask --app app.app reset-password --email user@example.com --password "newpass123"
```

Login attempts are throttled (defaults: 5 attempts per 5 minutes). Adjust via
`LOGIN_MAX_ATTEMPTS` / `LOGIN_ATTEMPT_WINDOW` in your `.env` if needed.

## Customer Portal Rollout

1. Enable the login experience by setting `CUSTOMER_LOGIN_ENABLED=true` in your environment.
2. Keep `LEGACY_PUBLIC_LINKS_ENABLED=true` during transition to allow existing share links to work (a banner prompts customers to sign in). Set it to `false` once all customers are onboarded to enforce authentication.
3. Invite customers with:

   ```bash
   flask --app app.app invite-customer customer@example.com
   ```

   Add `--no-send` to skip emailing and print the activation link.
4. Customers can access the portal at `/customer/login`, request password resets at `/customer/reset`, and manage decisions securely once invited.

Invite tokens expire after 72 hours by default; override with `--hours-valid`. Passwords require a minimum of 12 characters including letters and a number/symbol.

## Customer Upload Notifications

- Tick “Notify customer now” on the upload form to send a tailored email alongside the proof link.
- Use the modal editor to adjust subject/body; supported placeholders: `{{customer_name}}`, `{{job_name}}`, `{{proof_link}}`, and `{{designer_name}}`.
- Messages are queued through the same async email worker that honours designer SMTP overrides; delivery status (`queued`/`sent`/`failed`) is recorded in the database (`customer_notifications` table).
- Configure default templates via environment variables:

  ```env
  CUSTOMER_NOTIFY_DEFAULT_SUBJECT=New proof ready: {{job_name}}
  CUSTOMER_NOTIFY_DEFAULT_BODY=Hi {{customer_name}},\n\nA new proof "{{job_name}}" is ready. View it here: {{proof_link}}\n\nThanks,\n{{designer_name}}
  ```

- Failed sends surface a warning on the upload confirmation screen; all entries remain in the log for auditing and future resend tooling.
- Admins may select themselves when uploading, allowing notifications to use their configured SMTP profile without a designer.

## SMTP Validation

- Admins can manage SMTP credentials under Admin → Users → Edit and trigger a “Send Test Email” action; the result is stored alongside a timestamp and any error message.
- Designers see their current SMTP status on the dashboard and can run their own test from the same page once host/port are configured.
- The most recent outcome is displayed in the user list, helping administrators spot misconfigured accounts quickly.

All mutating forms include CSRF protection automatically; ensure any new forms
render `{{ csrf_token }}` and submit it with POST requests.

Emails default to the designer’s configured email/reply-to when available.
If SMTP send-as is not permitted, set `MAIL_DEFAULT_SENDER` / `MAIL_DEFAULT_REPLY_TO`
to a generic address and the notification will fall back gracefully.

Per-user SMTP settings can be configured under Admin → Users → Edit. Specify
host, port, credentials, and whether to use TLS/SSL; use the “Send Test Email”
button to validate connectivity. Leave fields blank to inherit the global mail
settings.

Production notifications run through an in-process worker queue (logged to
`app/logs/email.log`). Proof submission responses enqueue immediately, keeping
requests fast while delivering emails in the background.

Signed-in designers see their own proofs and have their details prefilled on
the upload form; admins can choose from the managed designer list when uploading.
Admins can manage accounts (create, activate/deactivate, reset password, change
role, delete) via the web UI under Admin → Users.

Customers can be managed via Admin → Customers; assigning a customer during
upload records ownership for future reporting, and the client-facing proof page
now surfaces version selection for historical comparison.

Proof metadata and decision history now live entirely in the database. If your
instance still has legacy JSON logs, run the import command above and remove the
old files once verification is complete.

## Legacy Data Import

If you have existing JSON/CSV proof data under `app/logs/` and proof files in
`app/proofs/`, migrate them into the database with:

```bash
docker compose run --rm web flask --app app.app import-legacy-data --email-domain hotink.co.za
```

Add `--dry-run` to preview without committing, or point the command at
alternative folders using `--log-dir`, `--proofs-dir`, and `--approvals-csv`.

## Customization

Edit `admin/settings.json` for branding. Configure mail, the optional
`PUBLIC_BASE_URL` (e.g. `https://proof.example.com`), optional `FILE_BASE_URL`
if assets are served from a CDN/object store, optional `FILE_STORAGE_ROOT`
to point at an external mount (e.g. NFS path inside the container), and `DATABASE_URL`
in the `.env` file to control outbound proof links and point the app at
your PostgreSQL instance (falls back to a local SQLite file when unset).
When running via Docker Compose the default connection string targets the
bundled `db` service; change the host to `localhost` if you run PostgreSQL
outside of Compose.

Copy `.env.example` to `.env` (or let `setup.sh` generate one) and tweak
values as needed before deploying.

### Using NFS or Shared Storage

Mount your NFS share into the container/host and point `FILE_STORAGE_ROOT`
at the mounted directory (e.g. `/mnt/proofs`). The app will read/write proofs
there while still serving them via the storage abstraction.

### Using Amazon S3

Set `FILE_STORAGE_BACKEND=s3` and provide `AWS_S3_BUCKET`, optional
`AWS_S3_PREFIX`, `AWS_S3_REGION`, and credentials (`AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`). When `FILE_BASE_URL` is omitted the app will issue
time-limited presigned URLs; provide a CDN URL if objects are replicated there.

## Logging & Production Runtime

Application logs are emitted as JSON to stdout (controlled by `LOG_LEVEL`),
with email delivery events captured in `app/logs/email.log`. The Docker image
ships with Gunicorn (`gunicorn app.app:app`) as the default entrypoint; adjust
worker counts via environment variables or Compose overrides for production.

## Roadmap Snapshot

- Introduce a customer login experience to replace public share links where possible.
- Add an optional customer-notification workflow during proof upload, with an editable email (popup editor) that sends via the selected designer’s SMTP settings.
- Expand automated test coverage, improve SMTP validation feedback, and document rollout guidance for upcoming features.

## License

MIT License
