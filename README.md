# Notki

A fast, lightweight, and private web-based note-taking application written in pure Python (Python 3.9+) with zero external dependencies from PyPI.

![Main notes view](docs/desktop_notes_light.png)

---

## 🚀 Key Features

- 📝 **Note Creation & Rich Formatting**: Rich text formatting (bold, italic, underline, font sizing), bulleted/numbered lists, and interactive checklists with real-time progress indicators and drag-and-drop task handles.
- 📅 **Due Dates & Daily Plan**: Schedule notes with due dates, view timeline sections (overdue, today, tomorrow, this week, later), and export events to iCalendar (`.ics`).
- 🏷️ **Labels & Flexible Organization**: Categorize with custom labels/tags, pin essential notes to the top, archive inactive items, manage trash, and personalize cards with adaptive pastel colors.
- 🤝 **Note Sharing & Collaboration**: Securely share notes with other users on your server using configurable read-only or read-write permissions.
- 📶 **Offline First & Auto-Sync**: Work seamlessly offline thanks to browser caching and background sync when connection is restored.
- 👤 **User Profiles & Avatars**: Profile customization, password management, and custom avatar upload support.
- 🔐 **Advanced Security & Authentication**:
  - Two-Factor Authentication (2FA) supporting both TOTP (Authenticator Apps) and WebAuthn Passkeys / Hardware Security Keys (FIDO2/Touch ID/Face ID).
  - Emergency 2FA recovery backup codes.
  - Option to enforce 2FA server-wide via administrative settings.
  - Rate limiting on login endpoints to prevent brute-force attempts.
- 💾 **Transparent JSON Backups**: Full server state backup, download, upload, and restore in transparent `.json` format, with backup import support during first-run setup.
- ⚙️ **Comprehensive Admin Panel**: User account management, single-use invitation link generation with custom expiration, server system stats, pinned server announcements, and direct update checks via GitHub releases.
- 🎨 **Themes & Multi-Language Support (i18n)**: Native Light, Dark, and System theme integration, with built-in translations for English, Polish, German, French, Japanese, Korean, Italian, and Spanish.

---

## 📱 Screenshots

| View | Desktop (Light) | Desktop (Dark) | Mobile (Light) | Mobile (Dark) |
|---|---|---|---|---|
| **Notes View** | ![Notes on Desktop Light](docs/desktop_notes_light.png) | ![Notes on Desktop Dark](docs/desktop_notes_dark.png) | ![Notes on Mobile Light](docs/mobile_notes_light.png) | ![Notes on Mobile Dark](docs/mobile_notes_dark.png) |
| **Admin Panel** | ![Admin Panel on Desktop Light](docs/desktop_admin_light.png) | ![Admin Panel on Desktop Dark](docs/desktop_admin_dark.png) | ![Admin Panel on Mobile Light](docs/mobile_admin_light.png) | ![Admin Panel on Mobile Dark](docs/mobile_admin_dark.png) |

---

## 🛠️ Recommended Installation (Docker Compose)

The easiest and recommended way to deploy Notki is using **Docker Compose**.

1. Create a project directory and download `docker-compose.yml`:
   ```bash
   mkdir notki && cd notki
   curl -O https://raw.githubusercontent.com/shirou93/Notki/main/docker-compose.yml
   ```

2. Start the container in background mode:
   ```bash
   docker compose up -d
   ```

3. Open your browser at `http://localhost:8000/setup` and complete the initial administrator setup.

---

## 💻 Alternative Installation Methods

### 1. Direct Execution (Python 3.9+)

Notki relies strictly on the Python standard library and requires no `pip` packages.

```bash
git clone https://github.com/shirou93/Notki.git
cd Notki
python3 server.py
```
The application will be accessible at `http://localhost:8000`.

### 2. Native Linux Installation (Systemd)

On Linux distributions (Debian, Ubuntu, Arch, Fedora, Alpine, etc.), you can run the automated installer script:

```bash
sudo ./install.sh
```
The script creates a dedicated system user `notki`, installs the application into `/opt/notki`, and configures a systemd service.

---

## 🛡️ Server Backups (JSON Backup)

From the **Admin Panel** under **Server Backups**, you can easily manage server data:
- Backups include all user accounts, notes, labels, invitations, and system settings.
- Files are saved in human-readable `.json` format with timestamped filenames (e.g., `notki-backup-20261014-120000Z-a1b2c3d4.json`).
- You can download backups, restore existing archives on the server, upload `.json` backups from your local device, or import a backup during initial first-run setup on a new server.

---

## ⚙️ Environment Variables

| Variable | Description | Default Value |
|---|---|---|
| `NOTKI_HOST` | Network interface IP for server binding | `127.0.0.1` (`0.0.0.0` in Docker) |
| `NOTKI_PORT` / `NOTKI_HTTP_PORT` | HTTP server port | `8000` |
| `NOTKI_DB_PATH` | Path to the SQLite3 database file | `./data/notki.sqlite3` |
| `NOTKI_BACKUP_DIR` | Directory path for storing JSON backups | `./data/backups` |
| `NOTKI_ALLOW_REMOTE_SETUP` | Allow first-time setup from remote IP addresses | `0` (`1` in Docker) |
| `NOTKI_TRUST_PROXY` | Trust `X-Forwarded-For` header for rate limiting (`1`/`true` or IP/CIDR list) | `0` |

> **Reverse Proxies & HTTPS (Cloudflare Tunnel, Nginx, Caddy, Traefik, NPM):**
> Notki operates natively as an HTTP server and automatically detects reverse proxy forwarding headers (`X-Forwarded-Proto`, `X-Forwarded-Host`, `X-Forwarded-Ssl`). It handles secure cookie flags and generates valid HTTPS invite links without extra SSL configuration inside the app.

---

## 📜 License

This open-source project is distributed under the terms of the MIT License.
