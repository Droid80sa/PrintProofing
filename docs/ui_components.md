# Tailwind Component Cheatsheet

The refreshed UI shares a small set of Tailwind-backed primitives. Import the Jinja macros and reuse them across templates instead of recreating custom markup.

## Using the Macros

```jinja
{% import 'components/ui_macros.html' as ui %}
```

### Buttons

```jinja
{{ ui.button("Primary Action") }}
{{ ui.button("Secondary", variant="secondary") }}
{{ ui.button("Upload", icon="upload", extra_classes="w-full") }}
{{ ui.button("Visit", href=url_for('designer_dashboard')) }}
```

- Variants: `primary`, `secondary`, `ghost`, or pass a direct Tailwind class string.
- Sizes: `sm`, `md`, `lg`.
- Icons use Google Material Symbols (already loaded in the prototype pages).

### Status Badges

```jinja
{{ ui.status_badge(proof.status) }}
{{ ui.status_badge('pending', 'Awaiting client input') }}
```

Recognised states: `approved`, `pending`, `declined`, `expired`, `active`. Other values fall back to a neutral badge.

### Cards

```jinja
{% call ui.card(title="Email Configuration", subtitle="Connect SMTP to notify customers.") %}
  <p class="text-sm text-slate-600">Custom card content goes here.</p>
{% endcall %}
```

The `card` macro wraps the inner block in the shared border, shadow, and padding used in the design prototypes.

## Tailwind Workflow

- Source file: `frontend/tailwind.css`
- Build command: `npm run build:css`
- Output: `app/static/dist/main.css`

The Tailwind config exposes brand colours via CSS variables (`brand.primary`, `brand.approve`, etc.) so pages stay aligned with the runtime branding data.

Store example screenshots in `docs/screenshots/` (see `visual_regression.md` for guidance) so designers can review real renders alongside the coded components.

### Visual Regression (Recommended)

- Take lightweight screenshots (e.g. `python -m playwright codegen` or Cypress) of key pages after each release.
- Track deltas in a CI-friendly snapshot tool (Percy, Chromatic, or Playwright Trace Viewer).
- Document expected states (success, pending, error) so designers know which screens to review.
