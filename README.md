# PlayConsoleDeveloperAccount

Central Google Play Console release pipeline, shared by every Android app in this
account. One reusable GitHub Actions workflow + one Python CLI here; each app repo
only needs a thin caller workflow and a handful of secrets.

- `scripts/play_publish.py` — CLI wrapping the [Android Publisher API v3](https://developers.google.com/android-publisher).
- `.github/workflows/play-deploy.yml` — reusable workflow (`workflow_call`) that builds/signs
  the app (when uploading), then runs `play_publish.py`.
- `examples/caller-workflow-example.yml` — template to copy into an app repo.

## What this pipeline can and can't do

Google splits Play Store publishing into two kinds of work, and only one of them has
an API:

| Step | Automated by this pipeline? |
|---|---|
| Create the app in Play Console | **No — manual, one-time per app.** There is no "create application" endpoint in the Play Developer API. Play Console → **Create app** → name / default language / app-or-game / free-or-paid → accept the policy checkboxes. |
| Content rating (IARC), Data safety form, Target audience & content, Ads declaration, government/financial/news app declarations, App access instructions, privacy policy URL | **No — manual, one-time per app.** Play Console → **App content**. No public API exists for any of these. Google requires them before releasing to *any* track, including internal testing. |
| App Signing enrollment | **No — manual, one-time per app**, in Play Console → **Setup → App signing**. |
| Store listing text (title, descriptions, video) | **Yes** — `update-listing` |
| Store graphics (icon, feature graphic, screenshots, promo/TV/wear assets) | **Yes** — `upload-images` |
| Uploading a build (AAB/APK) to a track | **Yes** — `upload` |
| Staged rollout percentage | **Yes** — `upload` (initial) / `set-rollout` (adjust an existing release) |
| Promoting a release between tracks | **Yes** — `promote` |
| Halting a rollout | **Yes** — `halt` |
| Checking current release/track status | **Yes** — `status` |

So for a **brand-new app**, the one-time bootstrap (create app + declarations + app
signing, a few minutes in the Play Console UI) always has to happen first, by a human.
Every release after that — for that app and any future app — is 100% this pipeline,
no further manual Play Console UI steps required.

## One-time setup

### 1. Create the Play Developer API service account

1. In [Google Cloud Console](https://console.cloud.google.com/), create (or reuse) a
   project, then **IAM & Admin → Service Accounts → Create service account**.
2. Create a JSON key for it and download it — this is the `PLAY_SERVICE_ACCOUNT_JSON`
   secret content below.
3. In Play Console → **Setup → API access**, link the Cloud project, then grant the
   service account access with at least **Release manager** permissions. You can scope
   it to specific apps or to all apps on the account.

### 2. Generate a release keystore per app

Each app needs its own signing keystore, generated once and reused for every future
release (losing it means you can never update that app again). If the app doesn't have
one yet, generate it the same way `festive-card-creator/scripts/generate_keystore.sh`
does:

```bash
keytool -genkeypair -v -keystore keystore/release.jks -alias release \
  -keyalg RSA -keysize 2048 -validity 10000 -storepass <password> -keypass <password>
```

Keep the store and key password identical (PKCS12, the default keystore format,
requires it). Never commit the `.jks` file or its passwords.

### 3. Add secrets to each app repo

GitHub personal accounts don't support org-wide Action secrets, so add these to
**each app repo's** Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `PLAY_SERVICE_ACCOUNT_JSON` | Full contents of the service account JSON key |
| `ANDROID_KEYSTORE_BASE64` | `base64 -w0 keystore/release.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | The keystore/key password |
| `ANDROID_KEY_ALIAS` | The key alias (`release` in the example above) |
| `ANDROID_KEY_PASSWORD` | Same as the keystore password |

`ANDROID_*` secrets are only needed for `action: upload` (they sign the build);
`set-rollout` / `promote` / `halt` / `update-listing` / `upload-images` / `status`
only need `PLAY_SERVICE_ACCOUNT_JSON`.

### 4. Add the caller workflow to the app repo

Copy `examples/caller-workflow-example.yml` to `.github/workflows/deploy-playstore.yml`
in the app repo, set `package_name` (and `module` if the app module isn't named `app`),
commit, and push. Trigger it from the **Actions** tab via **Run workflow**, picking
`action`/`track`/`rollout` as needed.

## Onboarding a new app from scratch (checklist)

1. **Manual, in Play Console:** create the app, complete App content declarations,
   enroll in App signing.
2. **Manual, once:** generate a release keystore (§2 above), add the five secrets to
   the new repo (§3 above).
3. **This repo, once:** add the caller workflow (§4 above) to the new app repo.
4. **From here on, all via workflow_dispatch, no more Play Console UI:**
   - `action: upload, track: internal, rollout: "1.0"` — first release.
   - `action: update-listing` / `action: upload-images` — fill in the store page.
   - `action: upload, track: internal, rollout: "0.1"` then repeated
     `action: set-rollout` calls with increasing `rollout` — staged rollout.
   - `action: promote, from_track: internal, to_track: production` — promote once ready.
   - `action: halt` — pause a bad rollout.
   - `action: status` — check what's live on each track.

## `play_publish.py` reference

```
play_publish.py --credentials <service-account.json> upload \
  --package <id> --track <track> --file <aab-or-apk> \
  [--artifact-type aab|apk] [--rollout 0.0-1.0] [--release-notes <dir>]

play_publish.py --credentials <service-account.json> set-rollout \
  --package <id> --track <track> --rollout <0.0-1.0>

play_publish.py --credentials <service-account.json> promote \
  --package <id> --from-track <track> --to-track <track>

play_publish.py --credentials <service-account.json> halt \
  --package <id> --track <track>

play_publish.py --credentials <service-account.json> update-listing \
  --package <id> [--language en-US] \
  [--title <str>] [--short-description <str>] [--full-description <str>] [--video-url <url>]

play_publish.py --credentials <service-account.json> upload-images \
  --package <id> [--language en-US] --image-type <type> --dir <dir-of-images>

play_publish.py --credentials <service-account.json> status \
  --package <id> [--track <track>]
```

`--release-notes <dir>` expects files named `<language-code>.txt`, e.g. `en-US.txt`.

Run it locally too (`pip install -r requirements.txt` first) — useful for a manual
`status` check or a one-off `set-rollout` without going through CI.
