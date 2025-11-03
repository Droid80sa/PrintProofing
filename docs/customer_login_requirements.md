# Customer Login Experience – Product Requirements

## Objectives
- Replace public proof links with authenticated access for customers without disrupting designer/admin workflows.
- Preserve legacy share links during transition while encouraging migration to the new login flow.
- Capture auditable activity for customer access and keep credential management maintainable for internal staff.

## Roles & Personas
- **Customer (new)**: Can sign in, view proofs assigned to their organisation, submit approve/decline responses, and review past decisions.
- **Designer (existing)**: Continues to upload proofs and optionally invite associated customers; can see customer access status for their proofs.
- **Admin (existing)**: Manages user/designer accounts plus customer auth lifecycle (invite, suspend, reset), views audit history, configures rollout settings.

## Authentication Flows
1. **Invitation**
   - Admin or designer triggers an invite from proof upload confirmation or customer management screen.
   - System generates a time-bound token (default 72h) and emails the customer with a “set your password” link.
   - Invite completion requires password meeting policy and acceptance of terms.
   - Expired/invalid tokens direct the customer to request a fresh invite.
2. **Login**
   - Customer enters email + password on `/customer/login`.
   - Rate limiting mirrors staff login defaults (`LOGIN_MAX_ATTEMPTS`, `LOGIN_ATTEMPT_WINDOW`).
   - Successful login establishes dedicated customer session storage slot (`customer_session_id`) independent from staff sessions.
3. **Password Reset**
   - Link available from login form.
   - Customer submits email; if recognised and active, system issues a reset token (24h) via email.
   - Reset form enforces password policy and rotates credentials, invalidating existing sessions.
4. **Logout**
   - Explicit button within customer UI; session cleared server-side.

## Password & Security Requirements
- Minimum length 12 characters, must include at least one alpha and one numeric/symbol character.
- Store credential hash using `werkzeug.security.generate_password_hash`.
- Tokens for invite/reset stored hashed with expiry timestamps; one active token per purpose per customer.
- Audit log records sign-in attempts (success/failure), invite sends, reset requests, and proof view events.

## Data Model Extensions
- `CustomerCredential` (1–1 with existing `Customer`):
  - `customer_id` (FK), `password_hash`, `last_login_at`, `is_active`, `mfa_secret` (reserved, nullable).
- `CustomerAuthToken`:
  - `id`, `customer_id`, `token_hash`, `purpose` (`invite` | `reset`), `expires_at`, `consumed_at`, `issued_by_user_id` (nullable).
- `CustomerLoginEvent`:
  - `id`, `customer_id`, `ip_address`, `user_agent`, `successful`, `occurred_at`.
- Proof assignment remains via `proof.customer_id`; customer access limited to proofs with matching customer.

## UI & Routing
- `/customer/login`, `/customer/logout`, `/customer/invite/<token>`, `/customer/reset/<token>` handled by new blueprint.
- Customer dashboard lists assigned proofs with status, version history, and decision links.
- Proof view URL becomes `/customer/proof/<share_id>` (mirrors existing layout, hides admin/designer controls).
- Legacy `/proof/<share_id>` remains functional when `LEGACY_PUBLIC_LINKS_ENABLED=1`; renders message prompting login transition.

## Session & Authorisation
- Separate session namespace to avoid collisions with staff auth.
- Decorator `customer_login_required` guards all customer-facing routes.
- Proof fetch ensures `proof.customer_id == g.current_customer.id`; otherwise respond 404 to avoid leaking presence.
- Maintain CSRF protection for forms (`customer_csrf_token`) aligned with existing approach.

## Rollout & Configurability
- Feature flag env vars:
  - `CUSTOMER_LOGIN_ENABLED` (default `false` while in development).
  - `LEGACY_PUBLIC_LINKS_ENABLED` (default `true` initially; set `false` once migration complete).
- Admin UI toggle warns when disabling legacy links; requires confirmation when outstanding proofs lack customer credentials.
- Logging: structured JSON with `event` fields (`customer_login_success`, `customer_login_failure`, etc.) for monitoring.

## Dependencies & Integrations
- Reuse `send_email_notification` with customer-friendly templates; fallback to global SMTP if designer override absent.
- Extend tests to cover blueprint routes, token lifecycle, proof access control, and regression on legacy form submission.

## Acceptance Criteria
1. Customers can complete invite, sign in, view their proofs, and submit decisions without accessing other customers’ data.
2. Admins can resend invites and deactivate customer access; audit history reflects actions.
3. Attempts to access `/customer/proof/<id>` without auth are redirected to login, while legacy share links follow configured fallback.
4. Automated tests cover happy path and key failure scenarios (expired token, wrong password lockout, unauthorised proof access).
5. Documentation outlines rollout steps and support guidance for customer onboarding.
