#!/usr/bin/env bash
#
# Build the RobotNerd debug APK and archive it for the APK server.
#
# The archive lives in apk-server/builds/ with a unique name per build:
#   robotnerd-{build}-{commit}[-dirty].apk
#
# Usage:
#   ./apk-server/publish.sh           # build + archive (skips if clean & exists)
#   ./apk-server/publish.sh --force   # rebuild even if already archived
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILDS_DIR="$SCRIPT_DIR/builds"

cd "$PROJECT_ROOT"

# --- Git metadata ---
BUILD=$(git rev-list --count HEAD)
COMMIT=$(git rev-parse --short HEAD)
if [ -n "$(git status --porcelain)" ]; then
  SUFFIX="-dirty"
else
  SUFFIX=""
fi

FILENAME="robotnerd-${BUILD}-${COMMIT}${SUFFIX}.apk"
DEST="$BUILDS_DIR/$FILENAME"

# --- Skip if already published (clean builds only — dirty always rebuilds) ---
if [ -f "$DEST" ] && [ -z "$SUFFIX" ] && [ "${1:-}" != "--force" ]; then
  echo "Already published: $FILENAME"
  echo "Use --force to rebuild."
  exit 0
fi

# --- Build ---
export ANDROID_HOME="${ANDROID_HOME:-$(pwd)/android-sdk}"
echo "Building debug APK..."
./gradlew :app:assembleDebug

# --- Archive ---
mkdir -p "$BUILDS_DIR"
cp app/build/outputs/apk/debug/app-debug.apk "$DEST"

SIZE=$(du -h "$DEST" | cut -f1)
TOTAL=$(find "$BUILDS_DIR" -name '*.apk' | wc -l)

echo ""
echo "Published: $FILENAME ($SIZE)"
echo "  Archive: $BUILDS_DIR ($TOTAL build(s))"
echo ""
echo "  If the server is running, the new build appears instantly."
echo "  Start it with: ./apk-server/serve.py"
