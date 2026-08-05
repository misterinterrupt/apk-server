#!/usr/bin/env python3
"""
TOTP (RFC 6238) implementation using only Python standard library.

No external packages. Uses hmac, hashlib, base64, struct, time, os, json.
This is the same algorithm your authenticator app (Google Authenticator,
Authy, Aegis, etc.) uses.

Can be imported as a module or run directly for quick testing:
    python3 totp.py                  # generate a code from the enrolled secret
    python3 totp.py --verify 123456  # verify a code
"""

import hmac
import hashlib
import base64
import struct
import time
import os
import json
from pathlib import Path

STEP = 30       # seconds per code
DIGITS = 6      # number of digits in the code
WINDOW = 1      # ±window steps for clock-drift tolerance

CONFIG_DIR = Path.home() / ".config" / "apk-server"
SECRET_FILE = CONFIG_DIR / "totp-secret"
REPLAY_FILE = CONFIG_DIR / "totp-replay.json"

REPLAY_TTL = 120  # seconds before a used code is forgotten


def generate_secret():
    """Generate a random 160-bit TOTP secret, Base32-encoded (32 chars)."""
    raw = os.urandom(20)  # 160 bits — RFC 4226 recommended key length
    return base64.b32encode(raw).decode("ascii")


def compute(secret, timestamp=None, step=STEP, digits=DIGITS):
    """Compute the TOTP code for the given Base32 secret and time.

    Implements HOTP (RFC 4226) with a time-based counter (RFC 6238).
    """
    if timestamp is None:
        timestamp = time.time()
    counter = int(timestamp) // step
    key = base64.b32decode(secret, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10 ** digits)).zfill(digits)


def verify(secret, user_code, step=STEP, digits=DIGITS, window=WINDOW):
    """Verify a user-provided code with ±window tolerance.

    Uses hmac.compare_digest for constant-time comparison (timing-attack safe).
    """
    now = time.time()
    code = str(user_code).strip()
    for offset in range(-window, window + 1):
        expected = compute(secret, now + offset * step, step, digits)
        if hmac.compare_digest(expected, code):
            return True
    return False


def otpauth_uri(secret, account="play-publish", issuer="apk-server"):
    """Build an otpauth:// URI for QR code generation or manual entry."""
    label = f"{issuer}:{account}"
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret}"
        f"&issuer={issuer}"
        f"&digits={DIGITS}"
        f"&period={STEP}"
    )


def save_secret(secret, path=None):
    """Write the secret to a file with restricted permissions."""
    if path is None:
        path = SECRET_FILE
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secret.strip() + "\n")
    os.chmod(path, 0o600)


def load_secret(path=None):
    """Read the secret from a file. Raises FileNotFoundError if not enrolled."""
    if path is None:
        path = SECRET_FILE
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"TOTP secret not found at {path}. Run play-enroll.py first."
        )
    return path.read_text().strip()


def check_and_record_replay(secret, user_code, path=None):
    """Verify the TOTP code AND prevent replay.

    Returns True if the code is valid and has not been used recently.
    On success, records the code as used so it can't authorize a second action.

    This is the function to call at the gate — it atomically checks validity
    and freshness in one step.
    """
    if not verify(secret, user_code):
        return False

    code = str(user_code).strip()
    now = time.time()

    if path is None:
        path = REPLAY_FILE
    path = Path(path)

    # Load previously-used codes
    used = {}
    if path.exists():
        try:
            used = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            used = {}

    # Expire old entries
    used = {k: v for k, v in used.items() if now - v < REPLAY_TTL}

    # Reject if this exact code was already used within the window
    if code in used:
        return False

    # Record this code as used
    used[code] = now
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(used))
    os.chmod(path, 0o600)

    return True


# --- CLI for quick testing ---

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--verify":
        if len(sys.argv) < 3:
            print("Usage: totp.py --verify <code>", file=sys.stderr)
            sys.exit(2)
        try:
            secret = load_secret()
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        if verify(secret, sys.argv[2]):
            print("✓ Valid")
            sys.exit(0)
        else:
            print("✗ Invalid")
            sys.exit(1)
    else:
        try:
            secret = load_secret()
            print(f"Current code: {compute(secret)}")
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
