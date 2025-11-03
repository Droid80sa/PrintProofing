# Visual Regression Workflow

The Playwright setup in `tests/visual/` enables lightweight visual checks for the key UI screens.

## Prerequisites

1. Start the Flask app so pages are reachable (e.g. `docker compose up`).
2. Export `VRT_BASE_URL` so Playwright knows where to point:

   ```bash
   export VRT_BASE_URL=http://localhost:5010
   ```
3. Install the Playwright browsers once:

   ```bash
   npx playwright install
   ```

## Capturing Baselines

1. Run the tests in update mode to capture the first set of snapshots:

   ```bash
   VRT_BASE_URL=http://localhost:5010 npx playwright test --update-snapshots
   ```
2. Commit the generated snapshots under `tests/visual/specs/__screenshots__`.

## Regular Runs

Execute the smoke suite locally or in CI whenever you change templates:

```bash
npm run test:visual
```

If `VRT_BASE_URL` is not defined, the suite skips automatically, so it is safe to wire into CI jobs that don’t boot the web app.

## Adding More Pages

1. Add a new `test()` block in `tests/visual/specs/smoke.spec.ts`.
2. Navigate to the target route and call `expect(page).toHaveScreenshot('descriptive-name.png')`.
3. Regenerate snapshots (`--update-snapshots`) so the new baseline is checked in.

Store optional design references (e.g. exported Figma frames) under `docs/screenshots/` for designers to compare against the automated captures.
