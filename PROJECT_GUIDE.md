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
├── add-project.sh                    # Register a new Android project
├── PROJECT_GUIDE.md                  # This file — read it first
├── README.md                         # User-facing quick start
├── PLAY_STORE_SETUP.md               # How to get Play Store API credentials
├── TOTP_OTP_GATE.md                  # How the authenticator-gated publish works
├── builds/                           # Archived APKs (gitignored)
│   ├── robotnerd/
│   ├── growbuild/
│   ├── usemorewords/
│   └── vkb/
└── robotnerd-apk-server.service      # systemd unit
```

## Registered projects

| Slug | Display Name | Namespace | Color | Project Root |
|---|---|---|---|---|
| `robotnerd` | RobotNerd | `com.ntrpt.robotnerd` | `#7c4dff` | `~/Documents/robot_nerd/chatbot-app` |
| `growbuild` | Grow & Build | `com.ntrpt.growandbuild` | `#4caf50` | `~/Documents/growandbuild` |
| `usemorewords` | Use More Words | `com.ntrpt.usemorewords` | `#2C5F5D` | `~/Documents/usemorewords/android` |
| `vkb` | VKB | `ntrpt.vkb` | `#FF6B35` | `~/Documents/VKB` |

## How a project is registered (two places)

### 1. `serve.py` — `PROJECTS` list

```python
PROJECTS = [
    ("robotnerd", "RobotNerd", "#7c4dff"),
    ("growbuild", "Grow & Build", "#4caf50"),
    ("usemorewords", "Use More Words", "#2C5F5D"),
    ("vkb", "VKB", "#FF6B35"),
]
```

Each entry is `(slug, display_name, hex_color)`. The **slug** is the folder name
under `builds/` and the URL path segment. The color drives the UI accent. Only
projects with an existing `builds/<slug>/` directory show up as tabs.

### 2. `publish.sh` — namespace detection

```bash
case "$NAMESPACE" in
    *growandbuild*) PROJECT="growbuild" ;;
    *robotnerd*)    PROJECT="robotnerd" ;;
    *usemorewords*) PROJECT="usemorewords" ;;
    *vkb*)          PROJECT="vkb" ;;
    *)              PROJECT="$(basename "$PROJECT_ROOT")" ;;
esac
```

`publish.sh` reads the `namespace` line from either `app/build.gradle.kts`
(Kotlin DSL) or `app/build.gradle` (Groovy), then maps it to a project slug.
The fallback uses the directory basename.

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
./publish.sh --project-root /home/interrupt/Documents/VKB

# Named project
./publish.sh --project growbuild

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
    --namespace com.example.myapp \
    --project-root /home/interrupt/Documents/myapp
```

This updates both `serve.py` and `publish.sh` and creates `builds/myapp/`.
Idempotent — safe to re-run. Nothing needs to change in the target Android
project itself.

---

## Play Store Publishing Feature (planned)

The server is being extended to publish apps to the **Google Play Store** via the
**Google Play Developer API** (a.k.a. Android Publisher API). This is a
fundamentally different pipeline from the debug-APK sideloading above.

### How it works

Google provides a fully scriptable REST API. The flow for each publish:

1. **Open an "edit"** for a package name
2. **Upload** an `.aab` (Android App Bundle — not a debug APK)
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
confusion, compromised upstream packages) are constant but spike during
conferences like DEFCON. We don't ban packages, but we follow two hard rules
before adding any dependency:

#### Rule 1: Pin versions — never suck in "latest"

Every dependency must be **pinned to a specific version** in a lockfile
(`requirements.txt` with `==`, a `requirements.lock`, or equivalent). Never
use bare `package-name` (which resolves to whatever the latest version is at
install time) or `>=` ranges without an upper bound.

**Why:** A pinned version is a fixed target — it was reviewed when we added
it. An unpinned dependency silently pulls in whatever a maintainer (or
attacker who compromised their account) pushes next. If a package we depend on
gets backdoored in a new version, pinning means we don't get the bad version
until we explicitly choose to upgrade.

**How to pin:**

```bash
# Lock the full transitive tree so sub-dependencies are also frozen:
pip freeze > requirements.lock
```

Commit `requirements.lock` to the repo. Re-generate it deliberately (after
reviewing what changed), never automatically.

Install from the lockfile (never re-resolve): `pip install -r requirements.lock`

#### Rule 2: Check before installing

Before adding any new dependency (or upgrading a pinned one), check it against
the known-compromise databases. This takes 30 seconds:

```bash
# Check GitHub Security Advisories for a specific package:
curl -s 'https://api.github.com/advisories?ecosystem=pip&severity=critical&sort=published&direction=desc&per_page=20' \
    | python3 -c "import sys,json; [print(a['published_at'][:10], a.get('source_code_location','').split('/')[-1] or a['ghsa_id'], a['summary'][:70]) for a in json.load(sys.stdin)]"

# Same for npm:
curl -s 'https://api.github.com/advisories?ecosystem=npm&severity=critical&sort=published&direction=desc&per_page=20' \
    | python3 -c "import sys,json; [print(a['published_at'][:10], a.get('source_code_location','').split('/')[-1] or a['ghsa_id'], a['summary'][:70]) for a in json.load(sys.stdin)]"
```

Also check **OSV.dev** (`https://osv.dev/list?ecosystem=PyPI`) and the
**PyPI/npm advisory pages** directly. Look for: the package name itself, its
direct dependencies, and its transitive dependencies (the "dependency tree").
The litellm wheel compromise (Jul 2026) is the cautionary example — a
legitimate package pulled in a hijacked dependency that propagated downstream.

#### General approach

Where we can trivially use Python stdlib or already-installed CLI tools
(`openssl`, `curl`), we do — fewer moving parts, nothing to verify. Where a
package genuinely saves work, we use it, but pinned and checked.

Current choices for this feature:

- **TOTP** — Python stdlib (`hmac`, `hashlib`, `base64`, `struct`, `time`).
- **JWT signing** (Play API auth) — `openssl` CLI (v3.5.6, already installed).
- **HTTP** — Python stdlib `urllib.request` + `ssl`.
- **Google API client** — if we decide to use `google-api-python-client`,
  we'll pin the exact version, check its advisories, and review its dependency
  tree before installing.

### Important constraints

- **First upload is always manual.** Google requires the very first version of a
  brand-new app to be uploaded through the Play Console web UI by hand. API
  publishing only works for *subsequent updates* to an already-created listing.
- **You must build AABs, not debug APKs.** `publish.sh` builds
  `:app:assembleDebug`. Play publishing needs `:app:bundleRelease` (signed).
- **Version codes must increase.** Each Play upload needs a higher `versionCode`
  than the last live one. The git-count-based build numbers fit this well.

### Planned file layout (once built)

```
apk-server/
├── play-publish.sh         # Build signed AAB + upload to Play (gated by TOTP)
├── play-enroll.py          # Generate TOTP secret + QR, verify enrollment
├── ~/.config/apk-server/   # Secrets (gitignored, chmod 600)
│   ├── totp-secret          # TOTP shared secret
│   └── play-service-account.json  # Play API service account key
```

### Build order

1. `play-enroll.py` — TOTP enrollment (generates secret, shows QR/otpauth URI)
2. `play-publish.sh` — builds signed release AAB
3. `serve.py` endpoint — `POST /api/<project>/play-publish` with TOTP validation
