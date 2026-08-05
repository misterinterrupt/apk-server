# APK Server — Project Guide

A quick-reference for how this repo works and how to add new Android projects.

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
├── serve.py            # HTTP server (stdlib only, Python 3)
├── publish.sh          # Gradle build + archive script
├── add-project.sh      # Add a new Android project to the server
├── PROJECT_GUIDE.md    # This file
├── builds/             # Archived APKs (gitignored)
│   ├── robotnerd/
│   ├── growbuild/
│   ├── usemorewords/
│   └── vkb/
└── robotnerd-apk-server.service   # systemd unit
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
See the script header for all options. Nothing needs to change in the target
Android project itself.
