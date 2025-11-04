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
from pathlib import Path

from app.app import app
from app.user_import import import_users_from_csv


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
        default="auto",
        help="CSV delimiter (default: auto-detect).",
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

    effective_delimiter = None if delimiter == "auto" else delimiter

    with app.app_context():
        with csv_path.open("r", encoding="utf-8-sig") as handle:
            summary = import_users_from_csv(
                handle,
                delimiter=effective_delimiter,
                skip_existing=skip_existing,
                dry_run=dry_run,
            )

    status = "DRY RUN" if dry_run else "Imported"
    print(f"{status}: created {summary.created} user(s); skipped {summary.skipped}.")


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
