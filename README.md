# Notki

Notki is a private notes app with per-user SQLite storage, invitation-only registration, and an administrator dashboard.

## Run locally

Requires Python 3.9 or newer. The server uses only Python's standard library.

Start the server:

```powershell
python server.py
```

On a fresh database, open the local address printed by the server. Notki automatically opens the first-run administrator form. Create an account with a password of at least 12 characters; the new administrator is signed in immediately. This setup page is only accessible from the local machine and can be used only once.

After setup, the same address opens the notes app. Sign in with the administrator account, then choose **Panel administracyjny** to create registration links. Each invitation works once and expires after seven days. New accounts can only be created through a valid invitation.

From **Backupy całego serwera**, an administrator can create timestamped `.tgz` backups stored on the server in `data/backups`. Each archive contains all accounts, password hashes, notes, and invitations; active sessions are excluded. Keep backups private because they contain password hashes. The admin panel can list, download, restore, and delete individual archives. Restoring replaces the current server data and logs everyone out.

On a fresh server, select a `.tgz` backup on the first-run setup page and import it before creating an administrator. Then sign in with an account from the backup. The legacy JSON snapshot import remains supported.

The first administrator can also be created from a terminal with `python server.py --create-admin` before starting the server.

The SQLite database is stored at `data/notki.sqlite3`. Existing browser-only notes are offered for migration the first time an account with no server notes signs in.

## Uruchomienie na Linuksie

Wymagany jest Python 3.9 lub nowszy. SQLite i pozostałe zależności są w bibliotece standardowej, więc nie trzeba instalować pakietów przez `pip`.

Na Ubuntu lub Debianie:

```sh
sudo apt update
sudo apt install python3
git clone <adres-repozytorium> Notki
cd Notki
python3 --version
python3 server.py
```

Serwer domyślnie nasłuchuje tylko na `127.0.0.1:8000`. Na tej samej maszynie otwórz `http://127.0.0.1:8000`. Przy pierwszym uruchomieniu pojawi się formularz utworzenia administratora.

Jeśli serwer działa na innej maszynie, pozostaw go związanym z `127.0.0.1` i zestaw tunel SSH ze swojego komputera:

```sh
ssh -L 8000:127.0.0.1:8000 <użytkownik>@<adres-serwera>
```

Podczas działania tunelu otwórz lokalnie `http://127.0.0.1:8000`. Tunel pozwala przejść pierwszą konfigurację administratora bez wystawiania formularza na publiczny interfejs.

### Stała usługa systemd

Dla serwera dostępnego przez domenę uruchom Notki za reverse proxy z TLS, a nie bezpośrednio publicznym HTTP. Przykład zakłada kod w `/opt/notki`, konto systemowe `notki` i proxy przekazujące ruch do `127.0.0.1:8000`.

```sh
sudo useradd --system --home-dir /opt/notki --shell /usr/sbin/nologin notki
sudo install -d -o notki -g notki /opt/notki/data
sudo -u notki python3 /opt/notki/server.py --create-admin
```

Zapisz poniższą jednostkę jako `/etc/systemd/system/notki.service`:

```ini
[Unit]
Description=Notki private notes app
After=network.target

[Service]
Type=simple
User=notki
Group=notki
WorkingDirectory=/opt/notki
Environment=NOTKI_HOST=127.0.0.1
Environment=NOTKI_PORT=8000
Environment=NOTKI_COOKIE_SECURE=1
Environment=NOTKI_PUBLIC_HTTPS=1
ExecStart=/usr/bin/python3 /opt/notki/server.py
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/notki/data

[Install]
WantedBy=multi-user.target
```

Włącz usługę i sprawdź logi:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now notki
sudo systemctl status notki
journalctl -u notki -f
```

Plik SQLite oraz archiwa backupów będą w `/opt/notki/data`. Nie udostępniaj tego katalogu publicznie; snapshoty `.tgz` zawierają hashe haseł.

## Configuration

- `NOTKI_HOST`: bind address; defaults to `127.0.0.1`.
- `NOTKI_PORT`: HTTP port; defaults to `8000`.
- `NOTKI_DB_PATH`: optional SQLite database path.
- `NOTKI_BACKUP_DIR`: optional directory for server backup archives; defaults to `backups` beside the database.
- `NOTKI_COOKIE_SECURE=1`: mark session cookies Secure when served through HTTPS.
- `NOTKI_PUBLIC_HTTPS=1`: generate HTTPS invitation URLs when TLS terminates in a reverse proxy.

The built-in HTTP server is intended for local use. For remote access, put it behind a TLS-enabled reverse proxy and set the secure-cookie options above.
