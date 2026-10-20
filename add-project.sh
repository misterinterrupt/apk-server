#!/usr/bin/env bash
#
# add-project.sh — Register a new Android project with the APK server.
#
# Updates projects.json and creates the builds/<slug>/ directory.
#
# Usage:
#   ./add-project.sh \
#       --slug myapp \
#       --name "My App" \
#       --color "#00BCD4" \
#       --namespace com.example.myapp
#
# Options:
#   --slug S         Folder name under builds/ and URL path (required)
#   --name N         Display name in the UI (required)
#   --color C        Hex accent color, e.g. "#FF6B35" (required)
#   --namespace NS   Android namespace from build.gradle, e.g. "com.example.app" (required)
#
# Notes:
#   - Idempotent: safe to re-run. Updates color/name if slug already exists.
#   - Requires Python 3 (for editing projects.json).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/projects.json"
BUILDS_DIR="$SCRIPT_DIR/builds"

# --- Defaults ---
SLUG=""
NAME=""
COLOR=""
NAMESPACE=""

# --- Parse args ---
while [ $# -gt 0 ]; do
  case "$1" in
    --slug)      SLUG="$2"; shift 2 ;;
    --name)      NAME="$2"; shift 2 ;;
    --color)     COLOR="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# --- Validate ---
err() { echo "Error: $1" >&2; exit 1; }

[ -n "$SLUG" ]      || err "--slug is required"
[ -n "$NAME" ]      || err "--name is required"
[ -n "$COLOR" ]     || err "--color is required"
[ -n "$NAMESPACE" ] || err "--namespace is required"

echo "$COLOR" | grep -qE '^#[0-9a-fA-F]{6}$' || err "--color must be a 6-digit hex like #FF6B35"

# ============================================================
# Update projects.json
# ============================================================
echo "Updating projects.json ..."
python3 - "$CONFIG_FILE" "$SLUG" "$NAME" "$COLOR" "$NAMESPACE" <<'PYEOF'
import json, sys

config_file, slug, name, color, namespace = sys.argv[1:6]

# Load existing config or create default
try:
    with open(config_file) as f:
        cfg = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {"projects": []}

projects = cfg.get("projects", [])

# Check if slug already exists
existing = None
for p in projects:
    if p.get("slug") == slug:
        existing = p
        break

new_entry = {
    "slug": slug,
    "name": name,
    "color": color,
    "namespace": namespace,
}

if existing:
    # Update in place
    for i, p in enumerate(projects):
        if p.get("slug") == slug:
            projects[i] = new_entry
            break
    print(f"  Updated existing entry for '{slug}'")
else:
    projects.append(new_entry)
    print(f"  Added new entry for '{slug}'")

cfg["projects"] = projects

with open(config_file, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PYEOF

# ============================================================
# Create builds/<slug>/ directory
# ============================================================
mkdir -p "$BUILDS_DIR/$SLUG"
echo "Created directory: builds/$SLUG"

# ============================================================
# Done
# ============================================================
echo ""
echo "✓ Project '$NAME' registered (slug: $SLUG)"
echo ""
echo "Next steps:"
echo "  1. Publish a build:"
echo "     ./publish.sh --project '$SLUG'"
echo ""
echo "  2. Start the server (if not running):"
echo "     ./serve.py"
echo ""
echo "  3. The '$NAME' tab appears once builds/$SLUG/ has an APK."
