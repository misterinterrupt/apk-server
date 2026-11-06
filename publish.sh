#!/usr/bin/env bash
#
# Build a debug APK and archive it for the APK server.
#
# Builds are organized into project subfolders under builds/:
#   builds/<slug>/<slug>-{versionCode}-{commit}[-dirty].apk
#
# Usage:
#   ./publish.sh                                          # auto-detect
#   ./publish.sh --project <slug>                         # named project
#   ./publish.sh --project-root /path/to/android-project  # explicit app dir
#   ./publish.sh --build <versionCode>                    # explicit code
#   ./publish.sh --force                                  # rebuild even if archived
#
# When --project-root is not given, the script assumes it is being run from
# inside the Android project directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILDS_DIR="$SCRIPT_DIR/builds"
CONFIG_FILE="$SCRIPT_DIR/projects.json"

# --- Parse args ---
PROJECT=""
PROJECT_ROOT=""
FORCE=false
BUILD_ARG=""
shift_next=""

for arg in "$@"; do
  case $arg in
    --force) FORCE=true ;;
    --build=*)        BUILD_ARG="${arg#*=}" ;;
    --build)         shift_next="build" ;;
    --project=*)      PROJECT="${arg#*=}" ;;
    --project)        shift_next="project" ;;
    --project-root=*) PROJECT_ROOT="${arg#*=}" ;;
    --project-root)   shift_next="project-root" ;;
    *)
      if [ -n "$shift_next" ]; then
        case "$shift_next" in
          project)      PROJECT="$arg" ;;
          project-root) PROJECT_ROOT="$arg" ;;
          build)        BUILD_ARG="$arg" ;;
        esac
        shift_next=""
      fi
      ;;
  esac
done

# --- Determine the Android project root ---
if [ -z "$PROJECT_ROOT" ]; then
  PROJECT_ROOT="$(pwd)"
fi
cd "$PROJECT_ROOT"

# --- Auto-detect project from the app namespace if not specified ---
if [ -z "$PROJECT" ]; then
  NAMESPACE=$(grep -E "^[[:space:]]*namespace" app/build.gradle.kts 2>/dev/null | head -1 | sed 's/.*["'"'"']\(.*\)["'"'"'].*/\1/' || true)
  if [ -z "$NAMESPACE" ]; then
    NAMESPACE=$(grep -E "^[[:space:]]*namespace" app/build.gradle 2>/dev/null | head -1 | sed 's/.*["'"'"']\(.*\)["'"'"'].*/\1/' || true)
  fi

  # Look up namespace in projects.json
  if [ -n "$NAMESPACE" ] && [ -f "$CONFIG_FILE" ]; then
    PROJECT=$(python3 -c "
import json, sys
with open('$CONFIG_FILE') as f:
    cfg = json.load(f)
for p in cfg.get('projects', []):
    if p.get('namespace') == '$NAMESPACE':
        print(p['slug'])
        sys.exit(0)
print('')
" 2>/dev/null || true)
  fi

  # Fallback: use directory basename
  if [ -z "$PROJECT" ]; then
    PROJECT="$(basename "$PROJECT_ROOT")"
  fi
fi

PROJECT_DIR="$BUILDS_DIR/$PROJECT"
mkdir -p "$PROJECT_DIR"

# --- Git metadata ---
BUILD=$(git rev-list --count HEAD 2>/dev/null || echo "0")
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "nogit")
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  SUFFIX="-dirty"
else
  SUFFIX=""
fi

# --- Version code ---------------------------------------------------------
# The filename MUST carry the APK's real versionCode — the same integer
# Android's PackageManager compares and the apksync app reads back from
# /api/{project}/builds. If the two disagree (they did on 2026-11-04/05,
# when filenames used commit counts but the APKs carried HEAD timestamps),
# the app's update check compares mismatched numbers: every build looks
# older-than-installed, the update flag never trips, and Android refuses
# the install as a version downgrade.
#
# Priority:
#   1. --build <n>   explicit (the robot_nerd post-commit hook passes the
#                    HEAD timestamp — exactly what gradle baked into the APK)
#   2. aapt          read versionCode out of the freshly built APK
#   3. commit count  last resort (projects still on counter versionCodes)

find_aapt() {
  local candidate
  for candidate in "$ANDROID_HOME"/build-tools/*/aapt \
                   "$PROJECT_ROOT"/android-sdk/build-tools/*/aapt; do
    [ -x "$candidate" ] && { echo "$candidate"; return 0; }
  done
  command -v aapt 2>/dev/null || true
}

apk_version_code() {
  local apk="$1" aapt code
  aapt="$(find_aapt)"
  [ -n "$aapt" ] || return 1
  code="$("$aapt" dump badging "$apk" 2>/dev/null |
    sed -n "s/^package:.*versionCode='\([0-9][0-9]*\)'.*/\1/p")"
  [ -n "$code" ] || return 1
  echo "$code"
}

dest_for() {
  echo "$PROJECT_DIR/${PROJECT}-${1}-${COMMIT}${SUFFIX}.apk"
}

VERSION_CODE="$BUILD_ARG"
[ -n "$VERSION_CODE" ] || VERSION_CODE="$BUILD"
DEST="$(dest_for "$VERSION_CODE")"

# --- Skip if already published (clean builds only — dirty always rebuilds) ---
if [ -f "$DEST" ] && [ -z "$SUFFIX" ] && [ "$FORCE" = "false" ]; then
  echo "Already published: $(basename "$DEST")"
  echo "Use --force to rebuild."
  exit 0
fi

# --- Build ---
export ANDROID_HOME="${ANDROID_HOME:-$PROJECT_ROOT/android-sdk}"
echo "Building debug APK (project: $PROJECT, root: $PROJECT_ROOT)..."
"$PROJECT_ROOT/gradlew" -p "$PROJECT_ROOT" :app:assembleDebug

# --- Archive ---
APK_OUT="$PROJECT_ROOT/app/build/outputs/apk/debug/app-debug.apk"

# Without an explicit --build, trust the APK itself over the commit-count
# guess (the skip-check above may then have used the wrong name — harmless,
# it only skips, never archives).
if [ -z "$BUILD_ARG" ]; then
  REAL_CODE="$(apk_version_code "$APK_OUT" || true)"
  [ -n "$REAL_CODE" ] && VERSION_CODE="$REAL_CODE"
  DEST="$(dest_for "$VERSION_CODE")"
fi

cp "$APK_OUT" "$DEST"
FILENAME="$(basename "$DEST")"

SIZE=$(du -h "$DEST" | cut -f1)
TOTAL=$(find "$PROJECT_DIR" -name '*.apk' | wc -l)

echo ""
echo "Published: $FILENAME ($SIZE)"
echo "  Archive: $PROJECT_DIR ($TOTAL build(s))"
echo ""
echo "  If the server is running, the new build appears instantly."
echo "  Start it with: ./serve.py"
