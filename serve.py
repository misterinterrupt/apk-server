#!/usr/bin/env python3
"""
RobotNerd APK Server — serves debug APKs over HTTP for download to a phone.

Designed for the tailnet dev workflow: build on this machine, download on your
phone. Auto-discovers the APK so it survives directory moves; binds to all
interfaces so it's reachable from anywhere on your network.

Usage:
    ./serve.py                    # defaults: port 8080, auto-find APK
    PORT=9000 ./serve.py          # custom port
    ./serve.py /path/to/app.apk   # explicit APK path
"""

import os
import socket
import subprocess
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

PORT = int(os.environ.get("PORT", "8080"))
PACKAGE = "com.ntrpt.robotnerd"
APP_NAME = "RobotNerd"


def find_apk():
    """Walk up from this script to find the Gradle project root, then locate the APK."""
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        return Path(sys.argv[1])

    # Walk up from this file looking for settings.gradle.kts (project root marker)
    here = Path(__file__).resolve().parent
    for candidate in [here, *here.parents]:
        if (candidate / "settings.gradle.kts").exists():
            apk = candidate / "app/build/outputs/apk/debug/app-debug.apk"
            if apk.exists():
                return apk
            # Try release too
            apk = candidate / "app/build/outputs/apk/release/app-release-unsigned.apk"
            if apk.exists():
                return apk
            break

    print("ERROR: Could not find the APK. Build it first with:")
    print("  ./gradlew :app:assembleDebug")
    print("Or pass the path explicitly: ./serve.py /path/to/app.apk")
    sys.exit(1)


def get_local_ips():
    """Return list of IPs this machine is reachable on (tailnet + LAN)."""
    ips = []
    try:
        # Connect to a public address to determine which interface is used
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    # Also grab all interface IPs
    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "addr"], capture_output=True, text=True, timeout=2
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                ip = parts[3].split("/")[0]
                if ip not in ips and not ip.startswith("127."):
                    ips.append(ip)
    except Exception:
        pass

    return ips or ["localhost"]


def git_commit():
    """Get short git hash of HEAD, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


APK_PATH = find_apk()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.serve_landing()
        elif self.path == "/app-debug.apk":
            self.serve_apk()
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Not found")

    def serve_landing(self):
        try:
            stat = APK_PATH.stat()
            size_mb = stat.st_size / 1024 / 1024
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            size_mb = 0
            modified = "?"

        commit = git_commit()
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME} APK</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 600px;
         margin: 0 auto; padding: 40px 20px; background: #1a1a2e; color: #e0e0e0; }}
  h1 {{ margin-bottom: 8px; }}
  .subtitle {{ color: #888; margin-bottom: 32px; }}
  a.download {{ color: #7c4dff; font-size: 1.3em; text-decoration: none; display: block;
         text-align: center; padding: 20px; background: #2a2a4e; border-radius: 12px;
         border: 1px solid #7c4dff; transition: background .15s; }}
  a.download:hover {{ background: #3a3a5e; }}
  .info {{ margin-top: 28px; color: #888; font-size: 0.9em; line-height: 1.8; }}
  .info strong {{ color: #bbb; }}
  code {{ background: #0d0d1a; padding: 2px 8px; border-radius: 4px; color: #7c4dff;
          font-size: 0.85em; }}
</style>
</head>
<body>
  <h1>\U0001f916 {APP_NAME} Debug APK</h1>
  <p class="subtitle">Tap to download, then open the file to install.</p>
  <a class="download" href="/app-debug.apk">\u2b07\ufe0f Download {APP_NAME} ({size_mb:.1f} MB)</a>
  <div class="info">
    <p><strong>Build:</strong> {modified}</p>
    <p><strong>Commit:</strong> <code>{commit}</code></p>
    <p><strong>Package:</strong> <code>{PACKAGE}</code></p>
    <p><strong>Size:</strong> {size_mb:.1f} MB</p>
    <hr style="border-color:#333;margin:20px 0">
    <p>You may need to allow <em>"Install unknown apps"</em> for your browser in Settings.</p>
  </div>
</body>
</html>"""
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_apk(self):
        if not APK_PATH.exists():
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"APK not found. Run ./gradlew :app:assembleDebug first.")
            return

        size = APK_PATH.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.android.package-archive")
        self.send_header("Content-Length", str(size))
        self.send_header(
            "Content-Disposition", f'attachment; filename="{APP_NAME.lower()}-debug.apk"'
        )
        self.end_headers()
        with open(APK_PATH, "rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"\n\033[1m{APP_NAME} APK Server\033[0m")
    print(f"  APK:   {APK_PATH}")
    try:
        stat = APK_PATH.stat()
        print(f"  Size:  {stat.st_size / 1024 / 1024:.1f} MB")
        print(f"  Built: {datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')}")
    except OSError:
        pass
    print(f"\n\033[1mDownload from your phone:\033[0m")
    for ip in get_local_ips():
        print(f"  \033[36mhttp://{ip}:{PORT}\033[0m")
    print(f"\n  Listening on 0.0.0.0:{PORT} (Ctrl+C to stop)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down.")
        server.shutdown()
