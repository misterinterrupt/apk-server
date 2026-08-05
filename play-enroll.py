#!/usr/bin/env python3
"""
play-enroll.py — Generate and enroll a TOTP secret for Play Store publishing.

This is a one-time setup. It generates a random secret, saves it to
~/.config/apk-server/totp-secret, and displays an otpauth:// URI (with optional
QR code if qrencode is installed) for you to add to your authenticator app.

Usage:
    ./play-enroll.py              # generate secret + show URI/QR
    ./play-enroll.py --verify     # test that your authenticator produces valid codes

No external Python packages required. Optional: qrencode CLI for QR display.
"""

import sys
import os
import subprocess
import shutil
from pathlib import Path

import totp


def have(cmd):
    return shutil.which(cmd) is not None


def show_qr(uri):
    """Print a QR code to the terminal if qrencode is available."""
    if not have("qrencode"):
        return False
    try:
        subprocess.run(
            ["qrencode", "-t", "ANSIUTF8", "-o", "-", uri],
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def enroll():
    print("=" * 60)
    print("  TOTP Enrollment for Play Store Publishing")
    print("=" * 60)
    print()

    # Check for existing secret
    try:
        existing = totp.load_secret()
        response = input(
            f"A TOTP secret already exists at {totp.SECRET_FILE}.\n"
            "Re-enrolling will invalidate your current authenticator entry.\n"
            "Continue? (yes/no): "
        )
        if response.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)
    except FileNotFoundError:
        pass

    # Generate and save
    secret = totp.generate_secret()
    totp.save_secret(secret)

    uri = totp.otpauth_uri(secret)
    print("✓ Secret generated and saved to:")
    print(f"    {totp.SECRET_FILE}")
    print()
    print("Scan this QR code with your authenticator app")
    print("(Google Authenticator, Authy, Aegis, FreeOTP, etc.):")
    print()
    if show_qr(uri):
        print()
    else:
        print("(Install qrencode to see a QR code: sudo apt install qrencode)")
        print()

    print("Or add manually using this secret key:")
    print()
    print(f"    {secret}")
    print()
    print("Settings for manual entry:")
    print(f"    Type:   Time-based (TOTP)")
    print(f"    Digits: {totp.DIGITS}")
    print(f"    Period: {totp.STEP} seconds")
    print()
    print("otpauth:// URI (for apps that accept it):")
    print(f"    {uri}")
    print()
    print("Next: run './play-enroll.py --verify' to confirm enrollment.")
    print("      (Wait up to 30s for your authenticator to sync.)")


def verify():
    print("=" * 60)
    print("  TOTP Verification")
    print("=" * 60)
    print()
    try:
        totp.load_secret()
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    code = input("Enter the current 6-digit code from your authenticator: ").strip()
    # Use verify (not check_and_record_replay) for enrollment testing — we
    # don't want to burn the code in replay protection.
    if totp.verify(totp.load_secret(), code):
        print()
        print("✓ Verified! Your authenticator is correctly enrolled.")
        print("  The publish feature will now require this code.")
    else:
        print()
        print("✗ Invalid code. Possible causes:")
        print("  - Clock drift — check timedatectl status on this machine")
        print("  - Typo — try again")
        print("  - Wrong secret — re-run play-enroll.py")
        sys.exit(1)


def main():
    if "--verify" in sys.argv:
        verify()
    else:
        enroll()


if __name__ == "__main__":
    main()
