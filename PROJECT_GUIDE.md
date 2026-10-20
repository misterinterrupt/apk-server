# APK Server — Project Guide

> **Read this file first** at the start of any new session. It is the complete
> reference for how this repo works, what's registered, and what features exist.

## What this is

A **build archive + HTTP server** for delivering debug APKs to a phone over the
LAN/tailnet. Workflow:

1. **`publish.sh`** — builds a debug APK via Gradle, names it with git metadata,
   archives it under `builds/<project-slug>/`.
2. **`serve.py`** — serves a web UI that lists all archived builds with project
   tabs, plus a JSON API and direct APK downloads.

No database, no restart needed. `serve.py` re-scans `builds/` on every request.

## File layout

```
apk-server/
├── serve.py                          # HTTP server (stdlib only, Python 3)
├── publish.sh                        # Gradle debug-APK build + archive script
├── play-publish.sh                   # Signed release AAB + Play Store publish
├── play-enroll.py                    # TOTP enrollment (authenticator setup)
├── add-project.sh                    # Register a new Android project
├── projects.json                     # Project registry (slug, name, namespace, color)
├── PROJECT_GUIDE.md                  # This file — read it first
├── README.md                         # User-facing quick start
├── PLAY_STORE_SETUP.md               # How to get Play Store API credentials
├── TOTP_OTP_GATE.md                  # How the authenticator-gated publish works
├── builds/                           # Archived APKs (gitignored)
│   └── <project-slug>/
├── robotnerd-apk-server.service      # systemd unit
└── totp.py                           # TOTP validation (stdlib)
```

## Project configuration

All project registration lives in `projects.json`. Example:

```json
{
  "projects": [
    {
      "slug": "robotnerd",
      "name": "RobotNerd",
      "color": "#7c4dff",
      "namespace": "com.ntrpt.robotnerd"
    }
  ]
}
```

Each entry is `{slug, name, color, namespace}`. The **slug** is the folder name
under `builds/` and the URL path segment. The color drives the UI accent. The
**namespace** is the Android application ID for auto-detection and Play publishing.
Only projects with an existing `builds/<slug>/` directory show up as tabs.

## Build naming

```
<slug>-<build>-<commit>[-dirty].apk
```

- **build** — `git rev-list --count HEAD` (monotonically increasing integer)
- **commit** — short git hash (`git rev-parse --short HEAD`)
- **dirty** — appended when working tree has uncommitted changes

Dirty builds always rebuild. Clean builds skip if already archived (use
`--force` to override).

## Publish commands

```bash
# Auto-detect (run from inside the Android project dir)
./publish.sh

# Explicit project root
./publish.sh --project-root /path/to/android-project

# Named project
./publish.sh --project myapp

# Force rebuild even if same commit already archived
./publish.sh --force
```

## Serve

```bash
./serve.py               # port 8080
PORT=9000 ./serve.py     # custom port
```

Runs as a systemd user service: `robotnerd-apk-server.service`.

## JSON API

| Endpoint | Returns |
|---|---|
| `GET /api/projects` | List of project sections `[{id, name, color}]` |
| `GET /api/<project>/builds` | List of builds for a project |

## Adding a new project

```bash
./add-project.sh \
    --slug myapp \
    --name "My App" \
    --color "#00BCD4" \
    --namespace com.example.myapp
```

This updates `projects.json` and creates `builds/myapp/`.
Idempotent — safe to re-run. Nothing needs to change in the target Android
project itself.

---

## Play Store Publishing Feature

The server can publish apps to the **Google Play Store** via the
**Google Play Developer API**.

### How it works

1. **Open an "edit"** for a package name
2. **Upload** an `.aab` (Android App Bundle)
3. **Assign** it to a track (internal testing, production, etc.)
4. **Commit** the edit — goes live on that track

### Two credentials needed (both described in `PLAY_STORE_SETUP.md`)

1. **Service Account JSON key** — authenticates to the Play API. Created in
   Google Cloud Console, linked to Play Console with per-app release permission.
2. **Release signing keystore** — signs the AAB. Created with `keytool`,
   configured in the app's `build.gradle` via `signingConfigs`.

### TOTP / OTP gate (`TOTP_OTP_GATE.md`)

Every Play publish requires a **6-digit code from your authenticator app**
(Google Authenticator, Authy, etc.). The server validates it (RFC 6238 TOTP,
pure stdlib — no packages) before touching the Play API. This means the
credential on disk alone can't publish anything without a human approving.

### Dependency safety rules

Package-ecosystem attacks (typosquatting, malicious updates, dependency
confusion, compromised upstream packages) are constant. We don't ban packages,
but we follow two hard rules before adding any dependency:

#### Rule 1: Pin versions — never suck in "latest"

Every dependency must be **pinned to a specific version** in a lockfile.
Never use bare `package-name` or `>=` ranges without an upper bound.

#### Rule 2: Check before installing

Before adding any new dependency (or upgrading a pinned one), check it against
known-compromise databases (GitHub Security Advisories, OSV.dev).

#### General approach

Where we can trivially use Python stdlib or already-installed CLI tools
(`openssl`, `curl`), we do — fewer moving parts, nothing to verify.

### Important constraints

- **First upload is always manual.** Google requires the very first version of a
  brand-new app to be uploaded through the Play Console web UI by hand.
- **You must build AABs, not debug APKs.** `publish.sh` builds
  `:app:assembleDebug`. Play publishing needs `:app:bundleRelease` (signed).
- **Version codes must increase.** Each Play upload needs a higher `versionCode`
  than the last live one. The git-count-based build numbers fit this well.
