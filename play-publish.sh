#!/usr/bin/env bash
#
# play-publish.sh — Build a signed release AAB and publish it to the Play Store.
#
# Flow: build AAB → prompt for TOTP → validate TOTP → upload to Play → commit
#
# Requires:
#   - Service account key at ~/.config/apk-server/play-service-account.json
#   - Release keystore at ~/.config/apk-server/release-keystore.jks
#   - TOTP enrollment (run play-enroll.py first)
#   - The app must already exist in Play Console (first upload is manual —
#     see PLAY_STORE_SETUP.md Part 4)
#
# Usage:
#   ./play-publish.sh [options]
#
# Options:
#   --project <slug>         Project slug (robotnerd, growbuild, vkb, ...)
#   --project-root <path>    Path to the Android project root (default: cwd)
#   --track <track>          Play track: internal, alpha, beta, production
#                            (default: internal)
#   --notes <text>           Release notes (default: "Build <version>")
#   --force                  Rebuild even if AAB already exists
#   --dry-run                Build and validate TOTP, but don't upload to Play
#   --help                   Show this help
#
# Environment:
#   APK_SERVER_CONFIG_DIR    Override the secrets directory
#                            (default: ~/.config/apk-server)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILDS_DIR="$SCRIPT_DIR/builds"
CONFIG_DIR="${APK_SERVER_CONFIG_DIR:-$HOME/.config/apk-server}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

# --- Defaults ---
PROJECT=""
PROJECT_ROOT=""
TRACK="internal"
NOTES=""
FORCE=false
DRY_RUN=false

# --- Parse args ---
while [ $# -gt 0 ]; do
  case "$1" in
    --project)       PROJECT="$2"; shift 2 ;;
    --project-root)  PROJECT_ROOT="$2"; shift 2 ;;
    --track)         TRACK="$2"; shift 2 ;;
    --notes)         NOTES="$2"; shift 2 ;;
    --force)         FORCE=true; shift ;;
    --dry-run)       DRY_RUN=true; shift ;;
    --help|-h)
      sed -n '2,/^# Environment:/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}" >&2
      exit 1
      ;;
  esac
done

# --- Validate track ---
case "$TRACK" in
  internal|alpha|beta|production) ;;
  *)
    echo -e "${RED}Error: --track must be one of: internal, alpha, beta, production${NC}" >&2
    exit 1
    ;;
esac

# --- Determine project root ---
if [ -z "$PROJECT_ROOT" ]; then
  PROJECT_ROOT="$(pwd)"
fi

if [ ! -d "$PROJECT_ROOT/app" ]; then
  echo -e "${RED}Error: $PROJECT_ROOT does not look like an Android project (no app/ dir)${NC}" >&2
  exit 1
fi

# --- Auto-detect project from namespace ---
if [ -z "$PROJECT" ]; then
  NAMESPACE=$(grep -E "^[[:space:]]*namespace" "$PROJECT_ROOT/app/build.gradle.kts" 2>/dev/null \
    | head -1 | sed 's/.*["'"'"']\(.*\)["'"'"'].*/\1/' || true)
  if [ -z "$NAMESPACE" ]; then
    NAMESPACE=$(grep -E "^[[:space:]]*namespace" "$PROJECT_ROOT/app/build.gradle" 2>/dev/null \
      | head -1 | sed 's/.*["'"'"']\(.*\)["'"'"'].*/\1/' || true)
  fi
  case "$NAMESPACE" in
    *growandbuild*) PROJECT="growbuild" ;;
    *robotnerd*)    PROJECT="robotnerd" ;;
    *usemorewords*) PROJECT="usemorewords" ;;
    *vkb*)          PROJECT="vkb" ;;
    *)
      echo -e "${RED}Error: Could not auto-detect project from namespace '$NAMESPACE'${NC}" >&2
      echo -e "  Specify with --project <slug>" >&2
      exit 1
      ;;
  esac
fi

# --- Git metadata ---
cd "$PROJECT_ROOT"
BUILD_NUM=$(git rev-list --count HEAD 2>/dev/null || echo "0")
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "nogit")

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo -e "${YELLOW}⚠ Warning: Working tree has uncommitted changes.${NC}"
  echo "  This will be a dirty build. Consider committing first."
  echo ""
fi

# --- Check prerequisites ---
echo -e "${BOLD}Play Store Publish${NC}"
echo -e "  Project:  $PROJECT"
echo -e "  Root:     $PROJECT_ROOT"
echo -e "  Track:    $TRACK"
echo -e "  Build:    #$BUILD_NUM ($COMMIT)"
echo ""

KEY_FILE="$CONFIG_DIR/play-service-account.json"
SIGNING_ENV="$CONFIG_DIR/signing.env"
TOTP_SECRET="$CONFIG_DIR/totp-secret"

errs=0
if [ ! -f "$KEY_FILE" ]; then
  echo -e "${RED}✗ Missing: $KEY_FILE${NC} (see PLAY_STORE_SETUP.md)" >&2
  errs=$((errs+1))
fi
if [ ! -f "$SIGNING_ENV" ]; then
  echo -e "${RED}✗ Missing: $SIGNING_ENV${NC} (see PLAY_STORE_SETUP.md)" >&2
  errs=$((errs+1))
fi
if [ ! -f "$TOTP_SECRET" ]; then
  echo -e "${RED}✗ Missing: $TOTP_SECRET${NC} (run play-enroll.py first)" >&2
  errs=$((errs+1))
fi
if [ "$errs" -gt 0 ]; then
  exit 1
fi

# --- Step 1: Build the signed AAB ---
AAB_DIR="$PROJECT_ROOT/app/build/outputs/bundle/release"
AAB_PATH="$AAB_DIR/app-release.aab"
PROJECT_DIR="$BUILDS_DIR/$PROJECT"

mkdir -p "$PROJECT_DIR"

NEEDS_BUILD=true
if [ -f "$AAB_PATH" ] && [ "$FORCE" = "false" ]; then
  echo -e "Found existing AAB: $AAB_PATH"
  read -r -p "Rebuild? (y/N) " REBUILD
  if [ "$REBUILD" = "y" ] || [ "$REBUILD" = "Y" ]; then
    NEEDS_BUILD=true
  else
    NEEDS_BUILD=false
  fi
fi

if [ "$NEEDS_BUILD" = "true" ]; then
  echo ""
  echo -e "${BOLD}Step 1: Building signed release AAB...${NC}"

  # Source signing credentials
  set -a
  # shellcheck disable=SC1090
  source "$SIGNING_ENV"
  set +a

  # Check that Gradle can find the keystore
  if [ -z "${KEYSTORE_PATH:-}" ] || [ -z "${KEYSTORE_PASSWORD:-}" ] || \
     [ -z "${KEY_ALIAS:-}" ] || [ -z "${KEY_PASSWORD:-}" ]; then
    echo -e "${RED}Error: signing.env must define KEYSTORE_PATH, KEYSTORE_PASSWORD,${NC}" >&2
    echo -e "${RED}       KEY_ALIAS, and KEY_PASSWORD${NC}" >&2
    exit 1
  fi

  # Pass signing config to Gradle via properties
  export ANDROID_HOME="${ANDROID_HOME:-$PROJECT_ROOT/android-sdk}"

  "$PROJECT_ROOT/gradlew" -p "$PROJECT_ROOT" :app:bundleRelease \
    -Pandroid.injected.signing.store.file="$KEYSTORE_PATH" \
    -Pandroid.injected.signing.store.password="$KEYSTORE_PASSWORD" \
    -Pandroid.injected.signing.key.alias="$KEY_ALIAS" \
    -Pandroid.injected.signing.key.password="$KEY_PASSWORD"

  if [ ! -f "$AAB_PATH" ]; then
    echo -e "${RED}Error: Build succeeded but AAB not found at $AAB_PATH${NC}" >&2
    echo "  Check that release signing is configured in your app/build.gradle" >&2
    exit 1
  fi
fi

AAB_SIZE=$(du -h "$AAB_PATH" | cut -f1)
echo -e "${GREEN}✓ AAB built: $AAB_PATH ($AAB_SIZE)${NC}"
echo ""

# --- Step 2: Archive a copy of the AAB ---
AAB_ARCHIVE="$PROJECT_DIR/${PROJECT}-${BUILD_NUM}-${COMMIT}.aab"
cp "$AAB_PATH" "$AAB_ARCHIVE"
echo -e "Archived: $AAB_ARCHIVE"
echo ""

# --- Step 3: TOTP gate ---
echo -e "${BOLD}Step 2: TOTP verification${NC}"
echo -e "Open your authenticator app and enter the current 6-digit code."
echo ""

# Prompt for TOTP code (hidden input for security)
while true; do
  read -r -s -p "TOTP code: " TOTP_CODE
  echo ""
  if [ -z "$TOTP_CODE" ]; then
    echo -e "${RED}Error: No code entered. Aborting.${NC}" >&2
    exit 1
  fi

  # Verify using the replay-aware check
  if python3 "$SCRIPT_DIR/totp.py" --verify "$TOTP_CODE" 2>/dev/null; then
    echo -e "${GREEN}✓ TOTP verified${NC}"
    break
  else
    echo -e "${YELLOW}Invalid code. Try again (or Ctrl+C to abort).${NC}"
  fi
done
echo ""

# --- Step 4: Play API upload ---
if [ "$DRY_RUN" = "true" ]; then
  echo -e "${YELLOW}${BOLD}DRY RUN — skipping Play upload${NC}"
  echo "  AAB:    $AAB_PATH"
  echo "  Package: $NAMESPACE"
  echo "  Track:   $TRACK"
  echo ""
  echo -e "${GREEN}✓ Dry run complete. Everything works up to the upload step.${NC}"
  exit 0
fi

echo -e "${BOLD}Step 3: Publishing to Play Store...${NC}"

# Determine the release notes
if [ -z "$NOTES" ]; then
  NOTES="Build $BUILD_NUM ($COMMIT)"
fi

# Call the Python publisher
PUBLISH_OUTPUT=$(python3 "$SCRIPT_DIR/playapi.py" \
  --key-file "$KEY_FILE" \
  --package "$NAMESPACE" \
  --aab "$AAB_PATH" \
  --track "$TRACK" \
  --notes "$NOTES" \
  --totp-code "$TOTP_CODE" 2>&1) || {
    echo -e "${RED}Publish failed:${NC}" >&2
    echo "$PUBLISH_OUTPUT" >&2
    # Clean up archived AAB on failure
    rm -f "$AAB_ARCHIVE"
    exit 1
  }

echo -e "${GREEN}✓ Published!${NC}"
echo ""
echo "$PUBLISH_OUTPUT"
echo ""
echo -e "  Track:       $TRACK"
echo -e "  Package:     $NAMESPACE"
echo -e "  Archived:    $AAB_ARCHIVE"
echo ""
echo -e "  Check Play Console: https://play.google.com/console/u/0/developers"
