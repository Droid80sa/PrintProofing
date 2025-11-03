# Customer Upload Notifications – Requirements

## Objectives
- Allow designers/admins to optionally notify a customer immediately after uploading a proof.
- Provide a customizable email (subject/body) that uses the uploader’s SMTP settings and includes proof context.
- Record what was sent, when, and whether delivery succeeded to support future resend/review workflows.

## Trigger & UI Flow
1. **Upload Form**
   - Add a `Notify customer now` checkbox.
   - When selected, expose a “Compose Email” button that opens a modal editor.
2. **Modal Editor**
   - Prefill subject/body with defaults (`New proof ready: <job_name>`, templated body with greeting, summary, proof link, and designer signature).
   - Merge fields available when composing:
     - `{{customer_name}}`
     - `{{job_name}}`
     - `{{proof_link}}`
     - `{{designer_name}}`
   - Modal validates non-empty subject/body before saving back to hidden form inputs.
3. **Submission**
   - Upload form POST includes `notify_customer=on`, subject, and body values when the modal is saved.
   - If notify is requested without a composed message, backend fills in the default template.

## Delivery Behaviour
- Email sent after proof + proof version records commit successfully.
- Uses `send_email_notification`, passing the designer’s associated `User` to honour per-user SMTP overrides; fallback to global sender when the designer lacks overrides.
- Runs asynchronously via the existing `EMAIL_QUEUE`; failures are caught and recorded.
- UI feedback:
  - On success: flash neutral/success message and highlight in upload success page (“Customer notification queued”).
  - On failure: flash warning and surface log entry with `status=failed` + error summary.

## Data Model
- `customer_notifications` table (new SQLAlchemy model + migration):
  - `id` UUID primary key.
  - `proof_id` FK (`proofs.id`) – reference high-level proof.
  - `proof_version_id` FK – specific version notified.
  - `customer_id` FK – recipient.
  - `sent_by_user_id` FK (`users.id`) – uploader.
  - `subject`, `body` (text) – final rendered message.
  - `recipient_email`, `sender_email`, `reply_to_email`.
  - `status` (`queued`|`sent`|`failed`).
  - `error_message` (nullable) – truncated failure detail.
  - `queued_at`, `sent_at`, `created_at`, `updated_at`.
- Ensure relationships allow eager loading for dashboards and future resend tooling.

## Logging & Resend Hooks
- Log creation occurs before queuing email with `status=queued`.
- After async send callback, update row to `sent` or `failed`.
- Even on failure, retain body/subject for audit trail.
- Provide helper function `record_notification_delivery(result)` to encapsulate status updates.
- Leave placeholders for future resend endpoint (e.g., `CustomerNotification.resend()` stub or service).

## Configuration & Defaults
- New env flag `CUSTOMER_NOTIFY_DEFAULT_SUBJECT` / `CUSTOMER_NOTIFY_DEFAULT_BODY` optional overrides.
- If unset, fall back to baked-in template using merge fields.
- Add README instructions covering workflow and template customization.

## Testing
- Unit tests for:
  - Default template rendering with merge fields.
  - Upload route creating `CustomerNotification` when notify selected.
  - Handling email queue success vs failure.
- Integration test (Flask test client) simulates upload with notification; asserts database log, flash messaging, and that share link included.

## Accessibility & UX
- Modal accessible: focus trap, ESC to close, labelled fields.
- Provide character count or minimal formatting guidance.
- Keep notify controls hidden for customers without email (disable checkbox with tooltip).
