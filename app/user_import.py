from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import TextIO

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import Designer, User


REQUIRED_COLUMNS = {"email", "password"}
OPTIONAL_COLUMNS = {
    "name",
    "display_name",
    "role",
    "reply_to",
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


@dataclass
class ImportSummary:
    created: int
    skipped: int


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
    except ValueError as exc:
        raise ValueError(f"Unable to parse integer value: {value}") from exc


def _normalise_row(row: dict[str, str | None]) -> dict[str, str]:
    return {
        _normalise_key(key): (value.strip() if isinstance(value, str) else "")
        for key, value in row.items()
    }


def _detect_delimiter(sample: str) -> str:
    header = sample.splitlines()[0] if sample else ""
    semicolons = header.count(";")
    commas = header.count(",")
    if semicolons == 0 and commas == 0:
        return ";"
    return ";" if semicolons >= commas else ","


def import_users_from_csv(
    handle: TextIO,
    *,
    delimiter: str | None = None,
    skip_existing: bool = False,
    dry_run: bool = False,
) -> ImportSummary:
    text = handle.read()
    if not isinstance(text, str):
        raise ValueError("CSV data must be text")

    text = text.lstrip("\ufeff")
    effective_delimiter = delimiter or _detect_delimiter(text)

    reader = csv.DictReader(
        io.StringIO(text), delimiter=effective_delimiter, skipinitialspace=True
    )

    if reader.fieldnames is None:
        raise ValueError("CSV file is empty or missing headers")

    fieldnames = {_normalise_key(name) for name in reader.fieldnames}
    missing = REQUIRED_COLUMNS - fieldnames
    if missing:
        raise ValueError(
            f"CSV missing required column(s): {', '.join(sorted(missing))}"
        )

    created = 0
    skipped = 0

    for row in reader:
        normalised = _normalise_row(row)
        email = normalised.get("email", "").lower()
        password = normalised.get("password", "")

        if not email or not password:
            skipped += 1
            continue

        existing = User.query.filter_by(email=email).first()
        if existing:
            if skip_existing:
                skipped += 1
                continue
            raise ValueError(f"User already exists: {email}")

        role = normalised.get("role", "designer") or "designer"
        role = role.lower()
        if role not in {"admin", "designer"}:
            raise ValueError(f"Unsupported role '{role}' for user {email}")

        name = normalised.get("name") or email.split("@", 1)[0]
        display_name = normalised.get("display_name") or name
        reply_to = (
            normalised.get("reply_to")
            or normalised.get("smtp_reply_to")
            or normalised.get("smtp_reply")
            or email
        )

        user = User(
            email=email,
            name=name,
            password_hash=generate_password_hash(password),
            role=role,
            is_active=True,
        )

        smtp_host = normalised.get("smtp_host") or None
        smtp_port = _coerce_int(normalised.get("smtp_port"))
        smtp_username = normalised.get("smtp_username") or None
        smtp_password = normalised.get("smtp_password") or None
        smtp_sender = normalised.get("smtp_sender") or None
        smtp_reply_to = (
            normalised.get("smtp_reply_to")
            or normalised.get("smtp_reply")
            or reply_to
        )
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
        if role == "designer":
            designer = Designer(
                user=user,
                display_name=display_name,
                email=email,
                reply_to_email=reply_to,
                is_active=True,
            )

        db.session.add(user)
        if designer is not None:
            db.session.add(designer)

        created += 1

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()

    return ImportSummary(created=created, skipped=skipped)
