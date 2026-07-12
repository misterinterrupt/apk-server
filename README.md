# RobotNerd APK Server

A build archive + HTTP server for delivering debug APKs to your phone over the
tailnet. Part of the phone-based dev workflow: build on the dev machine,
download on the phone, install and test.

## Workflow

```bash
# 1. Build and archive a new APK
./apk-server/publish.sh

# 2. Serve it (leave running in the background)
./apk-server/serve.py
```

Each published build is archived in `apk-server/builds/` with a unique name:

```
robotnerd-{build}-{commit}[-dirty].apk
```

- **build** — commit count (monotonically increasing integer)
- **commit** — short git hash
- **dirty** — appended when there are uncommitted changes at publish time

The landing page lists all builds, newest first. The server re-scans the
archive on every request, so newly published builds appear instantly without a
restart.

## Usage

### publish.sh

```bash
./apk-server/publish.sh             # build + archive
./apk-server/publish.sh --force     # rebuild even if same commit already archived
```

Skips the build if the same clean commit is already archived (use `--force` to
override). Dirty builds always rebuild since the source may have changed.

### serve.py

```bash
./apk-server/serve.py               # port 8080
PORT=9000 ./apk-server/serve.py     # custom port
```

On startup it prints all reachable URLs (tailnet + LAN IPs). The server binds
to `0.0.0.0` so it's reachable from any interface.

## Notes

- The `builds/` directory is gitignored (large binaries, machine-local).
- Python 3 only (stdlib). No Node.js required.
- You may need to allow **"Install unknown apps"** for your browser in Android
  Settings.
