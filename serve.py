#!/usr/bin/env python3
"""
APK Server — serves archived debug APKs over HTTP, with project tabs.

Builds are organized into project subfolders under builds/:
  builds/<slug>/<slug>-{build}-{commit}[-dirty].apk

Projects are configured in projects.json. The landing page shows a tab for
each project. The server re-scans on every request, so newly published builds
appear instantly without a restart.

Usage:
    ./serve.py                # port 8080
    PORT=9000 ./serve.py      # custom port
"""

import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, quote

PORT = int(os.environ.get("PORT", "8080"))

HERE = Path(__file__).resolve().parent
BUILDS_DIR = HERE / "builds"
CONFIG_FILE = HERE / "projects.json"

# Filename pattern: <anything>-<build>-<commit>[-dirty].apk
APK_PATTERN = re.compile(r"^(.+)-(\d+)-([0-9a-f]+)(-dirty)?\.apk$")
AAB_PATTERN = re.compile(r"^(.+)-(\d+)-([0-9a-f]+)(-dirty)?\.aab$")


def load_config():
    """Load project configuration from projects.json."""
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            return cfg.get("projects", [])
        except (json.JSONDecodeError, OSError):
            pass
    # Fallback: auto-discover from builds/ directory
    projects = []
    if BUILDS_DIR.is_dir():
        for folder in sorted(BUILDS_DIR.iterdir()):
            if folder.is_dir():
                projects.append({
                    "slug": folder.name,
                    "name": folder.name.replace("-", " ").title(),
                    "color": "#7c4dff",
                    "namespace": "",
                })
    return projects


def build_project_map():
    """Build (slug -> (name, color)) map from config."""
    projects = load_config()
    return {p["slug"]: (p["name"], p["color"]) for p in projects}


def build_package_map():
    """Build (slug -> namespace) map from config."""
    projects = load_config()
    return {p["slug"]: p.get("namespace", "") for p in projects if p.get("namespace")}


def get_local_ips():
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
    def __init__(self, path, project):
        self.path = path
        self.project = project
        self.filename = path.name
        self.url = f"/{project}/{quote(self.filename)}"
        stat = path.stat()
        self.size_mb = stat.st_size / 1024 / 1024
        self.modified = datetime.fromtimestamp(stat.st_mtime)

        m = APK_PATTERN.match(self.filename)
        if m:
            self.build_num = int(m.group(2))
            self.commit = m.group(3)
            self.dirty = bool(m.group(4))
        else:
            self.build_num = 0
            self.commit = self.filename
            self.dirty = False

    @property
    def commit_label(self):
        return self.commit + ("-dirty" if self.dirty else "")

    def sort_key(self):
        return (self.build_num, self.modified)


def get_projects():
    project_map = build_project_map()
    result = []
    for slug, (name, color) in project_map.items():
        if (BUILDS_DIR / slug).is_dir():
            result.append((slug, name, color))
    return result


def get_builds(project=None):
    if not BUILDS_DIR.exists():
        return []
    builds = []
    if project:
        pdir = BUILDS_DIR / project
        if pdir.is_dir():
            builds = [Build(f, project) for f in pdir.glob("*.apk")]
    else:
        for folder, _, _ in get_projects():
            pdir = BUILDS_DIR / folder
            if pdir.is_dir():
                builds.extend(Build(f, folder) for f in pdir.glob("*.apk"))
    builds.sort(key=Build.sort_key, reverse=True)
    return builds


def get_aab_builds(project):
    """Return a list of dicts for all archived AABs for a project, newest first."""
    pdir = BUILDS_DIR / project
    if not pdir.is_dir():
        return []
    aabs = []
    for f in pdir.glob("*.aab"):
        stat = f.stat()
        m = AAB_PATTERN.match(f.name)
        if m:
            build_num = int(m.group(2))
            commit = m.group(3)
            dirty = bool(m.group(4))
        else:
            build_num = 0
            commit = f.name
            dirty = False
        aabs.append({
            "filename": f.name,
            "buildNumber": build_num,
            "commit": commit,
            "dirty": dirty,
            "sizeMb": round(stat.st_size / 1024 / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    aabs.sort(key=lambda a: (a["buildNumber"], a["modified"]), reverse=True)
    return aabs


def get_latest_aab(project):
    """Return the Path to the newest AAB for a project, or None."""
    pdir = BUILDS_DIR / project
    if not pdir.is_dir():
        return None
    aabs = list(pdir.glob("*.aab"))
    if not aabs:
        return None

    def sort_key(path):
        m = AAB_PATTERN.match(path.name)
        build_num = int(m.group(2)) if m else 0
        return (build_num, path.stat().st_mtime)

    aabs.sort(key=sort_key, reverse=True)
    return aabs[0]


def build_to_dict(b):
    """Serialize a Build to a JSON-friendly dict for the API."""
    return {
        "buildNumber": b.build_num,
        "commit": b.commit,
        "dirty": b.dirty,
        "filename": b.filename,
        "downloadUrl": f"/{b.project}/{quote(b.filename)}",
        "sizeBytes": int(b.path.stat().st_size),
        "sizeMb": round(b.size_mb, 1),
        "modified": b.modified.isoformat(),
    }


def get_namespace_map():
    """Build a mapping from namespace substrings to project slugs, for
    auto-detection in publish.sh.  Loaded from projects.json."""
    projects = load_config()
    mapping = {}
    for p in projects:
        ns = p.get("namespace", "")
        if ns:
            mapping[ns] = p["slug"]
    return mapping


# Directory for Play Store secrets and the release keystore.
PLAY_CONFIG_DIR = Path(os.environ.get(
    "APK_SERVER_CONFIG_DIR",
    str(Path.home() / ".config" / "apk-server"),
))

# Expose the project config for shell scripts.
PROJECTS = load_config()
PROJECT_MAP = build_project_map()
PROJECT_PACKAGES = build_package_map()


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 keep-alive — every response path sends Content-Length, so
    # persistent connections are safe. `timeout` reaps idle keep-alive
    # connections so threads don't pile up.
    protocol_version = "HTTP/1.1"
    timeout = 60

    def do_POST(self):
        """Handle POST requests for Play Store publishing."""
        # POSTs (Play publishing) are rare — close the connection after
        # each one so an unread request body can't desync a reused
        # keep-alive connection.
        self.close_connection = True
        path_only = unquote(self.path.split("?", 1)[0])
        if path_only.startswith("/api/"):
            self.serve_api_post(path_only)
        else:
            self.not_found()

    def do_GET(self):
        # Strip query string for routing.
        path_only = unquote(self.path.split("?", 1)[0])
        if path_only.startswith("/api/"):
            self.serve_api(path_only)
        elif path_only in ("/", "/index.html"):
            self.serve_landing()
        elif path_only.endswith(".apk"):
            self.serve_apk(path_only)
        else:
            self.not_found()

    def serve_api(self, path):
        """JSON API for programmatic clients (e.g. the apksync library).

        GET /api/projects              → list of project sections
        GET /api/{project}/builds      → list of builds for a project
        GET /api/{project}/aab-builds  → list of archived AABs
        POST /api/{project}/play-publish → publish AAB to Play (TOTP-gated)
        """
        parts = [p for p in path.strip("/").split("/") if p]
        # parts[0] == "api"

        if len(parts) == 2 and parts[1] == "projects":
            # /api/projects
            data = [
                {"id": folder, "name": name, "color": color}
                for folder, name, color in get_projects()
            ]
            self.send_json(data)
            return

        if len(parts) == 3 and parts[2] == "builds":
            # /api/{project}/builds
            project = parts[1]
            if project not in [p[0] for p in get_projects()]:
                self.send_json([], status=404)
                return
            builds = get_builds(project)
            data = [build_to_dict(b) for b in builds]
            self.send_json(data)
            return

        if len(parts) == 3 and parts[2] == "aab-builds":
            # /api/{project}/aab-builds
            project = parts[1]
            project_map = build_project_map()
            if project not in project_map:
                self.send_json([], status=404)
                return
            aabs = get_aab_builds(project)
            self.send_json(aabs)
            return

        self.send_json({"error": "Not found"}, status=404)

    def serve_api_post(self, path):
        """Handle POST API requests.

        POST /api/{project}/play-publish
            Body: {"totp": "123456", "track": "internal", "notes": "..."}
            Publishes the latest archived AAB to the Play Store.
            Requires a valid TOTP code (see TOTP_OTP_GATE.md).
        """
        parts = [p for p in path.strip("/").split("/") if p]

        if len(parts) == 3 and parts[2] == "play-publish":
            project = parts[1]
            self.handle_play_publish(project)
            return

        self.send_json({"error": "Not found"}, status=404)

    def read_json_body(self):
        """Read and parse a JSON request body. Returns (data, error)."""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return None, "Invalid Content-Length"
        if length == 0 or length > 65536:
            return None, "Empty or too-large body"
        try:
            raw = self.rfile.read(length)
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as e:
            return None, f"Invalid JSON: {e}"
        if not isinstance(data, dict):
            return None, "Body must be a JSON object"
        return data, None

    def handle_play_publish(self, project):
        """Publish the latest AAB for a project to the Play Store.

        Validates TOTP, then calls playapi to upload + commit.
        This is the HTTP interface for play-publish.sh.
        """
        packages = build_package_map()
        # Validate project
        if project not in packages:
            self.send_json({"error": f"Unknown project '{project}'"}, status=404)
            return

        # Parse and validate the request body
        data, err = self.read_json_body()
        if err:
            self.send_json({"error": err}, status=400)
            return

        track = data.get("track", "internal")
        notes = data.get("notes", "")
        totp_code = data.get("totp", "")

        if track not in ("internal", "alpha", "beta", "production"):
            self.send_json(
                {"error": f"Invalid track: {track}. Must be one of: internal, alpha, beta, production"},
                status=400,
            )
            return

        # TOTP verification
        import totp
        if totp.TOTP_ENABLED:
            if not totp_code:
                self.send_json(
                    {"error": "TOTP code required (TOTP_ENABLED=True)"},
                    status=401,
                )
                return
            if not totp.verify(totp_code):
                self.send_json({"error": "Invalid TOTP code"}, status=403)
                return

        # Find latest AAB
        aab_path = get_latest_aab(project)
        if not aab_path:
            self.send_json(
                {"error": f"No AAB builds found for project '{project}'. Build one with play-publish.sh first."},
                status=404,
            )
            return

        # Publish to Play
        package = packages[project]
        try:
            import playapi
            key_file = PLAY_CONFIG_DIR / "play-service-account.json"
            if not key_file.is_file():
                self.send_json(
                    {"error": f"Service account key not found at {key_file}"},
                    status=500,
                )
                return

            client = playapi.Client.from_key_file(str(key_file))
            result = client.publish(
                package_name=package,
                aab_path=str(aab_path),
                track=track,
                release_notes=notes,
            )
            self.send_json(result, status=200)
        except playapi.PlayAPIError as e:
            self.send_json(
                {"error": str(e), "apiBody": e.body, "statusCode": e.status_code},
                status=502,
            )
        except Exception as e:
            self.send_json({"error": f"Publish failed: {e}"}, status=500)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def not_found(self):
        body = b"Not found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_landing(self):
        projects = get_projects()

        # Determine active project from ?project= query param.
        active_project = None
        if "?" in self.path:
            query = self.path.split("?", 1)[1]
            for pair in query.split("&"):
                if pair.startswith("project="):
                    candidate = unquote(pair[8:])
                    if candidate in [p[0] for p in projects]:
                        active_project = candidate
                    break

        if active_project:
            builds = get_builds(active_project)
        elif projects:
            active_project = projects[0][0]
            builds = get_builds(active_project)
        else:
            builds = []

        latest = builds[0] if builds else None
        older = builds[1:] if len(builds) > 1 else []

        # Tabs
        tabs_html = ""
        if len(projects) > 1:
            tab_items = []
            for folder, name, color in projects:
                cls = "tab active" if folder == active_project else "tab"
                border = color if folder == active_project else "transparent"
                tab_items.append(
                    f'<a class="{cls}" href="/?project={folder}" '
                    f'style="border-color: {border}">'
                    f'<span class="tab-dot" style="background:{color}"></span>{name}</a>'
                )
            tabs_html = f'<div class="tabs">{"".join(tab_items)}</div>'

        project_map = build_project_map()
        active_color = project_map.get(active_project, ("App", "#7c4dff"))[1] if active_project else "#7c4dff"
        active_name = project_map.get(active_project, ("App", "#7c4dff"))[0] if active_project else "App"

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
                '    <p class="muted">Run <code>./publish.sh</code> '
                "to build and archive an APK.</p>\n"
                "  </div>"
            )

        if older:
            rows = []
            for b in older:
                dirty_tag = ' <span class="dirty">dirty</span>' if b.dirty else ""
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
<title>{active_name} APKs</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 640px;
         margin: 0 auto; padding: 32px 20px; background: #1a1a2e; color: #e0e0e0; }}
  h1 {{ margin-bottom: 4px; }}
  h2 {{ font-size: 1em; text-transform: uppercase; letter-spacing: 1px;
       color: #666; margin: 32px 0 12px; }}
  .count {{ color: #555; font-size: 0.85em; margin-bottom: 8px; }}
  .tabs {{ display: flex; gap: 4px; margin-bottom: 24px; flex-wrap: wrap; }}
  .tab {{ display: inline-flex; align-items: center; gap: 6px;
         padding: 8px 16px; border-radius: 20px; text-decoration: none;
         color: #999; font-size: 0.9em; font-weight: 500;
         background: #1e1e36; border: 2px solid transparent; transition: all .15s; }}
  .tab:hover {{ background: #26264a; }}
  .tab.active {{ color: #e0e0e0; }}
  .tab-dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
  a.latest {{ display: block; text-align: center; padding: 24px;
       background: #2a2a4e; border-radius: 14px;
       border: 1px solid {active_color};
       text-decoration: none; margin: 20px 0; transition: background .15s; }}
  a.latest:hover {{ background: #3a3a5e; }}
  .latest-label {{ display: block; font-size: 1.3em; color: {active_color}; font-weight: 600; }}
  .latest-info {{ display: block; margin-top: 8px; color: #888; font-size: 0.9em; }}
  .build-list {{ display: flex; flex-direction: column; gap: 2px; }}
  a.row {{ display: flex; align-items: center; gap: 12px; padding: 12px 16px;
       background: #1e1e36; border-radius: 8px; text-decoration: none;
       color: #ccc; font-size: 0.9em; transition: background .15s; }}
  a.row:hover {{ background: #26264a; }}
  .row-num {{ color: {active_color}; font-weight: 600; min-width: 36px; }}
  .row-commit {{ font-family: monospace; font-size: 0.85em; flex: 1; }}
  .row-size {{ color: #888; min-width: 64px; text-align: right; }}
  .row-date {{ color: #666; font-size: 0.85em; min-width: 100px; text-align: right; }}
  .dirty {{ color: #e8a64a; font-size: 0.8em; }}
  .empty {{ text-align: center; padding: 48px 0; color: #888; }}
  .muted {{ color: #555; font-size: 0.9em; }}
  code {{ background: #0d0d1a; padding: 2px 8px; border-radius: 4px;
         color: {active_color}; font-size: 0.85em; }}
  .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #2a2a4e;
            color: #555; font-size: 0.8em; line-height: 1.7; }}
</style>
</head>
<body>
  <h1 style="color: {active_color}">{active_name}</h1>
{tabs_html}
  <p class="count">{total} {word} available</p>
{latest_html}
{older_html}
  <div class="footer">
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
        parts = path.lstrip("/").split("/")
        if len(parts) == 2 and parts[1].endswith(".apk"):
            project = parts[0]
            filename = parts[1]
            apk_path = BUILDS_DIR / project / filename
        else:
            filename = path.lstrip("/")
            apk_path = BUILDS_DIR / filename

        if not apk_path.is_file():
            self.not_found()
            return

        size = apk_path.stat().st_size

        # Range support (bytes=N-, bytes=N-M, bytes=-N) so an interrupted
        # download can resume instead of restarting 20MB from byte zero.
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range")
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)$", range_header.strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                else:  # suffix form: bytes=-N → the last N bytes
                    start = max(0, size - int(m.group(2)))
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206

        remaining = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "application/vnd.android.package-archive")
        self.send_header("Content-Length", str(remaining))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            with open(apk_path, "rb") as f:
                f.seek(start)
                sent = 0
                while chunk := f.read(65536):
                    if sent + len(chunk) > remaining:
                        chunk = chunk[: remaining - sent]
                    self.wfile.write(chunk)
                    sent += len(chunk)
                    if sent >= remaining:
                        break
        except (ConnectionResetError, BrokenPipeError, TimeoutError):
            # Client hung up mid-transfer (flaky mobile/Tailscale link) —
            # not a server error. Log quietly and drop the connection.
            print(f"  {self.address_string()} - download aborted: {filename}")
            self.close_connection = True

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} - {fmt % args}")


class ApkServer(ThreadingHTTPServer):
    """Threaded server: a slow APK download must not block API polls.

    The single-threaded HTTPServer head-of-line-blocked every request
    behind an in-flight download, and its listen backlog of 5 made the
    kernel RST excess connections — surfacing on Android as
    "SocketException: Software caused connection abort".
    """

    daemon_threads = True
    request_queue_size = 64

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, TimeoutError)):
            print(f"  {client_address[0]} - client disconnected: {type(exc).__name__}")
            return
        super().handle_error(request, client_address)


if __name__ == "__main__":
    server = ApkServer(("0.0.0.0", PORT), Handler)
    all_builds = get_builds()
    projects = get_projects()

    print(f"\n\033[1mAPK Server\033[0m")
    print(f"  Builds dir: {BUILDS_DIR}")
    print(f"  Config:     {CONFIG_FILE}")
    print(f"  Projects:   {', '.join(p[1] for p in projects) if projects else 'none'}")
    print(f"  Archived:   {len(all_builds)} build(s) total")

    for folder, name, color in projects:
        pbuilds = get_builds(folder)
        if pbuilds:
            latest = pbuilds[0]
            print(f"    {name}: #{latest.build_num} {latest.commit_label} ({latest.size_mb:.1f} MB)")

    print(f"\n\033[1mOpen on your phone:\033[0m")
    for ip in get_local_ips():
        print(f"  \033[36mhttp://{ip}:{PORT}\033[0m")
    print(f"\n  Listening on 0.0.0.0:{PORT} (Ctrl+C to stop)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down.")
        server.shutdown()
