# Notki

A fast, lightweight, and private web-based note-taking application written in Python 3.9+. Runtime dependencies are pinned in `requirements.txt` (`webauthn` for passkeys and `cryptography` for encrypted backups).

![Main notes view](docs/desktop_notes_light.png)

--------------------------------------------------------------------------------

## Key Features

* Note Creation & Rich Formatting
  Rich text formatting (bold, italic, underline, font sizing), bulleted/numbered lists, and interactive checklists with real-time progress indicators and drag-and-drop task handles.

* Due Dates & Daily Plan
  Schedule notes with due dates, view timeline sections (overdue, today, tomorrow, this week, later), and export events to iCalendar (`.ics`).

* Labels & Flexible Organization
  Categorize with custom labels/tags, pin essential notes to the top, archive inactive items, manage trash, and personalize cards with adaptive pastel colors.

* Note Sharing & Collaboration
  Securely share notes with other users on your server using configurable read-only or read-write permissions.

* Offline First & Auto-Sync
  Work seamlessly offline thanks to browser caching and background sync when connection is restored.

* User Profiles & Avatars
  Profile customization, password management, and custom avatar upload support.

* Advanced Security & Authentication
  - Two-Factor Authentication (2FA) supporting both TOTP (Authenticator Apps) and WebAuthn Passkeys / Hardware Security Keys (FIDO2/Touch ID/Face ID).
  - Emergency 2FA recovery backup codes.
  - Option to enforce 2FA server-wide via administrative settings.
  - Fail2ban rate limiting on login and 2FA endpoints to prevent brute-force attempts, with configurable ban thresholds and duration in the Admin Panel.

* Encrypted Backups
  Full server state backup, download, upload, and restore. Backups are encrypted with AES-GCM using a server key or an explicit password, with import support during first-run setup.

* Comprehensive Admin Panel
  User account management, single-use invitation link generation with custom expiration, server system stats, pinned server announcements, and direct update checks via GitHub releases.

* Themes & Multi-Language Support (i18n)
  Native Light, Dark, and System theme integration, with built-in translations for English, Polish, German, French, Japanese, Korean, Italian, and Spanish.

--------------------------------------------------------------------------------

## Screenshots

| View | Desktop (Light) | Desktop (Dark) | Mobile (Light) | Mobile (Dark) |
|---|---|---|---|---|
| Notes View | ![Notes on Desktop Light](docs/desktop_notes_light.png) | ![Notes on Desktop Dark](docs/desktop_notes_dark.png) | ![Notes on Mobile Light](docs/mobile_notes_light.png) | ![Notes on Mobile Dark](docs/mobile_notes_dark.png) |
| Admin Panel | ![Admin Panel on Desktop Light](docs/desktop_admin_light.png) | ![Admin Panel on Desktop Dark](docs/desktop_admin_dark.png) | ![Admin Panel on Mobile Light](docs/mobile_admin_light.png) | ![Admin Panel on Mobile Dark](docs/mobile_admin_dark.png) |

--------------------------------------------------------------------------------

## Recommended Installation (Docker Compose)

The easiest and recommended way to deploy Notki is using Docker Compose.

1. Download the source (or clone the pinned release) and start the locally built image:
   ```bash
   git clone --branch v0.1.6.2 --depth 1 https://github.com/shirou93/Notki.git notki
   cd notki
   docker compose up -d --build
   ```

2. Read the one-time setup token from the container log:
   ```bash
   docker compose logs notki | grep "SETUP TOKEN"
   ```

3. Open `http://localhost:8000/setup`, paste the token, and create the administrator.

> Security Warning (First-run setup):
> The setup API always requires the one-time `X-Setup-Token`, regardless of the client address. The setup page asks for that token before it can create an administrator or import a backup. Set `NOTKI_SETUP_TOKEN` to a strong value before the first start if you want to choose the token yourself. Do not expose the setup page publicly without TLS.

--------------------------------------------------------------------------------

## Command-Line Interface (CLI Options)

Notki provides administrative CLI flags for command-line management and disaster recovery:

```bash
# Create initial administrator account
python3 server.py --create-admin

# Disable 2FA for a specific user (by email or user ID)
python3 server.py --disable-2fa user@example.com

# Completely disable 2FA server-wide for all users
python3 server.py --disable-all-2fa

# Unban a specific IP address from Fail2ban
python3 server.py --unban 192.168.1.100

# Unban all banned IP addresses from Fail2ban
python3 server.py --unban-all

# Run server with custom host or port
python3 server.py --host 0.0.0.0 --port 8000
```

--------------------------------------------------------------------------------

## Alternative Installation Methods

### 1. Direct Execution (Python 3.9+)

Notki requires the pinned packages in `requirements.txt`.

```bash
git clone --branch v0.1.6.2 --depth 1 https://github.com/shirou93/Notki.git
cd Notki
python3 -m pip install --only-binary=:all: -r requirements.txt
python3 server.py
```
The application will be accessible at `http://localhost:8000`.

### 2. Native Linux Installation (Systemd)

On Linux distributions (Debian, Ubuntu, Arch, Fedora, Alpine, etc.), you can run the automated installer script:

```bash
sudo ./install.sh
```
The script creates a dedicated system user `notki`, installs the application into `/opt/notki`, and configures a systemd service.

--------------------------------------------------------------------------------

## Server Backups (Encrypted)

From the Admin Panel under Server Backups, you can manage server data:
- Backups include all user accounts, notes, labels, invitations, and system settings, but never active sessions.
- Backups are always encrypted with AES-256-GCM and use timestamped `.enc` filenames. TOTP secrets are also encrypted at rest in SQLite.
- By default the server derives the encryption key from `NOTKI_BACKUP_KEY` or from a generated file. To protect against directory dumps compromising both ciphertext and keys, it is highly recommended to supply keys via environment variables or mount a separate `NOTKI_KEY_DIR` outside the data volume.
- When creating a backup you may supply a separate `encryptionPassword`; restoring it then requires that password.
- You can download backups, restore archives on the server, upload `.enc`/`.tgz`/`.json` backups, or import one during first-run setup.
- Legacy plaintext `.json` snapshots remain importable; plaintext backup codes are re-hashed during import.

--------------------------------------------------------------------------------

## Environment Variables

| Variable | Description | Default Value |
|---|---|---|
| `NOTKI_HOST` | Network interface IP for server binding | `127.0.0.1` (`0.0.0.0` in Docker) |
| `NOTKI_PORT` | HTTP server port | `8000` |
| `NOTKI_DB_PATH` | Path to the SQLite3 database file | `./data/notki.sqlite3` |
| `NOTKI_BACKUP_DIR` | Directory for encrypted backups | `./data/backups` |
| `NOTKI_KEY_DIR` | Directory for storing generated `backup.key` and `totp.key` | `./.keys` |
| `NOTKI_BACKUP_KEY` | Master key for server-created encrypted backups | Key file in `NOTKI_KEY_DIR` |
| `NOTKI_TOTP_KEY` | Key for TOTP secrets encrypted at rest | Key file in `NOTKI_KEY_DIR` |
| `NOTKI_SETUP_TOKEN` | One-time token required by every setup/import API call | Auto-generated and printed |
| `NOTKI_TRUST_PROXY` | Proxy peers whose forwarding headers are trusted (`1`/`true`/`all` or IP/CIDR list) | Loopback only |
| `NOTKI_ALLOWED_HOSTS` | Optional allowlist for forwarded/host names | Empty |
| `NOTKI_PUBLIC_HOST` | Canonical public host (or full URL) used for links and Origin checks | Empty |
| `NOTKI_COOKIE_SECURE` | Force `Secure` + `__Host-` session cookies (`1`) or automatic (`0`/unset) | Automatic |
| `NOTKI_PUBLIC_HTTPS` | Emit HTTPS links when TLS terminates at a proxy | `0` |
| `NOTKI_ALLOW_BETA_UPDATES` | Allow installing the moving `main` tarball (not recommended) | `0` |
| `NOTKI_UPDATE_SHA256` | Expected SHA-256 of an update tarball | Empty |
| `NOTKI_UPDATE_PUBLIC_KEY` | Ed25519 public key (raw base64 or PEM) required to sign updates | Empty |
| `NOTKI_ALLOW_UNVERIFIED_UPDATES` | Allow updates without a checksum (dangerous) | `0` |

> Reverse Proxies & HTTPS (Cloudflare Tunnel, Nginx, Caddy, Traefik, NPM):
> Notki validates `Origin`/`Referer` scheme, host, and port for every mutating request, and only accepts `X-Forwarded-*` headers from peers allowed by `NOTKI_TRUST_PROXY`. Configure your proxy to overwrite (not append untrusted) forwarding headers and set `NOTKI_PUBLIC_HOST`.
>
> Security notes: see `SECURITY.md` for the 0.1.6.2 hardening changelog and deployment checklist.

--------------------------------------------------------------------------------

## License

This open-source project is distributed under the terms of the MIT License.
