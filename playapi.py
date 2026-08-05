#!/usr/bin/env python3
"""
playapi.py — Minimal Google Play Developer API client using only stdlib.

Talks to the Play Developer API REST endpoints directly — no google-api-python-client,
no google-auth, no requests. OAuth2 JWT-Bearer flow is done by signing an RS256
JWT with the openssl CLI (already installed). HTTP calls use urllib.request.

Authentication flow:
  1. Build a JWT from the service account JSON key
  2. Sign it with openssl (RS256)
  3. Exchange it for an OAuth2 access token at Google's token endpoint
  4. Use the token in Authorization headers for all API calls

See PLAY_STORE_SETUP.md for how to get the service account JSON key.

Usage as a module:
    import playapi

    client = playapi.Client.from_key_file("/path/to/play-service-account.json")
    client.upload_bundle("com.example.app", "/path/to/app-release.aab")
    client.assign_track("com.example.app", version_code, track="internal")

CLI usage (called by play-publish.sh):
    python3 playapi.py \\
        --key-file ~/.config/apk-server/play-service-account.json \\
        --package com.example.app \\
        --aab app-release.aab \\
        --track internal \\
        --totp-code 123456
"""

import argparse
import base64
import json
import os
import subprocess
import ssl
import sys
import time
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications"

# Play API is slow; give generous timeouts.
HTTP_TIMEOUT = 120
TOKEN_TTL = 3500  # seconds — refresh before the 1-hour expiry


class PlayAPIError(Exception):
    """Raised when the Play API returns an error."""

    def __init__(self, message, status_code=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


# ─── HTTP helpers ──────────────────────────────────────────────────────────

def _http_request(method, url, headers=None, data=None):
    """Execute an HTTP request with urllib, returning (status, headers, body)."""
    req = Request(url, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    ctx = ssl.create_default_context()
    try:
        with urlopen(req, data=data, timeout=HTTP_TIMEOUT, context=ctx) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except HTTPError as e:
        return e.code, dict(e.headers), e.read()


# ─── JWT / OAuth2 ──────────────────────────────────────────────────────────

def _b64(data):
    """Base64url encode without padding (for JWT segments)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_jwt_rs256(payload, private_key_pem):
    """Sign a JWT with RS256 using the openssl CLI.

    We extract the RSA private key from the service-account JSON and sign with
    openssl to avoid the `cryptography` package (supply-chain caution — see
    PROJECT_GUIDE.md → Dependency safety rules).
    """
    header = {"alg": "RS256", "typ": "JWT", "kid": payload.get("kid")}
    header_b64 = _b64(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as kf:
        kf.write(private_key_pem)
        kf.flush()
        key_path = kf.name

    with tempfile.NamedTemporaryFile(delete=False) as sf:
        sf.write(signing_input)
        sf.flush()
        sign_path = sf.name

    out_path = sign_path + ".sig"
    try:
        subprocess.run(
            [
                "openssl", "dgst", "-sha256",
                "-sign", key_path,
                "-out", out_path,
                sign_path,
            ],
            check=True,
            capture_output=True,
        )
        with open(out_path, "rb") as f:
            signature = f.read()
        return f"{signing_input.decode()}.{_b64(signature)}"
    finally:
        for p in (key_path, sign_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def _exchange_jwt_for_token(assertion):
    """Exchange a signed JWT assertion for an OAuth2 access token."""
    data = (
        f"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"
        f"&assertion={assertion}"
    ).encode()
    status, _, body = _http_request(
        "POST", TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data,
    )
    if status != 200:
        raise PlayAPIError(
            f"Token exchange failed (HTTP {status})",
            status_code=status,
            body=body.decode("utf-8", errors="replace"),
        )
    token_data = json.loads(body)
    return token_data["access_token"], int(token_data.get("expires_in", 3600))


# ─── Client ────────────────────────────────────────────────────────────────

class Client:
    def __init__(self, key_data, key_file=None):
        self.key_data = key_data
        self.key_file = key_file
        self._token = None
        self._token_expires = 0

    @classmethod
    def from_key_file(cls, path):
        path = Path(path).expanduser()
        with open(path) as f:
            data = json.load(f)
        return cls(data, key_file=path)

    def _get_token(self):
        """Get a valid access token, refreshing via JWT if expired."""
        now = time.time()
        if self._token and now < self._token_expires:
            return self._token

        now_int = int(now)
        payload = {
            "iss": self.key_data["client_email"],
            "scope": "https://www.googleapis.com/auth/androidpublisher",
            "aud": self.key_data["token_uri"],
            "iat": now_int,
            "exp": now_int + 3600,
            "kid": self.key_data["private_key_id"],
        }
        assertion = _sign_jwt_rs256(payload, self.key_data["private_key"])
        self._token, ttl = _exchange_jwt_for_token(assertion)
        self._token_expires = now + min(ttl, TOKEN_TTL)
        return self._token

    def _api(self, method, path, content_type="application/json", body=None):
        """Make an authenticated API call to the Play Developer API."""
        token = self._get_token()
        url = f"{API_BASE}/{path}"
        data = None
        if body is not None:
            data = body.encode() if isinstance(body, str) else body
        status, headers, resp_body = _http_request(
            method, url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
            },
            data=data,
        )
        if status >= 400:
            raise PlayAPIError(
                f"API call failed: {method} {path} → HTTP {status}",
                status_code=status,
                body=resp_body.decode("utf-8", errors="replace"),
            )
        return _parse_json(resp_body)

    def _upload(self, package_name, edit_id, file_path):
        """Upload an AAB using the resumable upload protocol."""
        token = self._get_token()
        file_path = Path(file_path)
        file_size = file_path.stat().st_size

        # Step 1: Start a resumable upload session
        url = (
            f"{UPLOAD_URL}/{package_name}/edits/{edit_id}/bundles"
            f"?uploadType=resumable&sync=false"
        )
        status, headers, body = _http_request(
            "POST", url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "application/octet-stream",
                "X-Upload-Content-Length": str(file_size),
            },
            data=json.dumps({}).encode(),
        )
        if status not in (200, 201):
            raise PlayAPIError(
                f"Upload session start failed (HTTP {status})",
                status_code=status,
                body=body.decode("utf-8", errors="replace"),
            )
        upload_url = headers.get("Location") or headers.get("location")
        if not upload_url:
            raise PlayAPIError(
                "Upload session start did not return a Location header"
            )

        # Step 2: Upload the file in a single PUT (chunked PUT is also possible
        # but a single PUT works for AABs which are typically < 200 MB)
        with open(file_path, "rb") as f:
            file_data = f.read()

        status, _, resp_body = _http_request(
            "PUT", upload_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Length": str(file_size),
            },
            data=file_data,
        )
        if status >= 400:
            raise PlayAPIError(
                f"AAB upload failed (HTTP {status})",
                status_code=status,
                body=resp_body.decode("utf-8", errors="replace"),
            )
        result = _parse_json(resp_body)
        return result.get("versionCode")

    # ─── High-level API ────────────────────────────────────────────────────

    def create_edit(self, package_name):
        """Open a new edit. Returns the edit_id."""
        result = self._api("POST", f"{package_name}/edits")
        return result["id"]

    def upload_bundle(self, package_name, edit_id, aab_path):
        """Upload an AAB. Returns the version code assigned by Play."""
        return self._upload(package_name, edit_id, aab_path)

    def assign_track(self, package_name, edit_id, version_code, track="internal", release_notes=""):
        """Assign a version code to a track (internal, alpha, beta, production)."""
        valid_tracks = {"internal", "alpha", "beta", "production"}
        if track not in valid_tracks:
            raise ValueError(f"Invalid track '{track}'. Must be one of: {valid_tracks}")

        body = {
            "track": track,
            "releases": [
                {
                    "name": f"Build {version_code}",
                    "versionCodes": [int(version_code)],
                    "status": "completed",
                }
            ],
        }
        if release_notes:
            body["releases"][0]["releaseNotes"] = [
                {"language": "en-US", "text": release_notes}
            ]
        return self._api(
            "PUT", f"{package_name}/edits/{edit_id}/tracks/{track}", body=json.dumps(body)
        )

    def commit_edit(self, package_name, edit_id):
        """Commit the edit — makes the changes live."""
        return self._api("POST", f"{package_name}/edits/{edit_id}:commit")

    def publish(self, package_name, aab_path, track="internal", release_notes=""):
        """Full publish flow: create edit → upload → assign track → commit.

        Returns a dict with the results.
        """
        edit_id = self.create_edit(package_name)
        version_code = self.upload_bundle(package_name, edit_id, aab_path)
        self.assign_track(
            package_name, edit_id, version_code,
            track=track, release_notes=release_notes,
        )
        self.commit_edit(package_name, edit_id)
        return {
            "status": "published",
            "versionCode": version_code,
            "track": track,
            "editId": edit_id,
            "package": package_name,
        }


# ─── Utilities ─────────────────────────────────────────────────────────────

def _parse_json(body):
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body.decode("utf-8", errors="replace")}


def validate_key_file(path):
    """Check that a service-account JSON key has all required fields."""
    path = Path(path).expanduser()
    with open(path) as f:
        data = json.load(f)
    required = ["type", "project_id", "private_key_id", "private_key",
                "client_email", "token_uri"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"Service account key missing fields: {missing}")
    if data["type"] != "service_account":
        names = {
            "project": data.get("project_id"),
            "email": data.get("client_email"),
        }
        raise ValueError(f"Key type is '{data['type']}', expected 'service_account'. {names}")
    return data


# ─── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Publish a signed AAB to the Google Play Store (TOTP-gated)."
    )
    parser.add_argument("--key-file", required=True,
                        help="Path to the service account JSON key file")
    parser.add_argument("--package", required=True,
                        help="Android package name (e.g. com.example.app)")
    parser.add_argument("--aab", required=True,
                        help="Path to the signed release AAB file")
    parser.add_argument("--track", default="internal",
                        help="Play track: internal, alpha, beta, production")
    parser.add_argument("--notes", default="",
                        help="Release notes text")
    parser.add_argument("--totp-code", required=True,
                        help="Current TOTP code from your authenticator app")
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate credentials and TOTP, but don't upload")
    args = parser.parse_args()

    # ─── TOTP gate ────────────────────────────────────────────────────────
    # The TOTP check with replay protection happens here — the very first
    # thing we do before touching any Google API.
    import totp

    try:
        secret = totp.load_secret()
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if not totp.check_and_record_replay(secret, args.totp_code):
        print("ERROR: Invalid or expired TOTP code.", file=sys.stderr)
        print("       Get a fresh code from your authenticator app and try again.",
              file=sys.stderr)
        sys.exit(403)

    print("✓ TOTP verified")

    # ─── Validate the key file ────────────────────────────────────────────
    try:
        validate_key_file(args.key_file)
    except (ValueError, json.JSONDecodeError, OSError) as e:
        print(f"ERROR: Invalid key file: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"✓ Key file valid")

    # ─── Validate the AAB ─────────────────────────────────────────────────
    aab_path = Path(args.aab)
    if not aab_path.is_file():
        print(f"ERROR: AAB not found: {aab_path}", file=sys.stderr)
        sys.exit(1)
    size_mb = aab_path.stat().st_size / 1024 / 1024
    print(f"✓ AAB found ({size_mb:.1f} MB)")

    if args.validate_only:
        print("\nValidation complete — no upload (--validate-only).")
        sys.exit(0)

    # ─── Publish ──────────────────────────────────────────────────────────
    print(f"\nPublishing {args.package} → {args.track} track...")
    client = Client.from_key_file(args.key_file)
    try:
        result = client.publish(
            package_name=args.package,
            aab_path=str(aab_path),
            track=args.track,
            release_notes=args.notes,
        )
    except PlayAPIError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        if e.body:
            print(f"  API response: {e.body}", file=sys.stderr)
        if e.status_code:
            sys.exit(1)
        sys.exit(1)

    print()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
