# Proofs App – Next Phase Roadmap

This roadmap captures the upcoming priorities now that the initial customer and versioning work is complete.

## 1. Customer Login Experience
- [x] Document detailed requirements (roles, password policy, invite/reset flows).
- [x] Extend the data model to store customer credentials and login audit events.
- [x] Build customer-facing login/registration UI and supporting Flask routes.
- [x] Protect proof views behind customer authentication, with a fallback plan for legacy share links.
- [x] Update copy/docs to emphasise that a customer login system is planned to enhance security and provide a personalised experience.

## 2. Customer Email Notifications on Upload
- [x] Add an optional “Notify customer” workflow to the proof upload form.
- [x] Provide a popup email editor with prefilled subject/body, including proof links and merge fields.
- [x] Ensure designers can edit the message before sending and that it uses the selected designer’s SMTP settings for branded delivery.
- [x] Handle delivery errors gracefully and surface feedback to the uploader.
- [x] Store a preview/log of the outbound message for auditing and resend capabilities.

## 3. Supporting Improvements
- [x] Surface SMTP configuration validation to designers/admins (test send, warnings).
- [x] Expand automated and manual tests to cover the new login and email scenarios.
- [x] Review accessibility and responsiveness of the new customer-facing components.
- [x] Document deployment/rollout steps, including communications to existing customers about login and notification changes.

## 4. Customer Invite Workflow via GUI
- [x] Expose an "Send Invite" action in the admin customer list/detail views that triggers the existing invite token flow and sends the email.
- [x] Track and display invite status (pending, sent, expired) per customer with timestamps in the UI.
- [x] Allow designers to trigger invites from their customer management screen when an account lacks credentials.
- [x] When uploading a proof, detect customers without login credentials and include an invite link automatically in the notification email.
- [x] Provide safeguards to avoid sending duplicate invites (warn when an unexpired invite already exists).
- [x] Add tests covering GUI invite actions and the conditional inclusion of invite links in proof notifications.
