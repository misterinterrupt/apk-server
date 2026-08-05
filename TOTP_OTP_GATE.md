# TOTP / OTP Authenticator Gate

This document explains the authenticator-app gate that protects Play Store
publishing. Every time you publish to the Play Store, the server requires a
**6-digit code from your authenticator app** (Google Authenticator, Authy,
FreeOTP, Aegis, etc.) before it will upload anything.

## Why this exists

The Play API credential (service account JSON key) lives on your machine so
that publishing can be automated. But "automated" shouldn't mean "anyone who can
reach the server can publish." The TOTP gate adds a **human-in-the-loop** check:

- The credential is present for automation — the server can talk to Google.
- **But** the server won't actually publish until you provide a fresh code from
  your phone.
- The code changes every 30 seconds and can't be guessed or reused.

This means even if someone gets network access to your server (or steals the
service account key off disk), they **cannot publish without the rotating code
from your authenticator app**.

## How it works

TOTP (Time-based One-Time Password, RFC 6238) is the same standard your
authenticator app uses. It works by:

1. **A shared secret** is generated once and stored on the server (never leaves
   the machine).
2. **Your authenticator app** gets the same secret (via a QR code during
   enrollment).
3. **Both sides** combine the secret with the current time to produce the same
   6-digit code, changing every 30 seconds.
4. **The server** checks your submitted code against what it computes. If they
   match (within a small ±30-second tolerance for clock drift), you're approved.

The TOTP algorithm itself is simple enough that we implement it directly in
Python's standard library — no need for `pyotp` or any third-party package.
This is partly out of simplicity (the code is ~15 lines) and partly out of
supply-chain caution: we avoid pulling in packages we don't need to, especially
during DEFCON season when package-ecosystem attacks (typosquatting, malicious
updates, dependency confusion) are common. We're not anti-package — we just
verify before we trust, and use stdlib when it's the easier path anyway.

| What | How | Package? |
|---|---|---|
| TOTP computation | Python stdlib: `hmac`, `hashlib`, `base64`, `struct`, `time` | None needed — stdlib |
| QR code for enrollment | `qrencode` CLI (install once) OR `otpauth://` URI you type/paste manually | Optional system tool |
| Secret generation | Python stdlib: `os.urandom` | None needed — stdlib |
| Secret storage | Plain file, `chmod 600` | None needed |

## Step 1: Enroll (one-time setup)

Enrollment generates the shared secret and puts it into your authenticator app.

### 1A — Generate the secret

Run the enrollment script (once built):

```bash
./play-enroll.py
```

It will:
1. Generate a 160-bit random secret using `os.urandom`.
2. Save it to `~/.config/apk-server/totp-secret` (chmod 600).
3. Display an `otpauth://` URI and (if `qrencode` is installed) a QR code.

### 1B — Add to your authenticator app

**Option A — Scan a QR code** (if `qrencode` is installed):

```bash
sudo apt install qrencode   # one-time, trusted Ubuntu/Debian package
```

Then re-run `./play-enroll.py` and scan the QR with your authenticator app.

**Option B — Manual entry** (no QR code, works anywhere):

The enrollment script prints an `otpauth://` URI like:

```
otpauth://totp/apk-server:play-publish?secret=JBSWY3DPEHPK3PXP&issuer=apk-server&digits=6&period=30
```

Copy the `secret=` value (`JBSWY3DPEHPK3PXP` in the example) and enter it
manually into your authenticator app as a "time-based" key. Most apps have an
"Enter key manually" or "Add account → Enter setup key" option.

### 1C — Verify enrollment

Test that both sides agree:

```bash
./play-enroll.py --verify
```

It will ask for the current 6-digit code from your authenticator. Enter it; it
should say `✓ Verified`. If it fails, check your system clock (TOTP requires
accurate time on both the server and your phone):

```bash
timedatectl status
# "System clock synchronized: yes" should be true
```

## Step 2: Publish (every time)

When you publish to the Play Store, the server requires the code. The flow:

```
You:  ./play-publish.sh --project vkb --track internal
      (script prompts for the code)

You:  opens authenticator app, reads current 6-digit code, types it

Server: validates the code (RFC 6238, ±1 step = ±30 seconds tolerance)
Server: if valid → builds signed AAB → uploads to Play → commits edit
Server: if invalid → 403 Forbidden, nothing is uploaded
```

### The API endpoint (for direct calls)

```
POST /api/<project>/play-publish
Content-Type: application/json

{
    "totp": "123456",
    "track": "internal"
}
```

- **`totp`** — current 6-digit code from your authenticator (required)
- **`track`** — which Play track to publish to: `internal` (default), `alpha`,
  `beta`, or `production`

Response:
- **200** — `{"status": "published", "versionCode": 42, "track": "internal"}`
- **403** — `{"error": "Invalid or expired TOTP code"}` — nothing was uploaded
- **400** — `{"error": "Missing totp field"}`

### Replay protection

Each code is valid for a ~90-second window (the current 30-second step plus the
one before and after, for clock drift). The server additionally tracks the last
successfully used code to prevent replay within the same window — a single code
can only authorize one publish.

## TOTP internals (for the implementer)

The algorithm is straightforward. Here's the complete RFC 6238 implementation in
pure Python stdlib:

```python
import hmac, hashlib, base64, struct, time

def totp(secret_b32, timestamp=None, step=30, digits=6):
    """Generate a TOTP code from a Base32-encoded secret."""
    if timestamp is None:
        timestamp = time.time()
    counter = int(timestamp) // step
    key = base64.b32decode(secret_b32)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset+4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)

def verify(secret_b32, user_code, step=30, digits=6, window=1):
    """Verify a user-provided code with ±window tolerance for clock drift."""
    now = time.time()
    for offset in range(-window, window + 1):
        expected = totp(secret_b32, now + offset * step, step, digits)
        if hmac.compare_digest(expected, str(user_code)):
            return True
    return False
```

Key points:
- **`hmac.compare_digest`** is used for comparison to prevent timing attacks
  (constant-time comparison).
- The secret is Base32-encoded for easy manual entry into authenticator apps.
- The `±window` tolerance allows codes from the previous and next 30-second step
  to account for clock drift between the server and your phone.

## File layout

```
~/.config/apk-server/
├── totp-secret               # Base32-encoded shared secret (chmod 600)
├── play-service-account.json # Play API key (chmod 600)
├── release-keystore.jks      # AAB signing key (chmod 600)
└── signing.env               # Keystore passwords (chmod 600)
```

## Security model

| Threat | Mitigated? | How |
|---|---|---|
| Service account key stolen from disk | ✅ | Attacker can't publish without the TOTP code |
| Network attacker hits the publish endpoint | ✅ | No valid TOTP code = 403, nothing uploaded |
| Replay of a captured code | ✅ | Codes expire in ~30 seconds; used codes are tracked |
| Clock drift between phone and server | ✅ | ±1 step (±30s) tolerance |
| Timing attack on code comparison | ✅ | `hmac.compare_digest` (constant-time) |
| Supply-chain compromise (malicious package) | ✅ | Minimal dependencies; TOTP uses stdlib, JWT uses openssl CLI. Any third-party package is checked against current attacks before use |

## Troubleshooting

**"Code always rejected"**
- Check system clock sync: `timedatectl status` — "System clock synchronized"
  must be `yes`.
- Check phone clock — authenticator apps rely on the phone's network time.
- Re-run enrollment: `./play-enroll.py` and re-scan/re-enter the secret.

**"QR code doesn't appear"**
- Install `qrencode`: `sudo apt install qrencode`
- Or use manual entry: copy the `secret=` value from the printed `otpauth://` URI.

**"Lost phone / authenticator app reset"**
- Re-enroll from scratch: delete `~/.config/apk-server/totp-secret`, run
  `./play-enroll.py` again, add the new secret to your authenticator app.
- Until re-enrollment completes, no publishes can happen (by design).
