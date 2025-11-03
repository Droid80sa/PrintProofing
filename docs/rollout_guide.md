# Deployment & Rollout Guide – Customer Login, Notifications, SMTP

## Prerequisites
- Apply database migrations: `alembic upgrade head` (adds customer auth tables, notification log, SMTP status columns).
- Ensure environment variables are updated:
  - `CUSTOMER_LOGIN_ENABLED`, `LEGACY_PUBLIC_LINKS_ENABLED`
  - Optional notification templates: `CUSTOMER_NOTIFY_DEFAULT_SUBJECT`, `CUSTOMER_NOTIFY_DEFAULT_BODY`
- Confirm per-user SMTP credentials are recorded for designers who should send branded mail.

## Rollout Checklist
1. **Database**
   - Run Alembic upgrade in each environment.
   - Verify new tables (`customer_*`, `customer_notifications`) exist; monitor migration output.
2. **Configuration**
   - Enable customer login behind a feature flag (`CUSTOMER_LOGIN_ENABLED=true`) in staging first.
   - Keep `LEGACY_PUBLIC_LINKS_ENABLED=true` while customers transition; disable once all have credentials.
   - Review `.env` for optional notification templates or leave defaults in place.
3. **SMTP Validation**
   - For every designer, visit Admin → Users → Edit and run “Send Test Email”.
   - Resolve any failures surfaced in the UI before go-live; designers can re-test from My Proofs.
4. **Customer Communication**
   - Announce the new login experience and optional immediate notifications to existing customers.
   - Provide invite/reset instructions and explain that legacy share links will be retired once the portal is enforced.
5. **Testing**
   - Execute the automated suite (`./venv/bin/pytest`).
   - Manually upload a proof with “Notify customer now” checked to confirm email delivery + log entry.
   - Verify designer dashboard warnings and test form behave as expected on desktop/mobile.
6. **Monitoring**
   - Review `customer_notifications` table for queued/failed records.
   - Track SMTP failures surfaced on the admin user list and designer dashboard after launch.

## Rollback Notes
- Disable customer login (`CUSTOMER_LOGIN_ENABLED=false`) to fall back to legacy links.
- Notifications remain optional; uncheck “Notify customer now” or remove SMTP host/port to revert to default mailer.
- Database schema additions are backward-compatible; no destructive changes were introduced.
