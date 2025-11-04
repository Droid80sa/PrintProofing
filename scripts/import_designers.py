#!/usr/bin/env python
"""Bulk-import user/designer accounts from a CSV file.

The script expects to run inside the Flask application context. When using
Docker, mount the CSV into the container and run:

    docker compose -f docker-compose.prod.yml run --rm \
        --entrypoint python \
        -v "$(pwd)/designers.csv:/tmp/designers.csv:ro" \
        web scripts/import_designers.py --csv /tmp/designers.csv

The CSV must contain ``email`` and ``password`` columns. Optional columns are
``name``, ``display_name``, ``role`` (``admin``/``designer``), general
communication ``reply_to``, and SMTP settings (``smtp_host``, ``smtp_port``,
``smtp_username``, ``smtp_password``, ``smtp_sender``, ``smtp_reply``/
``smtp_reply_to``, ``smtp_use_tls``, ``smtp_use_ssl``).

Use ``--delimiter ","`` if you prefer a comma-separated file.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from app.app import app
from app.extensions import db
from app.models import Designer, User
from werkzeug.security import generate_password_hash


REQUIRED_COLUMNS = {"email", "password"}
OPTIONAL_COLUMNS = {
    "name",
    "display_name",
    "reply_to",
    "role",
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_password",
    "smtp_sender",
    "smtp_reply",
    "smtp_reply_to",
    "smtp_use_tls",
    "smtp_use_ssl",
}


def _normalise_key(raw: str | None) -> str:
    if raw is None:
        return ""
    return raw.strip().lower().replace(" ", "_")


def _parse_bool(value: str | None) -> bool | None:
    if not value:
        return None
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _coerce_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise SystemExit(f"Unable to parse integer value: {value}") from None


def _normalise_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        _normalise_key(key): (value.strip() if isinstance(value, str) else "")
        for key, value in row.items()
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        required=True,
        type=Path,
        help="Path to the CSV file containing designer details.",
    )
    parser.add_argument(
        "--delimiter",
        default=";",
        help="CSV delimiter (default: ';').",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the file and show the summary without inserting records.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip rows whose email already exists instead of raising an error.",
    )
    return parser.parse_args()


def import_designers(
    csv_path: Path, *, delimiter: str, dry_run: bool, skip_existing: bool
) -> None:
    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")

    created = 0
    skipped = 0

    with app.app_context():
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter, skipinitialspace=True)
            raw_fieldnames = reader.fieldnames or []
            fieldnames = {_normalise_key(name) for name in raw_fieldnames}
            missing = REQUIRED_COLUMNS - fieldnames
            if missing:
                raise SystemExit(
                    f"CSV missing required column(s): {', '.join(sorted(missing))}"
                )

            unexpected = fieldnames - REQUIRED_COLUMNS - OPTIONAL_COLUMNS
            if unexpected:
                print(
                    f"Warning: ignoring unexpected column(s): {', '.join(sorted(unexpected))}",
                    file=sys.stderr,
                )

            for row in reader:
                normalised = _normalise_row(row)
                email = normalised.get("email", "").lower()
                password = normalised.get("password", "")

                if not email or not password:
                    print(
                        f"Skipping row with missing email/password: {row}",
                        file=sys.stderr,
                    )
                    skipped += 1
                    continue

                existing = User.query.filter_by(email=email).first()
                if existing:
                    message = f"User already exists: {email}"
                    if skip_existing:
                        print(f"Skipping existing user: {email}", file=sys.stderr)
                        skipped += 1
                        continue
                    raise SystemExit(message)

                role = normalised.get("role", "designer") or "designer"
                role = role.lower()
                if role not in {"designer", "admin"}:
                    raise SystemExit(f"Unsupported role '{role}' for user {email}")

                name = normalised.get("name") or email.split("@", 1)[0]
                display_name = normalised.get("display_name") or name
                reply_to = (
                    normalised.get("reply_to")
                    or normalised.get("smtp_reply_to")
                    or normalised.get("smtp_reply")
                    or email
                )

                if dry_run:
                    created += 1
                    continue

                user = User(
                    email=email,
                    name=name,
                    password_hash=generate_password_hash(password),
                    role=role,
                    is_active=True,
                )

                smtp_host = normalised.get("smtp_host") or None
                smtp_port = _coerce_int(normalised.get("smtp_port")) if normalised.get("smtp_port") else None
                smtp_username = normalised.get("smtp_username") or None
                smtp_password = normalised.get("smtp_password") or None
                smtp_sender = normalised.get("smtp_sender") or None
                smtp_reply_to = normalised.get("smtp_reply_to") or normalised.get("smtp_reply") or reply_to
                smtp_use_tls = _parse_bool(normalised.get("smtp_use_tls"))
                smtp_use_ssl = _parse_bool(normalised.get("smtp_use_ssl"))

                user.smtp_host = smtp_host
                user.smtp_port = smtp_port
                user.smtp_username = smtp_username
                user.smtp_password = smtp_password
                user.smtp_sender = smtp_sender
                user.smtp_reply_to = smtp_reply_to
                if smtp_use_tls is not None:
                    user.smtp_use_tls = smtp_use_tls
                if smtp_use_ssl is not None:
                    user.smtp_use_ssl = smtp_use_ssl

                designer = None
                designer = Designer(
                    user=user,
                    display_name=display_name,
                    email=email,
                    reply_to_email=reply_to,
                    is_active=True,
                ) if role == "designer" else None

                db.session.add(user)
                if designer is not None:
                    db.session.add(designer)
                created += 1

        if dry_run:
            print(f"DRY RUN: would create {created} user(s); skipped {skipped}.")
            db.session.rollback()
            return

        db.session.commit()
        print(f"Created {created} user(s); skipped {skipped}.")


def main() -> None:
    args = parse_args()
    import_designers(
        args.csv,
        delimiter=args.delimiter,
        dry_run=args.dry_run,
        skip_existing=args.skip_existing,
    )


if __name__ == "__main__":
    main()
