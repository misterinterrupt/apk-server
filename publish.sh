#!/usr/bin/env bash
#
# Build a debug APK and archive it for the APK server.
#
# Builds are organized into project subfolders under builds/:
#   builds/<slug>/<slug>-{build}-{commit}[-dirty].apk
#
# Usage:
#   ./publish.sh                                          # auto-detect
#   ./publish.sh --project growbuild                      # named project
#   ./publish.sh --project-root /path/to/android-project  # explicit app dir
#   ./publish.sh --force                                  # rebuild even if archived
#
# When --project-root is not given, the script assumes it is being run from
# inside the Android project directory (the old behaviour).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILDS_DIR="$SCRIPT_DIR/builds"

# --- Parse args ---
PROJECT=""
PROJECT_ROOT=""
FORCE=false
shift_next=""

for arg in "$@"; do
  case $arg in
    --force) FORCE=true ;;
    --project=*)      PROJECT="${arg#*=}" ;;
    --project)        shift_next="project" ;;
    --project-root=*) PROJECT_ROOT="${arg#*=}" ;;
    --project-root)   shift_next="project-root" ;;
    *)
      if [ -n "$shift_next" ]; then
        case "$shift_next" in
          project)      PROJECT="$arg" ;;
          project-root) PROJECT_ROOT="$arg" ;;
        esac
        shift_next=""
      fi
      ;;
  esac
done

# --- Determine the Android project root ---
# Default to the current working directory if not specified.
if [ -z "$PROJECT_ROOT" ]; then
  PROJECT_ROOT="$(pwd)"
fi
cd "$PROJECT_ROOT"

# --- Auto-detect project from the app namespace if not specified ---
if [ -z "$PROJECT" ]; then
  # Check Kotlin DSL (.kts) first, then fall back to Groovy (.gradle).
  NAMESPACE=$(grep -E "^[[:space:]]*namespace" app/build.gradle.kts 2>/dev/null | head -1 | sed 's/.*["'\'']\(.*\)["'\''].*/\1/' || true)
  if [ -z "$NAMESPACE" ]; then
    NAMESPACE=$(grep -E "^[[:space:]]*namespace" app/build.gradle 2>/dev/null | head -1 | sed 's/.*["'\'']\(.*\)["'\''].*/\1/' || true)
  fi
  case "$NAMESPACE" in
    *growandbuild*) PROJECT="growbuild" ;;
    *robotnerd*)    PROJECT="robotnerd" ;;
    *usemorewords*) PROJECT="usemorewords" ;;
    *vkb*)          PROJECT="vkb" ;;
    *)              PROJECT="$(basename "$PROJECT_ROOT")" ;;
  esac
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

FILENAME="${PROJECT}-${BUILD}-${COMMIT}${SUFFIX}.apk"
DEST="$PROJECT_DIR/$FILENAME"

# --- Skip if already published (clean builds only — dirty always rebuilds) ---
if [ -f "$DEST" ] && [ -z "$SUFFIX" ] && [ "$FORCE" = "false" ]; then
  echo "Already published: $FILENAME"
  echo "Use --force to rebuild."
  exit 0
fi

# --- Build ---
export ANDROID_HOME="${ANDROID_HOME:-$PROJECT_ROOT/android-sdk}"
echo "Building debug APK (project: $PROJECT, root: $PROJECT_ROOT)..."
"$PROJECT_ROOT/gradlew" -p "$PROJECT_ROOT" :app:assembleDebug

# --- Archive ---
cp "$PROJECT_ROOT/app/build/outputs/apk/debug/app-debug.apk" "$DEST"

SIZE=$(du -h "$DEST" | cut -f1)
TOTAL=$(find "$PROJECT_DIR" -name '*.apk' | wc -l)

echo ""
echo "Published: $FILENAME ($SIZE)"
echo "  Archive: $PROJECT_DIR ($TOTAL build(s))"
echo ""
echo "  If the server is running, the new build appears instantly."
echo "  Start it with: ./serve.py"
