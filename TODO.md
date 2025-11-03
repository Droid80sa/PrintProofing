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

## 5. Tailwind UI Migration Roadmap
- [x] **Foundations**: Add Tailwind build tooling (PostCSS/Vite), map branding colors into theme config, and update `base.html` / `base_no_nav.html` to load the compiled bundle alongside existing flash/CSRF blocks.
- [x] **Component Library**: Translate the “Updated UI” patterns into reusable Tailwind partials (buttons, status pills, tables, modals) and document usage.
- [x] **Customer Portal**: Migrate `customer/login.html`, `customer/invite.html`, `customer/reset*.html`, and `proof.html` to Tailwind components, preserving all Jinja logic and approval flows.
- [x] **Designer Screens**: Refactor `designer_dashboard.html`, `designer_customers.html`, and related partials to the new layout, wiring filters and invite status chips to existing data helpers.
- [x] **Admin Views**: Apply Tailwind to admin pages (`admin_customers.html`, `admin_customer_edit.html`, `admin_settings.html`, upload flow), ensuring forms/tests continue to pass.
- [x] **Cleanup & QA**: Remove obsolete CSS, reconcile inline styles, run pytest + manual regression, and capture design tokens/partials in docs for future iterations.

## 6. Polishing & Automation
- [x] Add automated Tailwind build step to CI / deployment pipeline (run `npm run build:css`).
- [x] Introduce visual regression snapshots (Playwright / Percy) for key screens (login, proof review, dashboards).
- [x] Document the new Tailwind components and workflows in `docs/` with screenshots for onboarding designers.
- [x] Audit remaining legacy templates or inline styles for removal (e.g. compare/annotate placeholders) and align with shared macros.
