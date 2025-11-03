#!/usr/bin/env sh
set -e

if [ "${WAIT_FOR_DB:-true}" = "true" ] && [ -n "${DATABASE_URL}" ]; then
  python <<'PY'
import os
import time
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

database_url = os.environ["DATABASE_URL"]
scheme = urlparse(database_url).scheme

if scheme.startswith("postgres"):
    engine = create_engine(database_url)
    last_exc = None
    for attempt in range(1, 11):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            break
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            time.sleep(2)
    else:  # pragma: no cover
        raise SystemExit(f"Database is unavailable: {last_exc}")
PY
fi

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  alembic upgrade head
fi

exec "$@"
