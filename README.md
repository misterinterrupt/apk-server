# RobotNerd APK Server

A build archive + HTTP server for delivering debug APKs to your phone over the
tailnet. Part of the phone-based dev workflow: build on the dev machine,
download on the phone, install and test.

Part of the [RobotNerd](https://github.com/misterinterrupt/robotnerd) monorepo.

## Workflow

```bash
# 1. Build and archive a new APK
./publish.sh

# 2. Serve it (leave running in the background)
./serve.py
```

Each published build is archived in `builds/` with a unique name:

```
<slug>-{build}-{commit}[-dirty].apk
```

- **build** — commit count (monotonically increasing integer)
- **commit** — short git hash
- **dirty** — appended when there are uncommitted changes at publish time

The landing page lists all builds, newest first. The server re-scans the
archive on every request, so newly published builds appear instantly without a
restart.

## Configuration

Projects are configured in `projects.json`:

```json
{
  "projects": [
    {
      "slug": "robotnerd",
      "name": "RobotNerd",
      "color": "#7c4dff",
      "namespace": "com.ntrpt.robotnerd"
    }
  ]
}
```

Add projects with `./add-project.sh` or edit `projects.json` directly.

## Usage

### publish.sh

```bash
./publish.sh             # build + archive (auto-detects project from namespace)
./publish.sh --force     # rebuild even if same commit already archived
./publish.sh --project myapp   # specify project slug explicitly
```

Skips the build if the same clean commit is already archived (use `--force` to
override). Dirty builds always rebuild since the source may have changed.

### serve.py

```bash
./serve.py               # port 8080
PORT=9000 ./serve.py     # custom port
```

On startup it prints all reachable URLs (tailnet + LAN IPs). The server binds
to `0.0.0.0` so it's reachable from any interface.

### systemd service

Copy the service file and enable it:

```
cp robotnerd-apk-server.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now robotnerd-apk-server
```

## Adding a new project

```bash
./add-project.sh \
    --slug myapp \
    --name "My App" \
    --color "#00BCD4" \
    --namespace com.example.myapp
```

This updates `projects.json` and creates `builds/myapp/`. Idempotent — safe to re-run.

## Notes

- The `builds/` directory is gitignored (large binaries, machine-local).
- Python 3 only (stdlib). No Node.js required.
- You may need to allow **"Install unknown apps"** for your browser in Android
  Settings.

## License

MIT — see the [RobotNerd monorepo](https://github.com/misterinterrupt/robotnerd).
