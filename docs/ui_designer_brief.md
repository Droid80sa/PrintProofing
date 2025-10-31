# Proof Approval System – UI Design Brief

## Project Snapshot
- **Product**: Web-based proof approval platform supporting agencies and in-house design teams.
- **Primary Users**:
  - *Admins*: Manage users, branding, customer accounts, and oversee all proofs.
  - *Designers*: Upload proofs, manage customer relationships, trigger customer invites.
  - *Customers*: Review proofs via secure portal, provide approval/decline decisions.
- **Goals**:
  1. Deliver a streamlined, branded review experience for customers.
  2. Help designers/admins manage proofs, customers, and notifications efficiently.
  3. Support a white-label look-and-feel that adapts to each organization’s brand.

## Brand & Visual Direction
- **Branding Source**: Admins upload logos and set colors via `branding` configuration.
- **Default Palette**:
  - Primary color: `#000000` (overridden per tenant)
  - Accent colors: `approve_button_color`, `reject_button_color`, `general_button_color`
  - Background: configurable; defaults to white (#FFFFFF).
- **Tone**:
  - Professional and reassuring for clients reviewing proofs.
  - Efficient, uncluttered dashboards for admins/designers.
  - Accessibility-friendly (contrasts, clear states, responsive).
- **Typography**: Defaults to sans-serif (`Roboto, sans-serif`); should be easily swapped.

## Key Experiences

### 1. Customer Portal
- Entry points: `/customer/login`, `/customer/invite/<token>`, `/customer/reset/<token>`.
- Screens:
  - Login: branded hero block (logo, company name, tagline), email/password form, forgot password link.
  - Invite acceptance: password creation with security guidance.
  - Dashboard & proof view: lists assigned proofs; each proof page shows version selector, annotations/compare placeholders, approval form.
- Interactions:
  - Approve/Decline flow uses modal to capture disclaimer acceptance and optional decline feedback.
  - If not authenticated, proof pages prompt portal login (with banner).

### 2. Proof Review Page (`/proof/<job_id>`)
- Audience: Customers (sometimes staff preview).
- Content:
  - Hero with job name, status badge, designer info.
  - Version selector, compare/annotate buttons (annotations currently placeholder).
  - Embedded PDF/image viewer; fallback download CTA.
  - Approval form (Approve/Reject) with CSRF token and optional decline reason.
  - Disclaimer modal gating approval.
  - For uninvited customers, upload notifications include invite link.
- Visual cues:
  - Status colors (approved=green, declined=red).
  - Info banner when portal login is encouraged.

### 3. Designer Dashboard
- Widgets:
  - Proof listing table with job name, status, last updated, decision summary.
  - Quick actions: upload new proof, create customers, trigger invites.
  - SMTP panel showing personal configuration status with “Send Test Email”.
- Designer customer page:
  - Table with customer info, invite status chips (pending, expired, active).
  - Actions: edit, delete, send invite (disabled if invite already pending).

### 4. Admin Experience
- Navigation: Admin dashboard, Users, Customers, Upload, Settings, Logo, Disclaimer, Export.
- Admin customers:
  - Table with invite status (pending/expires, consumed, none).
  - Modal for add customer; edit page includes “Send Invite” card with status detail.
- Users:
  - Manage roles, activation, onboarding designers with SMTP settings.
- Settings:
  - Branding controls (colors, fonts, disclaimers, theme CSS).
- Upload form:
  - Designer selection, customer selection, job details, file upload, “Notify customer” toggle with subject/body templates.
  - If customer lacks credentials and portal enabled, upload enqueues invite link automatically.

## Functional Requirements for UI
- **Responsiveness**: All core pages must work on mobile (especially client-facing proof view and login).
- **Accessibility**:
  - Ensure keyboard navigation and focus styles.
  - Provide sufficient color contrast (WCAG AA minimum).
  - Labels and error messages for all form inputs.
- **State Feedback**:
  - Flash messages (success/error/info/warning) already surfaced; design should style them consistently.
- **Button Styles**:
  - Approve/Reject buttons use explicit colors; hover and active states indicated.
  - General buttons align with `branding.general_button_color`.
- **Modals**:
  - Disclaimer and loading overlays share modal styling (centered card on dimmed background).
- **Invite Status Indicators**:
  - Visual tokens (badge/pill) for “Invite pending”, “Expired”, “Active”, etc., ideally color-coded.

## Assets & Theme
- Logo: `branding.logo_url` served as `/static/uploads/logo.png`.
- Theme CSS: `/theme.css` generated at runtime from admin settings—design should work with variable overrides.
- Email notifications reuse branding colors; ensure app UI aligns with email appearance for consistent experience.

## Known Placeholders & Future Enhancements
- Compare versions (`/proof/<job_id>/compare`) and annotate (`/proof/<job_id>/annotate`) currently placeholders; design should anticipate eventual implementation (e.g., side-by-side layout, annotation toolbar).
- Customer dashboard landing page (post-login) minimal; opportunity to surface proof summaries or onboarding tips.
- Portal invite/resend feedback limited to flash messages; consider inline status to reduce context switching.

## Deliverables Expected from UI Design
1. **Component Library** with reusable styles (buttons, form fields, tables, modals, status badges).
2. **Responsive Layouts** for:
   - Customer login/invite/reset.
   - Proof review page (desktop + mobile).
   - Designer dashboard & customers list.
   - Admin customer list/detail and upload screens.
3. **State Variations**:
   - Success/error states for forms and notifications.
   - Disabled/in-progress states for actions (e.g., sending invite, uploading).
4. **Annotation/Comparison Concepts** (wireframe or visual directions for future build).

By aligning UI updates with these flows and brand hooks, we ensure the platform feels cohesive across all personas while remaining easily themeable for each organization deploying it.
