# Play Store API Credentials — Setup Guide

This guide walks you through getting every credential and permission needed to
let the APK server publish apps to the Google Play Store. **Do this work on your
computer** (not inside this repo — the secrets stay outside the repo).

Once done, you'll have two files to place on your machine:
`~/.config/apk-server/play-service-account.json` and a release keystore.

---

## Prerequisites

You need:
- A **Google Play Developer account** (the one-time $25 registration, already
  paid if you've published before).
- A **Google Cloud Console project** that is linked to your Play account. This
  usually already exists (it's created automatically when you set up a Play
  Developer account).
- `openssl` and `keytool` on your machine — both are already installed:
  - OpenSSL 3.5.6 at `/usr/bin/openssl`
  - keytool at `/usr/bin/keytool`

---

## Part 1: Create the Service Account (Play API credential)

This is the credential your scripts use to authenticate to the Play Developer
API. It's a **service account** — a machine identity — not your personal Google
login.

### Step 1.1 — Open Google Cloud Console

1. Go to **https://console.cloud.google.com/**
2. Make sure you're in the project that's linked to your Play Developer account.
   The project selector is in the top bar. If you're not sure which one, it's
   typically named something like "Google Play Android Developer" or has your
   developer email associated.

### Step 1.2 — Enable the Google Play Developer API

1. In Cloud Console, go to **APIs & Services → Library** (left sidebar).
2. Search for **"Google Play Developer API"**.
3. Click it, then click **Enable**.
   - If it says "API enabled" already, you're good.

### Step 1.3 — Create the Service Account

1. Go to **IAM & Admin → Service Accounts** (left sidebar).
2. Click **+ CREATE SERVICE ACCOUNT** at the top.
3. Fill in:
   - **Service account name:** `apk-server-publisher`
   - **Service account ID:** leave the auto-generated one, or type
     `apk-server-publisher`
   - Click **CREATE AND CONTINUE**
4. **Grant this service account access to project (Step 2):** — **skip this**.
   Leave the role dropdown empty. Click **CONTINUE**.
5. **Grant users access (Step 3):** — **skip this**. Click **DONE**.

> The service account does **not** need any Cloud project roles. Its power comes
> from being linked inside the Play Console, not from Cloud IAM.

### Step 1.4 — Create the JSON Key

1. On the Service Accounts list, click the email address of the account you just
   created (`apk-server-publisher@<project>.iam.gserviceaccount.com`).
2. Go to the **KEYS** tab.
3. Click **ADD KEY → Create new key**.
4. Key type: **JSON**.
5. Click **CREATE**.

A JSON file downloads automatically. This is your service account key.

> **⚠️ This file is a long-lived credential. Anyone with it can impersonate the
> service account. Treat it like a root password.** Never email it, never commit
> it to git, never put it in a shared folder.

### Step 1.5 — Place the key on your machine

```bash
mkdir -p ~/.config/apk-server
chmod 700 ~/.config/apk-server
```

Move the downloaded JSON file:

```bash
mv ~/Downloads/your-project-abc123.json ~/.config/apk-server/play-service-account.json
chmod 600 ~/.config/apk-server/play-service-account.json
```

### Step 1.6 — Link the service account in Play Console

This is the critical step that gives the service account permission to touch
your apps.

1. Go to **https://play.google.com/console**
2. Go to **Setup → API access** (left sidebar, near the bottom under "Setup").
3. You should see the service account you just created listed under
   "Service accounts."
   - If you don't see it, wait 5-10 minutes and refresh (propagation delay).
4. Click the service account email to expand its permissions, or go to
   **Users and permissions** (left sidebar) and find the service account there.

### Step 1.7 — Grant app-specific release permission (least privilege)

1. In **Users and permissions**, click the service account email.
2. Under **Account permissions**, make sure only these are checked:
   - ☑️ **Create new releases** (or under app permissions: "Create releases (draft/existing)").
   - Leave full admin, financial, etc. **unchecked**.
3. Under **App permissions** (per-app), select the specific apps you want this
   server to publish. For each app, grant:
   - ☑️ **Create new releases**
   - ☑️ **Edit store listings** (optional — only if you want the API to update
     listing text; leave off if you just want to push AABs)
4. Click **Invite user** or **Apply changes**.

> **Why this matters:** If the service account key ever leaks, the attacker can
> only push new app versions to the tracks you specified — they can't access
> your financial data, change your account email, or touch apps you didn't
> authorize.

### Step 1.8 — Note the service account email

You'll need this email for troubleshooting:
`apk-server-publisher@<your-project>.iam.gserviceaccount.com`

Write it down or just remember it's in the JSON file:

```bash
python3 -c "import json; d=json.load(open('$HOME/.config/apk-server/play-service-account.json')); print(d['client_email'])"
```

---

## Part 2: Create the Release Signing Keystore

Your debug APKs are signed with a debug key (Android Studio's auto-generated
key). The Play Store requires a **release key** that you control. If you've
published an app before, you may already have one — check first.

### Step 2.0 — Check if you already have a release keystore

```bash
# Common locations to check
ls -la ~/.android/*.jks ~/.android/*.keystore 2>/dev/null
ls -la ~/Documents/*/release-keystore.jks 2>/dev/null
ls -la ~/Documents/**/*.jks 2>/dev/null
```

If you find a keystore you used to sign a previous release, you can use it —
skip to Step 2.2. If not, create a new one below.

### Step 2.1 — Generate a new keystore (first time only)

> ⚠️ **The keystore password and key password must be kept safe.** If you lose
> the keystore or its passwords, you can never publish an update to that app
> under the same key. Back it up somewhere secure (not in this git repo).

```bash
keytool -genkeypair \
    -v \
    -keystore ~/.config/apk-server/release-keystore.jks \
    -alias release \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000 \
    -storepass TYPE_STORE_PASSWORD \
    -keypass TYPE_KEY_PASSWORD \
    -dname "CN=Interrupt, OU=, O=, L=, ST=, C=US"
```

Replace the passwords and the `-dname` fields with your own. Use strong
passwords (20+ random characters each). You can generate them:

```bash
openssl rand -base64 18  # generate a strong password
```

### Step 2.2 — Record the keystore details

You'll need four values for the build configuration:

| Value | Example |
|---|---|
| **Keystore file path** | `~/.config/apk-server/release-keystore.jks` |
| **Keystore password** | (the `-storepass` you chose) |
| **Key alias** | `release` (or whatever alias you used) |
| **Key password** | (the `-keypass` you chose) |

### Step 2.3 — Store the passwords securely

Put them in a file that's protected:

```bash
cat > ~/.config/apk-server/signing.env <<'EOF'
# Release keystore credentials — chmod 600
KEYSTORE_PATH=$HOME/.config/apk-server/release-keystore.jks
KEYSTORE_PASSWORD=your-store-password-here
KEY_ALIAS=release
KEY_PASSWORD=your-key-password-here
EOF
chmod 600 ~/.config/apk-server/signing.env
```

The publish script will read this file instead of having passwords in the repo.

### Step 2.4 — Lock down permissions

```bash
chmod 600 ~/.config/apk-server/release-keystore.jks
chmod 700 ~/.config/apk-server
ls -la ~/.config/apk-server/
```

All files should show `-rw-------` (600) and the directory `-rwx------` (700).

---

## Part 3: Verify the Service Account Key

Before moving on, verify the JSON key is valid and the Play API accepts it.

### Step 3.1 — Extract the private key and client email

```bash
SA_KEY=~/.config/apk-server/play-service-account.json
python3 -c "import json; d=json.load(open('$SA_KEY')); print('Email:', d['client_email']); print('Key type:', d['type'])"
```

You should see:
```
Email: apk-server-publisher@<project>.iam.gserviceaccount.com
Key type: service_account
```

### Step 3.2 — Exchange key for an OAuth access token

The Play API uses OAuth2 JWT-Bearer flow. The `play-publish.sh` script (once
built) does this automatically using `openssl` + `curl` with zero Python
packages. For now, you can verify the key is well-formed:

```bash
python3 -c "
import json
with open('$HOME/.config/apk-server/play-service-account.json') as f:
    d = json.load(f)
required = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email', 'token_uri']
missing = [k for k in required if k not in d]
if missing:
    print('ERROR: Missing fields:', missing)
else:
    print('OK: All required fields present')
    print('  Project:', d['project_id'])
    print('  Token URI:', d['token_uri'])
    print('  Key ID:', d['private_key_id'][:12] + '...')
"
```

---

## Part 4: First Manual Upload (one-time per app)

Google requires the **very first upload** of a brand-new app to go through the
Play Console web UI by hand. The API can only push **updates** to existing
listings. You only do this once per app.

### For each app you want to publish via the API:

1. In Android Studio (or from the command line), build a signed AAB for
   **release**:
   ```bash
   cd ~/Documents/your-app
   ./gradlew :app:bundleRelease
   ```
   (This requires signing to be configured in `build.gradle` — see
   `TOTP_OTP_GATE.md` or the app's existing config.)

2. Go to **Play Console → [your app] → Production → Create release**.
3. Upload the `.aab` manually.
4. Fill in release notes and roll it out to internal testing.
5. Once the app exists in the Console with at least one version, the API can
   push all future updates.

After this one-time step, all subsequent publishes can go through the API.

---

## Summary Checklist

After completing this guide, you should have:

- [ ] `~/.config/apk-server/` directory (chmod 700)
- [ ] `~/.config/apk-server/play-service-account.json` (chmod 600) — the Play API key
- [ ] `~/.config/apk-server/release-keystore.jks` (chmod 600) — the signing key
- [ ] `~/.config/apk-server/signing.env` (chmod 600) — keystore passwords
- [ ] Service account linked in Play Console with per-app release permission
- [ ] Google Play Developer API enabled in Cloud Console
- [ ] At least one manual AAB upload per app (so the API can push updates)

## Security Reminders

- **Never commit any of these files to git.** They are all outside this repo by
  design (in `~/.config/apk-server/`).
- **The `.gitignore`** already excludes `builds/` and `tmp/`. If you ever need
  to put test keys inside the repo temporarily, add the path to `.gitignore`
  first.
- **Back up the keystore** offline (encrypted USB, password manager attachment).
  If you lose it, you can never update apps signed with that key without
  contacting Google Support (slow and not guaranteed).
- **Rotate the service account key** if you suspect compromise: delete it in
  Cloud Console and create a new one.
