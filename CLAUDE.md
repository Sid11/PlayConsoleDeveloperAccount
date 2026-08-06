# PlayConsoleDeveloperAccount — Project Rules

This repo is the **shared Play Console deployment pipeline** for every Android app
built under this account — currently `budget-tracker` and `festive-card-creator`, and
any future app. It is not itself an app; nothing here should assume a specific package
name, keystore, or app-specific detail. `README.md` is the source of truth for setup
and usage — read it before making changes here.

## What lives here and why

- `scripts/play_publish.py` — the only thing that talks to the Android Publisher API
  (v3). All release mechanics (upload, rollout %, promote, halt, listing text, store
  images, status) go through this one CLI so app repos never duplicate API logic.
- `.github/workflows/play-deploy.yml` — the reusable `workflow_call` workflow every app
  repo's caller workflow (`.github/workflows/deploy-playstore.yml`) points at via
  `uses: Sid11/PlayConsoleDeveloperAccount/.github/workflows/play-deploy.yml@main`.
- `examples/caller-workflow-example.yml` — template for onboarding a new app repo.

## Making changes

- This is reused by multiple app repos live in production — a breaking change here
  (renamed input, changed secret name, altered subcommand flags) breaks every app's
  deploy workflow at once. Keep `play_publish.py`'s CLI surface and
  `play-deploy.yml`'s `inputs`/`secrets` names backward compatible, or update every
  caller workflow in the same change.
- Don't add app-specific logic (a hardcoded package name, a specific keystore layout,
  etc.) here — that belongs in the calling app repo's own workflow/secrets. This repo
  stays generic.
- The Android Publisher API cannot create a new app or complete its policy
  declarations (content rating, data safety, target audience, privacy policy) — that's
  Play Console UI only, always manual, for every app, forever. Don't try to work around
  this; document it instead (see README's "What this pipeline can and can't do" table).
- Verify changes to `play_publish.py` with `python -m py_compile` and a `--help` pass
  on every subcommand at minimum; there's no live Play Console access from a dev/CI
  sandbox to test the real API calls against.
