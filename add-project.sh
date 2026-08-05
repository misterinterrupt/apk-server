#!/usr/bin/env bash
#
# add-project.sh — Register a new Android project with the APK server.
#
# Updates both serve.py (PROJECTS list) and publish.sh (namespace detection),
# and creates the builds/<slug>/ directory.
#
# Usage:
#   ./add-project.sh \
#       --slug vkb \
#       --name "VKB" \
#       --color "#FF6B35" \
#       --namespace ntrpt.vkb \
#       --project-root /home/interrupt/Documents/VKB
#
# Options:
#   --slug S         Folder name under builds/ and URL path (required)
#   --name N         Display name in the UI (required)
#   --color C        Hex accent color, e.g. "#FF6B35" (required)
#   --namespace NS   Android namespace from build.gradle, e.g. "ntrpt.vkb" (required)
#   --project-root P Path to the Android project root (optional, default: cwd)
#
# Notes:
#   - Idempotent: safe to re-run. Updates color/name if slug already exists.
#   - Requires Python 3 (for editing serve.py).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVE_PY="$SCRIPT_DIR/serve.py"
PUBLISH_SH="$SCRIPT_DIR/publish.sh"
BUILDS_DIR="$SCRIPT_DIR/builds"

# --- Defaults ---
SLUG=""
NAME=""
COLOR=""
NAMESPACE=""
PROJECT_ROOT="$(pwd)"

# --- Parse args ---
while [ $# -gt 0 ]; do
  case "$1" in
    --slug)         SLUG="$2"; shift 2 ;;
    --name)         NAME="$2"; shift 2 ;;
    --color)        COLOR="$2"; shift 2 ;;
    --namespace)    NAMESPACE="$2"; shift 2 ;;
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
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

# Confirm the namespace exists in the project's build.gradle file(s).
NAMESPACE_FOUND=false
for gradle_file in "$PROJECT_ROOT/app/build.gradle.kts" "$PROJECT_ROOT/app/build.gradle"; do
  if [ -f "$gradle_file" ] && grep -qE "namespace.*$NAMESPACE" "$gradle_file"; then
    NAMESPACE_FOUND=true
    break
  fi
done
if [ "$NAMESPACE_FOUND" = "false" ]; then
  echo "Warning: namespace '$NAMESPACE' not found in build.gradle files under $PROJECT_ROOT/app/" >&2
  echo "         (continuing anyway — make sure it's correct)" >&2
fi

# ============================================================
# 1. Update serve.py — add entry to PROJECTS list
# ============================================================
echo "Updating serve.py ..."
python3 - "$SERVE_PY" "$SLUG" "$NAME" "$COLOR" <<'PYEOF'
import sys, re

serve_py, slug, name, color = sys.argv[1:5]

with open(serve_py) as f:
    content = f.read()

# Match the PROJECTS = [ ... ] block
pattern = r'(PROJECTS\s*=\s*\[\n)(.*?)(\n\])'
m = re.search(pattern, content, re.DOTALL)
if not m:
    sys.exit("Error: could not find PROJECTS list in serve.py")

head, body, tail = m.group(1), m.group(2), m.group(3)

# Build the new entry line
new_entry = f'    ("{slug}", "{name}", "{color}"),'

# Check if slug already exists
lines = body.rstrip().split("\n")
existing = [l for l in lines if f'"{slug}"' in l]
if existing:
    # Replace the existing line
    updated_lines = [new_entry if f'"{slug}"' in l else l for l in lines]
    body = "\n".join(updated_lines)
    print(f"  Updated existing entry for '{slug}'")
else:
    # Append
    if body.strip():
        body = body.rstrip() + "\n" + new_entry
    else:
        body = new_entry
    print(f"  Added new entry for '{slug}'")

content = content[:m.start()] + head + body + tail + content[m.end():]

with open(serve_py, "w") as f:
    f.write(content)
PYEOF

# ============================================================
# 2. Update publish.sh — add namespace → slug mapping
# ============================================================
echo "Updating publish.sh ..."
python3 - "$PUBLISH_SH" "$SLUG" "$NAMESPACE" <<'PYEOF'
import sys, re

publish_sh, slug, namespace = sys.argv[1:4]

with open(publish_sh) as f:
    content = f.read()

# Build the new case line, indented to match existing entries.
new_case = f'    *{namespace}*)  PROJECT="{slug}" ;;'

# Check if this namespace pattern already has a case entry
if re.search(rf'\*{re.escape(namespace)}\*\)\s+PROJECT=', content):
    print(f"  Namespace mapping for '{namespace}' already exists — skipping")
else:
    # Find the line: *)  PROJECT="$(basename "$PROJECT_ROOT")" ;;
    # and insert our new case just before it.
    fallback_pattern = r'(\s*\*\)\s+PROJECT="\$\(basename "\$PROJECT_ROOT"\)"\s*;;)'
    if re.search(fallback_pattern, content):
        content = re.sub(
            fallback_pattern,
            f'\n{new_case}\\1',
            content,
            count=1,
        )
        print(f"  Added namespace mapping: {namespace} → {slug}")
    else:
        print("  Warning: could not find fallback case line in publish.sh")
        print("  You'll need to add this line manually inside the case block:")
        print(f"    {new_case}")

with open(publish_sh, "w") as f:
    f.write(content)
PYEOF

# ============================================================
# 3. Create builds/<slug>/ directory
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
echo "     ./publish.sh --project-root \"$PROJECT_ROOT\""
echo ""
echo "  2. Start the server (if not running):"
echo "     ./serve.py"
echo ""
echo "  3. The '$NAME' tab appears once builds/$SLUG/ has an APK."
