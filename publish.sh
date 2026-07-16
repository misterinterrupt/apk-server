#!/usr/bin/env bash
#
# Build a debug APK and archive it for the APK server.
#
# Builds are organized into project subfolders under apk-server/builds/:
#   builds/<slug>/<slug>-{build}-{commit}[-dirty].apk
#
# Usage:
#   ./publish.sh                          # build + archive (robotnerd)
#   ./publish.sh --project growbuild      # build + archive (growbuild)
#   ./publish.sh --force                  # rebuild even if already archived
#
# The script auto-detects the project name from the gradle namespace if
# --project is not specified.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILDS_DIR="$SCRIPT_DIR/builds"

# --- Parse args ---
PROJECT=""
FORCE=false
for arg in "$@"; do
  case $arg in
    --force) FORCE=true ;;
    --project=*) PROJECT="${arg#*=}" ;;
    --project) shift_next=true ;;
    *)
      if [ "${shift_next:-}" = "true" ]; then
        PROJECT="$arg"
        shift_next=false
      fi
      ;;
  esac
done

# --- Auto-detect project from the app namespace if not specified ---
if [ -z "$PROJECT" ]; then
  NAMESPACE=$(grep -E "^[[:space:]]*namespace" app/build.gradle.kts 2>/dev/null | head -1 | sed 's/.*"\(.*\)".*/\1/' || true)
  case "$NAMESPACE" in
    *growandbuild*) PROJECT="growbuild" ;;
    *robotnerd*)    PROJECT="robotnerd" ;;
    *)              PROJECT="$(basename "$(cd "$SCRIPT_DIR/.." && pwd)")" ;;
  esac
fi

PROJECT_DIR="$BUILDS_DIR/$PROJECT"
mkdir -p "$PROJECT_DIR"

# We need the git root — could be this dir or a parent.
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

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
export ANDROID_HOME="${ANDROID_HOME:-$(pwd)/android-sdk}"
echo "Building debug APK (project: $PROJECT)..."
./gradlew :app:assembleDebug

# --- Archive ---
cp app/build/outputs/apk/debug/app-debug.apk "$DEST"

SIZE=$(du -h "$DEST" | cut -f1)
TOTAL=$(find "$PROJECT_DIR" -name '*.apk' | wc -l)

echo ""
echo "Published: $FILENAME ($SIZE)"
echo "  Archive: $PROJECT_DIR ($TOTAL build(s))"
echo ""
echo "  If the server is running, the new build appears instantly."
echo "  Start it with: ./serve.py"
