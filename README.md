# RobotNerd APK Server

A tiny HTTP server that serves the debug APK for download to your phone over the
tailnet. Part of the phone-based dev workflow: build on the dev machine, download
on the phone, install and test.

## Usage

```bash
# From anywhere — it auto-finds the APK by walking up to the Gradle root
./apk-server/serve.py

# Custom port
PORT=9000 ./apk-server/serve.py

# Explicit APK path (if auto-detect fails)
./apk-server/serve.py /path/to/some.apk
```

On startup it prints all reachable URLs (tailnet + LAN IPs). Open one on your
phone, tap download, install.

## How it works

- **Auto-discovery:** Walks up from `serve.py` looking for `settings.gradle.kts`
  (the Gradle project root), then finds the APK at
  `app/build/outputs/apk/debug/app-debug.apk`. No hardcoded paths.
- **Binds to `0.0.0.0`:** Reachable from any interface (tailnet, LAN, localhost).
- **Landing page:** Shows file size, build time, git commit, and package name.
- **Direct download:** `http://<ip>:8080/app-debug.apk` for scripted/automated pulls.

## Build the APK first

```bash
export ANDROID_HOME=$(pwd)/android-sdk
./gradlew :app:assembleDebug
```

Then run the server. The APK lands at
`app/build/outputs/apk/debug/app-debug.apk`.

## Notes

- You may need to allow **"Install unknown apps"** for your browser in Android Settings.
- Python 3 only (no Node.js required). Uses only the standard library.
