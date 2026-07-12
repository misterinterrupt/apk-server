#!/usr/bin/env python3
"""
RobotNerd APK Server — serves archived debug APKs over HTTP.

Each published build lives in builds/ with a unique name:
  robotnerd-{build}-{commit}[-dirty].apk

The landing page lists all builds, newest first. The server re-scans
builds/ on every request, so newly published builds appear instantly
without a restart.

Publish new builds with:
  ./apk-server/publish.sh

Usage:
    ./serve.py                # port 8080
    PORT=9000 ./serve.py      # custom port
"""

import os
import re
import socket
import subprocess
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, quote

PORT = int(os.environ.get("PORT", "8080"))
PACKAGE = "com.ntrpt.robotnerd"
APP_NAME = "RobotNerd"
APP_SLUG = APP_NAME.lower()

HERE = Path(__file__).resolve().parent
BUILDS_DIR = HERE / "builds"

# Filename pattern: robotnerd-5-8874d22-dirty.apk
APK_PATTERN = re.compile(rf"^{APP_SLUG}-(\d+)-([0-9a-f]+)(-dirty)?\.apk$")


def get_local_ips():
    """Return list of IPs this machine is reachable on (tailnet + LAN)."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
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


class Build:
    """Represents one archived APK, with metadata parsed from its filename."""

    def __init__(self, path):
        self.path = path
        self.filename = path.name
        self.url = "/" + quote(self.filename)
        stat = path.stat()
        self.size_mb = stat.st_size / 1024 / 1024
        self.modified = datetime.fromtimestamp(stat.st_mtime)

        m = APK_PATTERN.match(self.filename)
        if m:
            self.build_num = int(m.group(1))
            self.commit = m.group(2)
            self.dirty = bool(m.group(3))
        else:
            # Unrecognized filename — show it as-is
            self.build_num = 0
            self.commit = self.filename
            self.dirty = False

    @property
    def commit_label(self):
        return self.commit + ("-dirty" if self.dirty else "")

    def sort_key(self):
        return (self.build_num, self.modified)


def get_builds():
    """Scan builds/ and return all APKs sorted newest first."""
    if not BUILDS_DIR.exists():
        return []
    builds = [Build(f) for f in BUILDS_DIR.glob("*.apk")]
    builds.sort(key=Build.sort_key, reverse=True)
    return builds


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = unquote(self.path)
        if path in ("/", "/index.html"):
            self.serve_landing()
        elif path.endswith(".apk"):
            self.serve_apk(path)
        else:
            self.not_found()

    def not_found(self):
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Not found")

    def serve_landing(self):
        builds = get_builds()
        latest = builds[0] if builds else None
        older = builds[1:] if builds else []

        if latest:
            latest_html = (
                f'  <a class="latest" href="{latest.url}">\n'
                f'    <span class="latest-label">\u2b07\ufe0f Download Latest</span>\n'
                f'    <span class="latest-info">#{latest.build_num} \u00b7 '
                f'{latest.commit_label} \u00b7 {latest.size_mb:.1f} MB</span>\n'
                f"  </a>"
            )
        else:
            latest_html = (
                '  <div class="empty">\n'
                "    <p>No builds published yet.</p>\n"
                '    <p class="muted">Run <code>./apk-server/publish.sh</code> '
                "to build and archive an APK.</p>\n"
                "  </div>"
            )

        if older:
            rows = []
            for b in older:
                dirty_tag = (
                    ' <span class="dirty">dirty</span>' if b.dirty else ""
                )
                rows.append(
                    f'    <a class="row" href="{b.url}">\n'
                    f'      <span class="row-num">#{b.build_num}</span>\n'
                    f'      <span class="row-commit">{b.commit}{dirty_tag}</span>\n'
                    f'      <span class="row-size">{b.size_mb:.1f} MB</span>\n'
                    f'      <span class="row-date">'
                    f'{b.modified.strftime("%b %d %H:%M")}</span>\n'
                    "    </a>"
                )
            older_html = (
                '  <h2>Previous builds</h2>\n'
                '  <div class="build-list">\n'
                + "\n".join(rows)
                + "\n  </div>"
            )
        else:
            older_html = ""

        total = len(builds)
        word = "build" if total == 1 else "builds"

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME} APKs</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 640px;
         margin: 0 auto; padding: 32px 20px; background: #1a1a2e; color: #e0e0e0; }}
  h1 {{ margin-bottom: 4px; }}
  h2 {{ font-size: 1em; text-transform: uppercase; letter-spacing: 1px;
       color: #666; margin: 32px 0 12px; }}
  .count {{ color: #555; font-size: 0.85em; margin-bottom: 8px; }}
  a.latest {{ display: block; text-align: center; padding: 24px;
       background: #2a2a4e; border-radius: 14px; border: 1px solid #7c4dff;
       text-decoration: none; margin: 20px 0; transition: background .15s; }}
  a.latest:hover {{ background: #3a3a5e; }}
  .latest-label {{ display: block; font-size: 1.3em; color: #7c4dff; font-weight: 600; }}
  .latest-info {{ display: block; margin-top: 8px; color: #888; font-size: 0.9em; }}
  .build-list {{ display: flex; flex-direction: column; gap: 2px; }}
  a.row {{ display: flex; align-items: center; gap: 12px; padding: 12px 16px;
       background: #1e1e36; border-radius: 8px; text-decoration: none;
       color: #ccc; font-size: 0.9em; transition: background .15s; }}
  a.row:hover {{ background: #26264a; }}
  .row-num {{ color: #7c4dff; font-weight: 600; min-width: 36px; }}
  .row-commit {{ font-family: monospace; font-size: 0.85em; flex: 1; }}
  .row-size {{ color: #888; min-width: 64px; text-align: right; }}
  .row-date {{ color: #666; font-size: 0.85em; min-width: 100px; text-align: right; }}
  .dirty {{ color: #e8a64a; font-size: 0.8em; }}
  .empty {{ text-align: center; padding: 48px 0; color: #888; }}
  .muted {{ color: #555; font-size: 0.9em; }}
  code {{ background: #0d0d1a; padding: 2px 8px; border-radius: 4px;
         color: #7c4dff; font-size: 0.85em; }}
  .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #2a2a4e;
            color: #555; font-size: 0.8em; line-height: 1.7; }}
</style>
</head>
<body>
  <h1>\U0001f916 {APP_NAME}</h1>
  <p class="count">{total} {word} available</p>
{latest_html}
{older_html}
  <div class="footer">
    <p><strong>Package:</strong> <code>{PACKAGE}</code></p>
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

    def serve_apk(self, path):
        filename = path.lstrip("/")
        apk_path = BUILDS_DIR / filename
        if not apk_path.is_file():
            self.not_found()
            return

        size = apk_path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.android.package-archive")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        with open(apk_path, "rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    builds = get_builds()
    print(f"\n\033[1m{APP_NAME} APK Server\033[0m")
    print(f"  Builds dir: {BUILDS_DIR}")
    print(f"  Archived:   {len(builds)} build(s)")
    if builds:
        latest = builds[0]
        print(
            f"  Latest:     #{latest.build_num} {latest.commit_label}"
            f" ({latest.size_mb:.1f} MB)"
        )
    print(f"\n\033[1mOpen on your phone:\033[0m")
    for ip in get_local_ips():
        print(f"  \033[36mhttp://{ip}:{PORT}\033[0m")
    print(f"\n  Listening on 0.0.0.0:{PORT} (Ctrl+C to stop)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down.")
        server.shutdown()
