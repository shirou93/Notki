# Notki

A fast, lightweight, and private browser-based note-taking app built with pure Python (Python 3.9+) with zero external dependencies from PyPI.

![Main notes view](docs/desktop_notes.png)

---

## 🚀 Key Features

- 📝 **Note Creation & Editing**: Rich text formatting, bulleted and numbered lists, and interactive checklists (tasks).
- 📌 **Organization**: Pin important notes, archive, apply labels, and set colors for easy categorization.
- 🤝 **Sharing**: Securely share notes with other server users with read or edit permissions.
- 🔐 **Security**:
  - Two-Factor Authentication (2FA) via TOTP apps and Passkeys / WebAuthn security keys.
  - Mandatory 2FA enforcement for all users configurable by admins.
- 💾 **JSON Backups**: Create, download, restore, and import full server backups in `.json` format.
- ⚙️ **Admin Panel**: Manage users, invitation links (with customizable expiration duration in days), server statistics, and automatic updates directly from GitHub.
- 🎨 **Themes & Languages**: Light, dark, and system theme support, along with multi-language i18n support.

---

## 📱 Screenshots

| View | Desktop | Mobile |
|---|---|---|
| **Notes** | ![Desktop Notes](docs/desktop_notes.png) | ![Mobile Notes](docs/mobile_notes.png) |
| **Admin Panel** | ![Desktop Admin](docs/desktop_admin.png) | ![Mobile Admin](docs/mobile_admin.png) |

---

## 🛠️ Recommended Installation (Docker Compose)

The easiest and recommended way to run Notki is using **Docker Compose**.

1. Create a directory and download the `docker-compose.yml` file:
   ```bash
   mkdir notki && cd notki
   curl -O https://raw.githubusercontent.com/shirou93/Notki/main/docker-compose.yml
   ```

2. Start the container:
   ```bash
   docker compose up -d
   ```

3. Open your browser at `http://localhost:8000/setup` and create your initial administrator account.

---

## 💻 Alternative Installation Methods

### 1. Direct Execution (Python 3.9+)

The application uses the Python standard library exclusively, requiring no external `pip` packages.

```bash
git clone https://github.com/shirou93/Notki.git
cd Notki
python3 server.py
```
Open your browser at `http://localhost:8000`.

### 2. Bare-Metal Installation (Linux Systemd)

On a Linux server (Debian, Ubuntu, Arch, Fedora, Alpine), you can use the automated installer script:

```bash
sudo ./install.sh
```
The script creates a dedicated `notki` system user, installs the application in `/opt/notki`, and configures and starts a Systemd service.

---

## 🛡️ Backups (JSON)

In the Admin Panel under **Full Server Backups**, you can generate full server backups.
- Backups include accounts, notes, labels, invitations, and settings.
- Files are saved in `.json` format with filenames containing the creation date and time timestamp (e.g., `notki-backup-20261013-120000Z-a1b2c3d4.json`).
- Backups can be downloaded at any time, restored from the server list, uploaded from local disk, or imported during initial setup on a new server.

---

## ⚙️ Environment Variables

| Variable | Description | Default Value |
|---|---|---|
| `NOTKI_HOST` | IP address the server listens on | `127.0.0.1` (`0.0.0.0` in Docker) |
| `NOTKI_PORT` / `NOTKI_HTTP_PORT` | HTTP server port | `8000` |
| `NOTKI_DB_PATH` | Path to the SQLite database file | `./data/notki.sqlite3` |
| `NOTKI_BACKUP_DIR` | Path to the directory for JSON backups | `./data/backups` |
| `NOTKI_COOKIE_SECURE` | Set `Secure` flag on cookies (requires HTTPS) | `0` |
| `NOTKI_PUBLIC_HTTPS` | Generate invitation links with `https://` prefix | `0` |
| `NOTKI_ALLOW_REMOTE_SETUP` | Allow initial setup from non-localhost IP addresses | `0` (`1` in Docker) |

---

## 📜 License

Open-source project licensed under the MIT License.
