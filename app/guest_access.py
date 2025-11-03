"""Guest proof access helpers."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

from app.models import ProofGuestAccess


DEFAULT_EXPIRY_HOURS = 168  # 7 days
def generate_guest_token() -> str:
    return secrets.token_urlsafe(20)
def generate_guest_pin() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"
def build_guest_access(
    proof,
    *,
    email: str,
    name: Optional[str] = None,
    expires_hours: Optional[int] = None,
) -> Tuple[ProofGuestAccess, str]:
    token = generate_guest_token()
    pin = generate_guest_pin()
    now = datetime.now(timezone.utc)
    expires_at = None
    if expires_hours and expires_hours > 0:
        expires_at = now + timedelta(hours=expires_hours)
    elif expires_hours is None:
        expires_at = now + timedelta(hours=DEFAULT_EXPIRY_HOURS)

    guest_access = ProofGuestAccess(
        proof=proof,
        email=email,
        name=name or None,
        access_token=token,
        pin_hash=generate_password_hash(pin),
        expires_at=expires_at,
    )
    return guest_access, pin
def pin_is_valid(access: ProofGuestAccess, pin: str) -> bool:
    return check_password_hash(access.pin_hash, pin)
def access_is_active(access: ProofGuestAccess) -> bool:
    return access.is_active()
