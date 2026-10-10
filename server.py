import argparse
import hashlib
import hmac
import ipaddress
import io
import json
import math
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import tarfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
import urllib.request


ROOT = Path(__file__).resolve().parent
VERSION = '0.1.4.1'
DB_PATH = Path(os.environ.get('NOTKI_DB_PATH', ROOT / 'data' / 'notki.sqlite3'))
SESSION_COOKIE = 'notki_session'
SESSION_DAYS = 30
INVITE_DAYS = 7
PASSWORD_ITERATIONS = 310_000
MAX_REQUEST_BYTES = 3 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024
BACKUP_FILENAME_PATTERN = re.compile(r'^notki-server-\d{8}-\d{6}Z-[a-f0-9]{8}\.tgz$')
NOTE_COLORS = {'default', 'mint', 'lemon', 'peach', 'lilac', 'sky'}
AVATAR_PATTERN = re.compile(r'^data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}$')
MAX_AVATAR_CHARS = 2_900_000
STATIC_FILES = {
    'manifest.json', 'index.html', 'app.js', 'i18n.js', 'theme.js', 'setup.html', 'setup.js', 'styles.css'}
TRANSLATION_FILES = {'translations/pl.js', 'translations/en.js'}
DEFAULT_LANGUAGE = 'en'
SUPPORTED_LANGUAGES = ('pl', 'en')

# Polish messages are the source strings; this catalog provides their English counterparts.
ENGLISH_MESSAGES = {
    'Podaj poprawny adres e-mail.': 'Enter a valid e-mail address.',
    'Hasło musi mieć co najmniej 12 znaków.': 'The password must be at least 12 characters long.',
    'Hasło jest zbyt długie.': 'The password is too long.',
    'Podane hasła nie są takie same.': 'The passwords do not match.',
    'Nieprawidłowy rozmiar żądania.': 'Invalid request size.',
    'Żądanie jest zbyt duże.': 'The request is too large.',
    'Oczekiwano danych JSON.': 'JSON data was expected.',
    'Oczekiwano archiwum .tgz.': 'A .tgz archive was expected.',
    'Nieprawidłowy format JSON.': 'Invalid JSON format.',
    'Nieprawidłowe dane żądania.': 'Invalid request data.',
    'Żądanie z innej domeny zostało zablokowane.': 'A cross-origin request was blocked.',
    'Zaloguj się, aby kontynuować.': 'Sign in to continue.',
    'Ta sekcja jest dostępna tylko dla administratora.': 'This section is available only to the administrator.',
    'Pierwszą konfigurację można wykonać wyłącznie lokalnie.': 'The first-time setup can only be completed locally.',
    'Pierwsza konfiguracja administratora wymaga dostępu lokalnego.': 'Creating the first administrator requires local access.',
    'Nie znaleziono endpointu.': 'Endpoint not found.',
    'Nie znaleziono strony.': 'Page not found.',
    'Nie znaleziono pliku.': 'File not found.',
    'Konto administratora zostało już utworzone.': 'The administrator account has already been created.',
    'Konto z tym adresem e-mail już istnieje.': 'An account with this e-mail address already exists.',
    'Nieprawidłowy e-mail lub hasło.': 'Invalid e-mail or password.',
    'Aktualne hasło jest nieprawidłowe.': 'The current password is incorrect.',
    'Rejestracja wymaga ważnego zaproszenia.': 'Registration requires a valid invitation.',
    'Zaproszenie jest nieprawidłowe lub wygasło.': 'The invitation is invalid or has expired.',
    'Snapshot przekracza limit 100 MB.': 'The snapshot exceeds the 100 MB limit.',
    'Nie udało się zapisać backupu na serwerze.': 'Could not save the backup on the server.',
    'Nie znaleziono backupu.': 'Backup not found.',
    'Plik backupu przekracza limit rozmiaru.': 'The backup file exceeds the size limit.',
    'Nie można odczytać archiwum backupu.': 'The backup archive cannot be read.',
    'Archiwum backupu ma nieprawidłową zawartość.': 'The backup archive has invalid contents.',
    'Nie można odczytać snapshotu z archiwum.': 'The snapshot cannot be read from the archive.',
    'Import snapshotu jest dostępny tylko lokalnie.': 'Snapshot import is available only locally.',
    'Plik nie jest prawidłowym snapshotem serwera Notki.': 'The file is not a valid Notki server snapshot.',
    'Snapshot nie zawiera kompletnej listy kont, notatek i zaproszeń.': 'The snapshot does not contain a complete list of accounts, notes, and invitations.',
    'Snapshot jest pusty lub przekracza limit danych.': 'The snapshot is empty or exceeds the data limit.',
    'Nieprawidłowe konto w snapshocie.': 'Invalid account in the snapshot.',
    'Nieprawidłowy identyfikator konta w snapshocie.': 'Invalid account identifier in the snapshot.',
    'Nieprawidłowy adres lub rola konta w snapshocie.': 'Invalid account address or role in the snapshot.',
    'Snapshot zawiera nieprawidłowy hash hasła.': 'The snapshot contains an invalid password hash.',
    'Snapshot zawiera nieprawidłowy avatar.': 'The snapshot contains an invalid avatar.',
    'Avatar jest zbyt duży.': 'The avatar is too large.',
    'Avatar musi być obrazem PNG, JPEG, WebP lub GIF.': 'The avatar must be a PNG, JPEG, WebP, or GIF image.',
    'Snapshot musi zawierać konto administratora.': 'The snapshot must contain an administrator account.',
    'Nieprawidłowa notatka w snapshocie.': 'Invalid note in the snapshot.',
    'Nieprawidłowa notatka lub właściciel w snapshocie.': 'Invalid note or owner in the snapshot.',
    'Notatka w snapshocie przekracza limit rozmiaru.': 'A note in the snapshot exceeds the size limit.',
    'Nieprawidłowa kolejność notatek w snapshocie.': 'Invalid note order in the snapshot.',
    'Nieprawidłowe zaproszenie w snapshocie.': 'Invalid invitation in the snapshot.',
    'Nieprawidłowy hash zaproszenia w snapshocie.': 'Invalid invitation hash in the snapshot.',
    'Nieprawidłowe zaproszenie lub administrator w snapshocie.': 'Invalid invitation or administrator in the snapshot.',
    'Import jest możliwy tylko do całkowicie pustej bazy danych.': 'Import is possible only into a completely empty database.',
    'Snapshot zawiera nieprawidłową datę.': 'The snapshot contains an invalid date.',
    'Snapshot zawiera datę bez strefy czasowej.': 'The snapshot contains a date without a time zone.',
    'Nieprawidłowa lista notatek.': 'Invalid note list.',
    'Nieprawidłowa notatka.': 'Invalid note.',
    'Dane notatki są nieprawidłowe lub zbyt duże.': 'The note data is invalid or too large.',
    'Nieprawidłowa kolejność notatek.': 'Invalid note order.',
    'Nie znaleziono notatki.': 'Note not found.',
    'Nie możesz udostępnić notatki samemu sobie.': 'You cannot share a note with yourself.',
    'Nie znaleziono użytkownika o tym adresie e-mail.': 'No user with that e-mail address was found.',
    'Nieprawidłowy poziom uprawnień.': 'Invalid permission level.',
    'Ta notatka nie jest już udostępniona temu użytkownikowi.': 'This note is no longer shared with that user.',
    'Nie masz uprawnień do edycji tej notatki.': 'You do not have permission to edit this note.',
    'Nie możesz zmieniać uprawnień notatki, której nie jesteś właścicielem.': 'You cannot change permissions of a note you do not own.',
    'Brak nowszej wersji.': 'No newer version available.',
    'Nie udało się pobrać informacji o aktualizacji.': 'Could not fetch update information.',
    'Brak adresu tarball w odpowiedzi.': 'No tarball address in response.',
    'Wystąpił błąd podczas pobierania archiwum.': 'An error occurred while downloading the archive.',
    'Nie udało się wyodrębnić plików.': 'Could not extract files.',
    'Nieprawidłowy adres pobierania.': 'Invalid download URL.',
}


def parse_version(version_str):
    return tuple(int(x) for x in re.findall(r'\d+', str(version_str)))


def parse_language(header_value):
    """Pick the highest-priority supported language from an Accept-Language header."""
    best = None
    for index, chunk in enumerate(str(header_value or '').split(',')):
        parts = chunk.split(';')
        tag = parts[0].strip().lower()
        if not tag:
            continue
        quality = 1.0
        for parameter in parts[1:]:
            name, _, value = parameter.partition('=')
            if name.strip().lower() == 'q':
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
        if quality <= 0 or tag == '*':
            continue
        language = tag.split('-', 1)[0]
        if language not in SUPPORTED_LANGUAGES:
            continue
        if best is None or quality > best[0]:
            best = (quality, index, language)
    return best[2] if best else DEFAULT_LANGUAGE


def translate_message(message, language):
    if language == 'en':
        return ENGLISH_MESSAGES.get(message, message)
    return message


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_time(value=None):
    return (value or utc_now()).isoformat()


def backup_directory():
    return Path(os.environ.get('NOTKI_BACKUP_DIR') or DB_PATH.parent / 'backups')


def token_hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute('PRAGMA busy_timeout = 10000')
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database():
    with database() as connection:
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
                created_at TEXT NOT NULL,
                avatar TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS invites (
                token_hash TEXT PRIMARY KEY,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT
            );
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                body_format INTEGER NOT NULL DEFAULT 0,
                color TEXT NOT NULL DEFAULT 'default',
                tags_json TEXT NOT NULL DEFAULT '[]',
                pinned INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sort_order REAL NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS notes_user_idx ON notes(user_id);
            CREATE TABLE IF NOT EXISTS note_shares (
                note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                permission TEXT NOT NULL DEFAULT 'read' CHECK (permission IN ('read', 'write')),
                created_at TEXT NOT NULL,
                PRIMARY KEY (note_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS note_shares_user_idx ON note_shares(user_id);
        ''')
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(users)')}
        if 'avatar' not in columns:
            connection.execute('ALTER TABLE users ADD COLUMN avatar TEXT')
        if 'labels_json' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN labels_json TEXT NOT NULL DEFAULT '[]'")


def hash_password(password):
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PASSWORD_ITERATIONS)
    return f'pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${derived.hex()}'


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt_hex, expected_hex = encoded.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def normalize_email(value):
    email = str(value or '').strip().lower()
    if len(email) > 254 or email.count('@') != 1:
        raise ValueError('Podaj poprawny adres e-mail.')
    local, domain = email.split('@')
    if not local or not domain or '.' not in domain or any(character.isspace() for character in email):
        raise ValueError('Podaj poprawny adres e-mail.')
    return email


def public_user(row):
    keys = row.keys()
    labels = []
    if 'labels_json' in keys and row['labels_json']:
        try:
            labels = json.loads(row['labels_json'])
        except json.JSONDecodeError:
            pass
    return {
        'id': row['id'], 'email': row['email'], 'isAdmin': row['role'] == 'admin',
        'createdAt': row['created_at'], 'avatar': row['avatar'] if 'avatar' in keys else None,
        'labels': labels
    }


def create_admin_account():
    initialize_database()
    with database() as connection:
        if connection.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone():
            print('Administrator już istnieje.')
            return
    try:
        email = normalize_email(input('E-mail administratora: '))
        import getpass
        password = getpass.getpass('Hasło (minimum 12 znaków): ')
        confirmation = getpass.getpass('Powtórz hasło: ')
        if len(password) < 12:
            raise ValueError('Hasło musi mieć co najmniej 12 znaków.')
        if password != confirmation:
            raise ValueError('Podane hasła nie są takie same.')
        with database() as connection:
            connection.execute(
                'INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)',
                (email, hash_password(password), 'admin', iso_time()),
            )
        print(f'Konto administratora {email} zostało utworzone.')
    except (ValueError, sqlite3.IntegrityError) as error:
        print(f'Nie udało się utworzyć administratora: {error}', file=sys.stderr)
        raise SystemExit(1) from error


class APIError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


import subprocess

def aes_encrypt(data, password_str):
    proc = subprocess.run(
        ['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-pass', f'pass:{password_str}'],
        input=data,
        capture_output=True,
        check=True
    )
    return proc.stdout

def aes_decrypt(data, password_str):
    proc = subprocess.run(
        ['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-pass', f'pass:{password_str}'],
        input=data,
        capture_output=True,
        check=True
    )
    return proc.stdout


class NotkiHandler(BaseHTTPRequestHandler):
    server_version = f'NotkiServer/{VERSION}'

    @property
    def language(self):
        return parse_language(self.headers.get('Accept-Language'))

    def error_message(self, message):
        return translate_message(message, self.language)

    def send_error_json(self, message, status=400):
        self.send_json({'error': self.error_message(message)}, status)

    def send_json(self, payload, status=200, extra_headers=()):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def read_body(self, max_bytes=MAX_REQUEST_BYTES):
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError as error:
            raise APIError('Nieprawidłowy rozmiar żądania.') from error
        if length < 0 or length > max_bytes:
            raise APIError('Żądanie jest zbyt duże.', 413)
        return self.rfile.read(length)

    def read_json(self, max_bytes=MAX_REQUEST_BYTES):
        if 'application/json' not in self.headers.get('Content-Type', ''):
            raise APIError('Oczekiwano danych JSON.', 415)
        body = self.read_body(max_bytes)
        if not body:
            return {}
        try:
            value = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise APIError('Nieprawidłowy format JSON.') from error
        if not isinstance(value, dict):
            raise APIError('Nieprawidłowe dane żądania.')
        return value

    def check_origin(self):
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            raise APIError('Żądanie z innej domeny zostało zablokowane.', 403)

    def has_admin(self):
        with database() as connection:
            return connection.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone() is not None

    def is_local_setup_request(self):
        if os.environ.get('NOTKI_ALLOW_REMOTE_SETUP') == '1':
            return True
        try:
            remote_ip = ipaddress.ip_address(self.client_address[0].split('%', 1)[0])
        except ValueError:
            return False
        host = urlsplit(f"//{self.headers.get('Host', '')}").hostname or ''
        return remote_ip.is_loopback and host.lower() in {'localhost', '127.0.0.1', '::1'}

    def send_redirect(self, path):
        self.send_response(302)
        self.send_header('Location', path)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

    def current_user(self):
        cookie = cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            token = cookie[SESSION_COOKIE].value
        except (cookies.CookieError, KeyError):
            return None
        with database() as connection:
            row = connection.execute('''
                SELECT users.id, users.email, users.role, users.created_at, users.avatar, users.labels_json
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            ''', (token_hash(token), iso_time())).fetchone()
            return public_user(row) if row else None

    def require_user(self, admin=False):
        user = self.current_user()
        if not user:
            raise APIError('Zaloguj się, aby kontynuować.', 401)
        if admin and not user['isAdmin']:
            raise APIError('Ta sekcja jest dostępna tylko dla administratora.', 403)
        return user

    def session_headers(self, token, max_age=SESSION_DAYS * 24 * 60 * 60):
        secure = '; Secure' if os.environ.get('NOTKI_COOKIE_SECURE') == '1' else ''
        return [('Set-Cookie', f'{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}')]

    def new_session(self, user_id):
        token = secrets.token_urlsafe(32)
        with database() as connection:
            connection.execute('DELETE FROM sessions WHERE expires_at <= ?', (iso_time(),))
            connection.execute(
                'INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)',
                (token_hash(token), user_id, iso_time(utc_now() + timedelta(days=SESSION_DAYS))),
            )
        return token

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        try:
            if path == '/api/setup/status':
                self.send_json({'needsSetup': not self.has_admin()})
            elif path in ('/setup', '/setup.html'):
                if self.has_admin():
                    self.send_redirect('/')
                elif not self.is_local_setup_request():
                    self.send_error_json('Pierwszą konfigurację można wykonać wyłącznie lokalnie.', 403)
                else:
                    self.serve_static('setup.html')
            elif path == '/api/session':
                self.send_json({'user': self.current_user()})
            elif path == '/api/notes':
                user = self.require_user()
                with database() as connection:
                    rows = connection.execute('SELECT * FROM notes WHERE user_id = ? ORDER BY sort_order DESC', (user['id'],)).fetchall()
                self.send_json({'notes': [self.note_from_row(row) for row in rows]})
            elif path == '/api/shared':
                user = self.require_user()
                self.send_json({'notes': self.shared_notes(user['id'])})
            elif path == '/api/users':
                user = self.require_user()
                self.send_json({'users': self.directory(user['id'])})
            elif path.startswith('/api/notes/') and path.endswith('/shares'):
                user = self.require_user()
                note_id = path[len('/api/notes/'):-len('/shares')]
                self.send_json({'shares': self.list_shares(user, note_id)})
            elif path == '/api/admin/summary':
                self.require_user(admin=True)
                with database() as connection:
                    stats = connection.execute('''
                        SELECT
                            (SELECT COUNT(*) FROM users) AS users,
                            COUNT(*) AS notes,
                            SUM(CASE WHEN deleted = 0 AND archived = 0 THEN 1 ELSE 0 END) AS active,
                            SUM(CASE WHEN deleted = 0 AND archived = 1 THEN 1 ELSE 0 END) AS archived,
                            SUM(CASE WHEN deleted = 1 THEN 1 ELSE 0 END) AS trash
                        FROM notes
                    ''').fetchone()
                    users = connection.execute('''
                        SELECT users.id, users.email, users.role, users.created_at, COUNT(notes.id) AS note_count
                        FROM users LEFT JOIN notes ON notes.user_id = users.id
                        GROUP BY users.id ORDER BY users.created_at DESC
                    ''').fetchall()
                    invites = connection.execute('''
                        SELECT created_at, expires_at, used_at FROM invites ORDER BY created_at DESC LIMIT 30
                    ''').fetchall()
                    pending = connection.execute(
                        'SELECT COUNT(*) FROM invites WHERE used_at IS NULL AND expires_at > ?', (iso_time(),)
                    ).fetchone()[0]
                self.send_json({
                    'stats': {key: stats[key] or 0 for key in ('users', 'notes', 'active', 'archived', 'trash')}
                              | {'pendingInvites': pending},
                    'users': [{'id': row['id'], 'email': row['email'], 'role': row['role'], 'createdAt': row['created_at'], 'notes': row['note_count']} for row in users],
                    'invites': [{'createdAt': row['created_at'], 'expiresAt': row['expires_at'], 'usedAt': row['used_at']} for row in invites],
                })
            elif path == '/api/admin/backups':
                self.list_server_backups()
            elif path.startswith('/api/admin/backups/'):
                filename = path.removeprefix('/api/admin/backups/')
                self.download_server_backup(filename)
            elif path == '/api/admin/update/check':
                self.check_update()
            elif path in ('/', '/index.html', '/admin', '/admin.html') or path.lstrip('/') in STATIC_FILES or path.lstrip('/') in TRANSLATION_FILES:
                if path in ('/', '/index.html') and not self.has_admin():
                    if not self.is_local_setup_request():
                        self.send_error_json('Pierwsza konfiguracja administratora wymaga dostępu lokalnego.', 403)
                        return
                    self.send_redirect('/setup')
                    return
                filename = 'index.html' if path in ('/', '/admin', '/admin.html') else path.lstrip('/')
                self.serve_static(filename)
            elif path.startswith('/api/'):
                self.send_error_json('Nie znaleziono endpointu.', 404)
            else:
                self.send_error_json('Nie znaleziono strony.', 404)
        except APIError as error:
            self.send_error_json(str(error), error.status)
        except ValueError as error:
            self.send_error_json(str(error), 400)

    def do_POST(self):
        try:
            self.check_origin()
            path = urlsplit(self.path).path
            if path == '/api/setup/import-backup':
                # Since setup.js sends FormData, we must read the multipart request
                import cgi
                ctype, pdict = cgi.parse_header(self.headers.get('Content-Type'))
                if ctype == 'multipart/form-data':
                    pdict['boundary'] = bytes(pdict['boundary'], 'utf-8')
                    pdict['CONTENT-LENGTH'] = int(self.headers.get('Content-Length', 0))
                    fields = cgi.parse_multipart(self.rfile, pdict)
                    archive_bytes = fields.get('archive', [b''])[0]
                    password = fields.get('password', [b''])[0].decode('utf-8')
                    if not archive_bytes:
                        raise APIError('Brak archiwum w żądaniu.', 400)
                    if len(archive_bytes) > MAX_SNAPSHOT_BYTES:
                        raise APIError('Plik backupu przekracza limit rozmiaru.', 413)
                    self.import_snapshot_archive(archive_bytes, password if password else None)
                else:
                    if ctype not in ('application/gzip', 'application/x-gzip'):
                        raise APIError('Oczekiwano archiwum .tgz lub multipart/form-data.', 415)
                    self.import_snapshot_archive(self.read_body(MAX_SNAPSHOT_BYTES))
                return
            payload = self.read_json(MAX_SNAPSHOT_BYTES if path == '/api/setup/import' else MAX_REQUEST_BYTES)
            if path == '/api/login':
                self.login(payload)
            elif path == '/api/setup/admin':
                self.create_first_admin(payload)
            elif path == '/api/setup/import':
                self.import_snapshot(payload)
            elif path == '/api/register':
                self.register(payload)
            elif path == '/api/logout':
                self.logout()
            elif path == '/api/account/password':
                self.change_password(payload)
            elif path == '/api/account/avatar':
                self.change_avatar(payload)
            elif path == '/api/account/labels':
                self.change_labels(payload)
            elif path.startswith('/api/notes/') and path.endswith('/shares'):
                user = self.require_user()
                note_id = path[len('/api/notes/'):-len('/shares')]
                self.create_share(user, note_id, payload)
            elif path == '/api/admin/invites':
                self.create_invite()
            elif path == '/api/admin/backups':
                self.create_server_backup(payload)
            elif path.startswith('/api/admin/backups/'):
                match = re.fullmatch(r'/api/admin/backups/([^/]+)/restore', path)
                if not match:
                    self.send_error_json('Nie znaleziono endpointu.', 404)
                else:
                    self.restore_server_backup(match.group(1), payload)
            elif path == '/api/admin/update/perform':
                self.perform_update(payload)
            else:
                self.send_error_json('Nie znaleziono endpointu.', 404)
        except APIError as error:
            self.send_error_json(str(error), error.status)
        except ValueError as error:
            self.send_error_json(str(error), 400)

    def do_DELETE(self):
        try:
            self.check_origin()
            path = unquote(urlsplit(self.path).path)
            share_match = re.fullmatch(r'/api/notes/([^/]+)/shares/(\d+)', path)
            if share_match:
                user = self.require_user()
                self.delete_share(user, share_match.group(1), int(share_match.group(2)))
                return
            match = re.fullmatch(r'/api/admin/backups/([^/]+)', path)
            if match:
                self.delete_server_backup(match.group(1))
                return
            user_match = re.fullmatch(r'/api/admin/users/(\d+)', path)
            if user_match:
                self.delete_user(int(user_match.group(1)))
                return
            self.send_error_json('Nie znaleziono endpointu.', 404)
        except APIError as error:
            self.send_error_json(str(error), error.status)

    def create_first_admin(self, payload):
        if not self.is_local_setup_request():
            raise APIError('Pierwszą konfigurację można wykonać wyłącznie lokalnie.', 403)
        email = normalize_email(payload.get('email'))
        password = str(payload.get('password') or '')
        if len(password) < 12:
            raise APIError('Hasło musi mieć co najmniej 12 znaków.')
        if len(password) > 1024:
            raise APIError('Hasło jest zbyt długie.')
        now = iso_time()
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone():
                raise APIError('Konto administratora zostało już utworzone.', 409)
            try:
                cursor = connection.execute(
                    'INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)',
                    (email, hash_password(password), 'admin', now),
                )
            except sqlite3.IntegrityError as error:
                raise APIError('Konto z tym adresem e-mail już istnieje.', 409) from error
            user_id = cursor.lastrowid
        token = self.new_session(user_id)
        with database() as connection:
            user = connection.execute('SELECT id, email, role, created_at, avatar, labels_json FROM users WHERE id = ?', (user_id,)).fetchone()
        self.send_json({'user': public_user(user)}, 201, self.session_headers(token))

    def build_snapshot(self):
        with database() as connection:
            connection.execute('BEGIN')
            users = connection.execute('SELECT id, email, password_hash, role, created_at, avatar, labels_json FROM users ORDER BY id').fetchall()
            notes = connection.execute('SELECT * FROM notes ORDER BY user_id, sort_order DESC').fetchall()
            invites = connection.execute('SELECT * FROM invites ORDER BY created_at').fetchall()
            shares = connection.execute('SELECT * FROM note_shares ORDER BY note_id, user_id').fetchall()
        snapshot = {
            'format': 'notki-server-snapshot',
            'version': 1,
            'createdAt': iso_time(),
            'users': [
                {'id': row['id'], 'email': row['email'], 'passwordHash': row['password_hash'], 'role': row['role'],
                 'createdAt': row['created_at'], 'avatar': row['avatar'],
                 'labels': json.loads(row['labels_json']) if 'labels_json' in row.keys() and row['labels_json'] else []}
                for row in users
            ],
            'notes': [
                {'id': row['id'], 'userId': row['user_id'], 'title': row['title'], 'body': row['body'],
                 'bodyFormat': row['body_format'], 'color': row['color'], 'tags': json.loads(row['tags_json']),
                 'pinned': bool(row['pinned']), 'archived': bool(row['archived']), 'deleted': bool(row['deleted']),
                 'createdAt': row['created_at'], 'updatedAt': row['updated_at'], 'order': row['sort_order']}
                for row in notes
            ],
            'invites': [
                {'tokenHash': row['token_hash'], 'createdBy': row['created_by'], 'createdAt': row['created_at'],
                 'expiresAt': row['expires_at'], 'usedAt': row['used_at']}
                for row in invites
            ],
            'shares': [
                {'noteId': row['note_id'], 'userId': row['user_id'], 'permission': row['permission'],
                 'createdAt': row['created_at']}
                for row in shares
            ],
        }
        return snapshot

    def create_server_backup(self, payload=None):
        payload = payload or {}
        password = payload.get('password')
        self.require_user(admin=True)
        created_at = utc_now()
        snapshot_bytes = json.dumps(self.build_snapshot(), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(snapshot_bytes) > MAX_SNAPSHOT_BYTES:
            raise APIError('Snapshot przekracza limit 100 MB.', 413)
        archive_buffer = io.BytesIO()
        with tarfile.open(fileobj=archive_buffer, mode='w:gz') as archive:
            member = tarfile.TarInfo('snapshot.json')
            member.size = len(snapshot_bytes)
            member.mtime = int(created_at.timestamp())
            member.mode = 0o600
            archive.addfile(member, io.BytesIO(snapshot_bytes))

        backup_bytes = archive_buffer.getvalue()
        if password:
            backup_bytes = aes_encrypt(backup_bytes, password)

        backup_dir = backup_directory()
        backup_dir.mkdir(parents=True, exist_ok=True)
        filename = f"notki-server-{created_at.strftime('%Y%m%d-%H%M%SZ')}-{secrets.token_hex(4)}.tgz"
        backup_path = backup_dir / filename
        temporary_path = backup_dir / f'.{secrets.token_hex(16)}.tmp'
        try:
            with temporary_path.open('xb') as stream:
                stream.write(backup_bytes)
            os.replace(temporary_path, backup_path)
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            raise APIError('Nie udało się zapisać backupu na serwerze.', 500) from error
        self.send_json({'filename': filename, 'createdAt': iso_time(created_at), 'sizeBytes': backup_path.stat().st_size}, 201)

    def list_server_backups(self):
        self.require_user(admin=True)
        backup_dir = backup_directory()
        if not backup_dir.exists():
            self.send_json({'backups': []})
            return
        backups = []
        for path in backup_dir.iterdir():
            if not BACKUP_FILENAME_PATTERN.fullmatch(path.name) or path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            backups.append({
                'filename': path.name,
                'createdAt': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                'sizeBytes': stat.st_size,
            })
        backups.sort(key=lambda backup: backup['createdAt'], reverse=True)
        self.send_json({'backups': backups})

    def find_server_backup(self, filename):
        if not BACKUP_FILENAME_PATTERN.fullmatch(filename):
            raise APIError('Nie znaleziono backupu.', 404)
        path = backup_directory() / filename
        if path.is_symlink() or not path.is_file():
            raise APIError('Nie znaleziono backupu.', 404)
        return path

    def download_server_backup(self, filename):
        self.require_user(admin=True)
        path = self.find_server_backup(filename)
        size = path.stat().st_size
        if size > MAX_SNAPSHOT_BYTES:
            raise APIError('Plik backupu przekracza limit rozmiaru.', 413)
        data = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'application/gzip')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Content-Disposition', f'attachment; filename="{path.name}"')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def delete_server_backup(self, filename):
        self.require_user(admin=True)
        path = self.find_server_backup(filename)
        path.unlink()
        self.send_json({'deleted': filename})

    def delete_user(self, user_id):
        admin = self.require_user(admin=True)
        if admin['id'] == user_id:
            raise APIError('Nie możesz usunąć własnego konta z panelu administratora.', 400)
        with database() as connection:
            row = connection.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
            if not row:
                raise APIError('Nie znaleziono użytkownika.', 404)
            connection.execute('DELETE FROM users WHERE id = ?', (user_id,))
        self.send_json({'deleted': user_id})

    def restore_server_backup(self, filename, payload=None):
        payload = payload or {}
        self.require_user(admin=True)
        path = self.find_server_backup(filename)
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise APIError('Plik backupu przekracza limit rozmiaru.', 413)
        try:
            archive_bytes = path.read_bytes()
            password = payload.get('password')
            if password:
                archive_bytes = aes_decrypt(archive_bytes, password)
            snapshot = self.snapshot_from_archive(archive_bytes)
        except OSError as error:
            raise APIError('Nie można odczytać archiwum backupu.') from error
        self.restore_snapshot(snapshot, replace_existing=True)

    def check_update(self):
        self.require_user(admin=True)
        req = urllib.request.Request('https://api.github.com/repos/shirou93/Notki/tags')
        req.add_header('User-Agent', 'Notki-App')
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                tags = json.loads(response.read().decode('utf-8'))
                if not tags:
                    self.send_json({'updateAvailable': False, 'currentVersion': VERSION})
                    return

                valid_tags = [t for t in tags if re.match(r'^[0-9.]+$', t.get('name', ''))]
                if not valid_tags:
                    self.send_json({'updateAvailable': False, 'currentVersion': VERSION})
                    return
                latest_tag = max(valid_tags, key=lambda t: parse_version(t.get('name', '')))
                latest_version = latest_tag.get('name', '').lstrip('v')

                if latest_version and parse_version(latest_version) > parse_version(VERSION):
                    self.send_json({'updateAvailable': True, 'latestVersion': latest_version, 'tarballUrl': latest_tag.get('tarball_url')})
                else:
                    self.send_json({'updateAvailable': False, 'currentVersion': VERSION})
        except Exception:
            raise APIError('Nie udało się pobrać informacji o aktualizacji.', 500)

    def perform_update(self, payload):
        self.require_user(admin=True)
        tarball_url = payload.get('tarballUrl')
        if not tarball_url:
            raise APIError('Brak adresu tarball w odpowiedzi.', 400)
        if not tarball_url.startswith('https://api.github.com/repos/shirou93/Notki/tarball/'):
            raise APIError('Nieprawidłowy URL aktualizacji.', 400)


        # Verify it's a valid Github API tarball URL for the project
        if not tarball_url.startswith('https://api.github.com/repos/shirou93/Notki/tarball/'):
            raise APIError('Nieprawidłowy adres pobierania.', 400)

        req = urllib.request.Request(tarball_url)
        req.add_header('User-Agent', 'Notki-App')
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                archive_bytes = response.read()
        except Exception:
            raise APIError('Wystąpił błąd podczas pobierania archiwum.', 500)

        try:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode='r:gz') as archive:
                members = archive.getmembers()
                if not members:
                    raise ValueError("Empty archive")

                server_member = None
                for member in members:
                    parts = member.name.split('/', 1)
                    rel_name = parts[1] if len(parts) > 1 else member.name
                    if rel_name == 'server.py':
                        server_member = member
                        break

                if server_member:
                    extracted_file = archive.extractfile(server_member)
                    if extracted_file:
                        content = extracted_file.read().decode('utf-8', errors='ignore')
                        match = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)['\"]", content, re.MULTILINE)
                        if match:
                            new_version = match.group(1)
                            if parse_version(new_version) <= parse_version(VERSION):
                                raise APIError('Brak nowszej wersji.', 400)

                for member in members:
                    parts = member.name.split('/', 1)
                    if len(parts) > 1:
                        member.name = parts[1]
                        target_path = (ROOT / member.name).resolve()
                        if target_path.is_relative_to(ROOT):
                            archive.extract(member, path=ROOT)
        except APIError:
            raise
        except Exception:
            raise APIError('Nie udało się wyodrębnić plików.', 500)

        threading.Timer(1.0, lambda: os._exit(0)).start()
        self.send_json({'success': True})

    def import_snapshot_archive(self, archive_bytes, password=None):
        if not self.is_local_setup_request():
            raise APIError('Import snapshotu jest dostępny tylko lokalnie.', 403)
        if password:
            archive_bytes = aes_decrypt(archive_bytes, password)
        self.restore_snapshot(self.snapshot_from_archive(archive_bytes), replace_existing=False)

    @staticmethod
    def snapshot_from_archive(archive_bytes):
        try:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode='r:gz') as archive:
                members = archive.getmembers()
                if len(members) != 1 or members[0].name != 'snapshot.json' or not members[0].isfile():
                    raise APIError('Archiwum backupu ma nieprawidłową zawartość.')
                if members[0].size > MAX_SNAPSHOT_BYTES:
                    raise APIError('Snapshot przekracza limit 100 MB.', 413)
                snapshot_file = archive.extractfile(members[0])
                if snapshot_file is None:
                    raise APIError('Nie można odczytać snapshotu z archiwum.')
                return json.loads(snapshot_file.read(MAX_SNAPSHOT_BYTES + 1).decode('utf-8'))
        except APIError:
            raise
        except (OSError, tarfile.TarError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise APIError('Nie można odczytać archiwum backupu.') from error

    def import_snapshot(self, payload):
        if not self.is_local_setup_request():
            raise APIError('Import snapshotu jest dostępny tylko lokalnie.', 403)
        self.restore_snapshot(payload.get('snapshot'), replace_existing=False)

    def restore_snapshot(self, snapshot, replace_existing=False):
        if not isinstance(snapshot, dict) or snapshot.get('format') != 'notki-server-snapshot' or snapshot.get('version') != 1:
            raise APIError('Plik nie jest prawidłowym snapshotem serwera Notki.')
        users = snapshot.get('users')
        notes = snapshot.get('notes')
        invites = snapshot.get('invites')
        if not isinstance(users, list) or not isinstance(notes, list) or not isinstance(invites, list):
            raise APIError('Snapshot nie zawiera kompletnej listy kont, notatek i zaproszeń.')
        if not users or len(users) > 10_000 or len(notes) > 100_000 or len(invites) > 100_000:
            raise APIError('Snapshot jest pusty lub przekracza limit danych.')

        user_ids = set()
        emails = set()
        prepared_users = []
        for user in users:
            if not isinstance(user, dict):
                raise APIError('Nieprawidłowe konto w snapshocie.')
            user_id = user.get('id')
            email = normalize_email(user.get('email'))
            password_hash = str(user.get('passwordHash') or '')
            role = user.get('role')
            if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0 or user_id in user_ids:
                raise APIError('Nieprawidłowy identyfikator konta w snapshocie.')
            if email in emails or role not in ('admin', 'user'):
                raise APIError('Nieprawidłowy adres lub rola konta w snapshocie.')
            if not self.valid_password_hash(password_hash):
                raise APIError('Snapshot zawiera nieprawidłowy hash hasła.')
            avatar = user.get('avatar')
            if avatar is not None:
                avatar = str(avatar)
                if len(avatar) > MAX_AVATAR_CHARS or not AVATAR_PATTERN.fullmatch(avatar):
                    raise APIError('Snapshot zawiera nieprawidłowy avatar.')
            user_ids.add(user_id)
            emails.add(email)
            labels = user.get('labels')
            labels_json = json.dumps(labels if isinstance(labels, list) else [])
            prepared_users.append((user_id, email, password_hash, role, self.snapshot_date(user.get('createdAt')), avatar, labels_json))
        if not any(user[3] == 'admin' for user in prepared_users):
            raise APIError('Snapshot musi zawierać konto administratora.')

        prepared_notes = []
        note_ids = set()
        for note in notes:
            if not isinstance(note, dict):
                raise APIError('Nieprawidłowa notatka w snapshocie.')
            note_id = str(note.get('id') or '')
            user_id = note.get('userId')
            title = str(note.get('title') or '')
            body = str(note.get('body') or '')
            tags = note.get('tags') if isinstance(note.get('tags'), list) else []
            if (not note_id or len(note_id) > 200 or note_id in note_ids or isinstance(user_id, bool)
                    or not isinstance(user_id, int) or user_id not in user_ids):
                raise APIError('Nieprawidłowa notatka lub właściciel w snapshocie.')
            if len(title) > 160 or len(body) > 1_000_000:
                raise APIError('Notatka w snapshocie przekracza limit rozmiaru.')
            try:
                sort_order = float(note.get('order') or 0)
            except (TypeError, ValueError) as error:
                raise APIError('Nieprawidłowa kolejność notatek w snapshocie.') from error
            if not math.isfinite(sort_order):
                raise APIError('Nieprawidłowa kolejność notatek w snapshocie.')
            note_ids.add(note_id)
            color = note.get('color')
            prepared_notes.append((
                note_id, user_id, title, body, 1 if note.get('bodyFormat') == 1 else 0,
                color if isinstance(color, str) and color in NOTE_COLORS else 'default',
                json.dumps([str(tag)[:80] for tag in tags[:64]], ensure_ascii=False),
                int(bool(note.get('pinned'))), int(bool(note.get('archived'))), int(bool(note.get('deleted'))),
                self.snapshot_date(note.get('createdAt')), self.snapshot_date(note.get('updatedAt')), sort_order,
            ))

        prepared_invites = []
        invite_hashes = set()
        for invite in invites:
            if not isinstance(invite, dict):
                raise APIError('Nieprawidłowe zaproszenie w snapshocie.')
            token = str(invite.get('tokenHash') or '')
            created_by = invite.get('createdBy')
            if len(token) != 64 or any(character not in '0123456789abcdef' for character in token):
                raise APIError('Nieprawidłowy hash zaproszenia w snapshocie.')
            if (token in invite_hashes or isinstance(created_by, bool) or not isinstance(created_by, int)
                    or created_by not in user_ids):
                raise APIError('Nieprawidłowe zaproszenie lub administrator w snapshocie.')
            invite_hashes.add(token)
            prepared_invites.append((
                token, created_by, self.snapshot_date(invite.get('createdAt')),
                self.snapshot_date(invite.get('expiresAt')), self.snapshot_date(invite['usedAt']) if invite.get('usedAt') else None,
            ))

        prepared_shares = []
        share_keys = set()
        for share in snapshot.get('shares') or []:
            if not isinstance(share, dict):
                raise APIError('Nieprawidłowe udostępnienie w snapshocie.')
            note_id = str(share.get('noteId') or '')
            user_id = share.get('userId')
            permission = share.get('permission')
            if (note_id not in note_ids or isinstance(user_id, bool) or not isinstance(user_id, int)
                    or user_id not in user_ids or permission not in ('read', 'write')):
                raise APIError('Nieprawidłowe udostępnienie w snapshocie.')
            if (note_id, user_id) in share_keys:
                raise APIError('Nieprawidłowe udostępnienie w snapshocie.')
            share_keys.add((note_id, user_id))
            prepared_shares.append((note_id, user_id, permission, self.snapshot_date(share.get('createdAt'))))

        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            has_existing_data = any(
                connection.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone()
                for table in ('users', 'notes', 'invites', 'sessions')
            )
            if has_existing_data and not replace_existing:
                raise APIError('Import jest możliwy tylko do całkowicie pustej bazy danych.', 409)
            if replace_existing:
                connection.execute('DELETE FROM sessions')
                connection.execute('DELETE FROM note_shares')
                connection.execute('DELETE FROM notes')
                connection.execute('DELETE FROM invites')
                connection.execute('DELETE FROM users')
            connection.executemany(
                'INSERT INTO users (id, email, password_hash, role, created_at, avatar, labels_json) VALUES (?, ?, ?, ?, ?, ?, ?)', prepared_users,
            )
            connection.executemany('''
                INSERT INTO notes (id, user_id, title, body, body_format, color, tags_json, pinned, archived,
                                   deleted, created_at, updated_at, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', prepared_notes)
            connection.executemany(
                'INSERT INTO invites (token_hash, created_by, created_at, expires_at, used_at) VALUES (?, ?, ?, ?, ?)',
                prepared_invites,
            )
            connection.executemany(
                'INSERT INTO note_shares (note_id, user_id, permission, created_at) VALUES (?, ?, ?, ?)',
                prepared_shares,
            )
        result = {
            'users': len(prepared_users),
            'notes': len(prepared_notes),
            'invites': len(prepared_invites),
            'shares': len(prepared_shares),
        }
        result['restored' if replace_existing else 'imported'] = True
        self.send_json(result, 200 if replace_existing else 201)

    @staticmethod
    def valid_password_hash(password_hash):
        try:
            algorithm, iterations, salt_hex, digest_hex = password_hash.split('$')
            count = int(iterations)
            return (
                algorithm == 'pbkdf2_sha256' and 100_000 <= count <= 2_000_000
                and len(bytes.fromhex(salt_hex)) == 16 and len(bytes.fromhex(digest_hex)) == 32
            )
        except (ValueError, TypeError):
            return False

    @staticmethod
    def snapshot_date(value):
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (TypeError, ValueError) as error:
            raise APIError('Snapshot zawiera nieprawidłową datę.') from error
        if parsed.tzinfo is None:
            raise APIError('Snapshot zawiera datę bez strefy czasowej.')
        return parsed.astimezone(timezone.utc).isoformat()

    def do_PUT(self):
        try:
            self.check_origin()
            path = urlsplit(self.path).path
            shared_match = re.fullmatch(r'/api/shared/([^/]+)', path)
            if shared_match:
                user = self.require_user()
                self.update_shared_note(user, unquote(shared_match.group(1)), self.read_json())
                return
            if path != '/api/notes':
                self.send_error_json('Nie znaleziono endpointu.', 404)
                return
            user = self.require_user()
            payload = self.read_json()
            self.save_notes(user['id'], payload.get('notes'))
            self.send_json({'saved': True})
        except APIError as error:
            self.send_error_json(str(error), error.status)
        except ValueError as error:
            self.send_error_json(str(error), 400)

    def login(self, payload):
        email = normalize_email(payload.get('email'))
        password = str(payload.get('password') or '')
        if len(password) > 1024:
            self.send_error_json('Nieprawidłowy e-mail lub hasło.', 401)
            return
        with database() as connection:
            row = connection.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if not row or not verify_password(password, row['password_hash']):
            self.send_error_json('Nieprawidłowy e-mail lub hasło.', 401)
            return
        token = self.new_session(row['id'])
        self.send_json({'user': public_user(row)}, extra_headers=self.session_headers(token))

    def register(self, payload):
        email = normalize_email(payload.get('email'))
        password = str(payload.get('password') or '')
        invite = str(payload.get('invite') or '')
        if len(password) < 12:
            raise APIError('Hasło musi mieć co najmniej 12 znaków.')
        if len(password) > 1024:
            raise APIError('Hasło jest zbyt długie.')
        if not invite or len(invite) > 256:
            raise APIError('Rejestracja wymaga ważnego zaproszenia.', 403)
        now = iso_time()
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            invitation = connection.execute(
                'SELECT token_hash FROM invites WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?',
                (token_hash(invite), now),
            ).fetchone()
            if not invitation:
                raise APIError('Zaproszenie jest nieprawidłowe lub wygasło.', 403)
            try:
                cursor = connection.execute(
                    'INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)',
                    (email, hash_password(password), 'user', now),
                )
            except sqlite3.IntegrityError as error:
                raise APIError('Konto z tym adresem e-mail już istnieje.', 409) from error
            connection.execute('UPDATE invites SET used_at = ? WHERE token_hash = ?', (now, invitation['token_hash']))
            user_id = cursor.lastrowid
        token = self.new_session(user_id)
        with database() as connection:
            user = connection.execute('SELECT id, email, role, created_at, avatar, labels_json FROM users WHERE id = ?', (user_id,)).fetchone()
        self.send_json({'user': public_user(user)}, 201, self.session_headers(token))

    def change_password(self, payload):
        user = self.require_user()
        current = str(payload.get('currentPassword') or '')
        password = str(payload.get('newPassword') or '')
        if len(current) > 1024 or len(password) > 1024:
            raise APIError('Hasło jest zbyt długie.')
        if len(password) < 12:
            raise APIError('Hasło musi mieć co najmniej 12 znaków.')
        with database() as connection:
            row = connection.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()
            if not row or not verify_password(current, row['password_hash']):
                raise APIError('Aktualne hasło jest nieprawidłowe.', 403)
            connection.execute('UPDATE users SET password_hash = ? WHERE id = ?', (hash_password(password), user['id']))
            connection.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))
        token = self.new_session(user['id'])
        self.send_json({'changed': True}, extra_headers=self.session_headers(token))

    def change_labels(self, payload):
        user = self.require_user()
        labels = payload.get('labels')
        if not isinstance(labels, list):
            raise APIError('Oczekiwano danych JSON.')
        labels = [str(label)[:80] for label in labels[:200]]
        with database() as connection:
            connection.execute('UPDATE users SET labels_json = ? WHERE id = ?', (json.dumps(labels), user['id']))
        self.send_json({'labels': labels})

    def change_avatar(self, payload):
        user = self.require_user()
        avatar = payload.get('avatar')
        if avatar is None or avatar == '':
            avatar = None
        else:
            avatar = str(avatar)
            if len(avatar) > MAX_AVATAR_CHARS:
                raise APIError('Avatar jest zbyt duży.')
            if not AVATAR_PATTERN.fullmatch(avatar):
                raise APIError('Avatar musi być obrazem PNG, JPEG, WebP lub GIF.')
        with database() as connection:
            connection.execute('UPDATE users SET avatar = ? WHERE id = ?', (avatar, user['id']))
        self.send_json({'avatar': avatar})

    def logout(self):
        cookie = cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            token = cookie[SESSION_COOKIE].value
        except (cookies.CookieError, KeyError):
            token = None
        if token:
            with database() as connection:
                connection.execute('DELETE FROM sessions WHERE token_hash = ?', (token_hash(token),))
        self.send_json({'loggedOut': True}, extra_headers=self.session_headers('', 0))

    def create_invite(self):
        user = self.require_user(admin=True)
        token = secrets.token_urlsafe(32)
        created = utc_now()
        expires = created + timedelta(days=INVITE_DAYS)
        with database() as connection:
            connection.execute(
                'INSERT INTO invites (token_hash, created_by, created_at, expires_at) VALUES (?, ?, ?, ?)',
                (token_hash(token), user['id'], iso_time(created), iso_time(expires)),
            )
        host = self.headers.get('Host', 'localhost:8000')
        scheme = 'https' if os.environ.get('NOTKI_PUBLIC_HTTPS') == '1' else 'http'
        self.send_json({'url': f'{scheme}://{host}/?invite={token}', 'expiresAt': iso_time(expires)}, 201)

    def save_notes(self, user_id, notes):
        if not isinstance(notes, list) or len(notes) > 10_000:
            raise APIError('Nieprawidłowa lista notatek.')
        prepared = []
        seen = set()
        for note in notes:
            if not isinstance(note, dict):
                raise APIError('Nieprawidłowa notatka.')
            note_id = str(note.get('id') or '')
            title = str(note.get('title') or '')
            body = str(note.get('body') or '')
            tags = note.get('tags') if isinstance(note.get('tags'), list) else []
            if not note_id or len(note_id) > 200 or note_id in seen or len(title) > 160 or len(body) > 1_000_000:
                raise APIError('Dane notatki są nieprawidłowe lub zbyt duże.')
            seen.add(note_id)
            created = str(note.get('createdAt') or iso_time())[:64]
            updated = str(note.get('updatedAt') or created)[:64]
            try:
                sort_order = float(note.get('order') or 0)
            except (TypeError, ValueError) as error:
                raise APIError('Nieprawidłowa kolejność notatek.') from error
            if not math.isfinite(sort_order):
                raise APIError('Nieprawidłowa kolejność notatek.')
            prepared.append((
                note_id, user_id, title, body, 1 if note.get('bodyFormat') == 1 else 0,
                note.get('color') if note.get('color') in NOTE_COLORS else 'default',
                json.dumps([str(tag)[:80] for tag in tags[:64]], ensure_ascii=False),
                int(bool(note.get('pinned'))), int(bool(note.get('archived'))), int(bool(note.get('deleted'))),
                created, updated, sort_order,
            ))
        with database() as connection:
            connection.execute('DELETE FROM notes WHERE user_id = ?', (user_id,))
            connection.executemany('''
                INSERT INTO notes (id, user_id, title, body, body_format, color, tags_json, pinned, archived,
                                   deleted, created_at, updated_at, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', prepared)

    @staticmethod
    def note_from_row(row):
        return {
            'id': row['id'], 'title': row['title'], 'body': row['body'], 'bodyFormat': row['body_format'],
            'color': row['color'], 'tags': json.loads(row['tags_json']), 'pinned': bool(row['pinned']),
            'archived': bool(row['archived']), 'deleted': bool(row['deleted']), 'createdAt': row['created_at'],
            'updatedAt': row['updated_at'], 'order': row['sort_order'],
        }

    def owned_note(self, connection, user_id, note_id):
        """Return the note only when the given user owns it."""
        row = connection.execute('SELECT * FROM notes WHERE id = ? AND user_id = ?', (note_id, user_id)).fetchone()
        if not row:
            raise APIError('Nie znaleziono notatki.', 404)
        return row

    def directory(self, user_id):
        """Other accounts a note can be shared with, without exposing anything beyond the address."""
        with database() as connection:
            rows = connection.execute(
                'SELECT id, email, avatar FROM users WHERE id != ? ORDER BY email COLLATE NOCASE', (user_id,)
            ).fetchall()
        return [{'id': row['id'], 'email': row['email'], 'avatar': row['avatar']} for row in rows]

    def list_shares(self, user, note_id):
        with database() as connection:
            self.owned_note(connection, user['id'], note_id)
            rows = connection.execute('''
                SELECT note_shares.user_id, note_shares.permission, note_shares.created_at, users.email, users.avatar
                FROM note_shares JOIN users ON users.id = note_shares.user_id
                WHERE note_shares.note_id = ? ORDER BY users.email COLLATE NOCASE
            ''', (note_id,)).fetchall()
        return [
            {'userId': row['user_id'], 'email': row['email'], 'avatar': row['avatar'],
             'permission': row['permission'], 'createdAt': row['created_at']}
            for row in rows
        ]

    def create_share(self, user, note_id, payload):
        permission = str(payload.get('permission') or 'read')
        if permission not in ('read', 'write'):
            raise APIError('Nieprawidłowy poziom uprawnień.')
        email = normalize_email(payload.get('email'))
        with database() as connection:
            self.owned_note(connection, user['id'], note_id)
            target = connection.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
            if not target:
                raise APIError('Nie znaleziono użytkownika o tym adresie e-mail.', 404)
            if target['id'] == user['id']:
                raise APIError('Nie możesz udostępnić notatki samemu sobie.')
            connection.execute('''
                INSERT INTO note_shares (note_id, user_id, permission, created_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(note_id, user_id) DO UPDATE SET permission = excluded.permission
            ''', (note_id, target['id'], permission, iso_time()))
        self.send_json({'shares': self.list_shares(user, note_id)}, 201)

    def delete_share(self, user, note_id, target_id):
        with database() as connection:
            self.owned_note(connection, user['id'], note_id)
            cursor = connection.execute('DELETE FROM note_shares WHERE note_id = ? AND user_id = ?', (note_id, target_id))
            if not cursor.rowcount:
                raise APIError('Ta notatka nie jest już udostępniona temu użytkownikowi.', 404)
        self.send_json({'shares': self.list_shares(user, note_id)})

    def shared_notes(self, user_id):
        """Notes other people shared with this user, tagged with the owner and the granted permission."""
        with database() as connection:
            rows = connection.execute('''
                SELECT notes.*, note_shares.permission, users.email AS owner_email, users.avatar AS owner_avatar
                FROM note_shares
                JOIN notes ON notes.id = note_shares.note_id
                JOIN users ON users.id = notes.user_id
                WHERE note_shares.user_id = ? AND notes.deleted = 0
                ORDER BY notes.updated_at DESC
            ''', (user_id,)).fetchall()
        shared = []
        for row in rows:
            note = self.note_from_row(row)
            note['ownerEmail'] = row['owner_email']
            note['ownerAvatar'] = row['owner_avatar']
            note['permission'] = row['permission']
            shared.append(note)
        return shared

    def writable_note_ids(self, connection, user_id):
        rows = connection.execute(
            "SELECT note_id FROM note_shares WHERE user_id = ? AND permission = 'write'", (user_id,)
        ).fetchall()
        return {row['note_id'] for row in rows}

    def update_shared_note(self, user, note_id, payload):
        """Let a recipient with write access update the content of a note shared with them.

        Only the fields a recipient may change are copied; ownership, ordering and the owner's own
        flags stay untouched.
        """
        title = str(payload.get('title') or '')
        body = str(payload.get('body') or '')
        if len(title) > 160 or len(body) > 1_000_000:
            raise APIError('Dane notatki są nieprawidłowe lub zbyt duże.')
        tags = payload.get('tags') if isinstance(payload.get('tags'), list) else []
        with database() as connection:
            row = connection.execute(
                'SELECT permission FROM note_shares WHERE note_id = ? AND user_id = ?', (note_id, user['id'])
            ).fetchone()
            if not row:
                raise APIError('Nie znaleziono notatki.', 404)
            if row['permission'] != 'write':
                raise APIError('Nie masz uprawnień do edycji tej notatki.', 403)
            connection.execute('''
                UPDATE notes SET title = ?, body = ?, body_format = ?, color = ?, tags_json = ?, updated_at = ?
                WHERE id = ?
            ''', (
                title, body, 1 if payload.get('bodyFormat') == 1 else 0,
                payload.get('color') if payload.get('color') in NOTE_COLORS else 'default',
                json.dumps([str(tag)[:80] for tag in tags[:64]], ensure_ascii=False),
                iso_time(), note_id,
            ))
        self.send_json({'saved': True})

    def serve_static(self, filename):
        if filename not in STATIC_FILES and filename not in TRANSLATION_FILES and filename != 'manifest.json':
            self.send_error_json('Nie znaleziono pliku.', 404)
            return
        file_path = ROOT / filename
        data = file_path.read_bytes()
        content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        if content_type.startswith('text/') or content_type in ('application/javascript',):
            content_type += '; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format_string, *args):
        super().log_message('%s %s', self.command, urlsplit(self.path).path)


def main():
    parser = argparse.ArgumentParser(description='Lokalny serwer Notki z bazą SQLite.')
    parser.add_argument('--create-admin', action='store_true', help='Utwórz pierwsze konto administratora.')
    parser.add_argument('--host', default=os.environ.get('NOTKI_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('NOTKI_PORT', '8000')))
    args = parser.parse_args()

    initialize_database()
    if args.create_admin:
        create_admin_account()
        return
    server = ThreadingHTTPServer((args.host, args.port), NotkiHandler)
    print(f'Notki działa pod adresem http://{args.host}:{args.port}')
    with database() as connection:
        needs_setup = connection.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone() is None
    if needs_setup:
        print(f'Pierwsza konfiguracja administratora: http://127.0.0.1:{args.port}/setup')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nZatrzymywanie serwera...')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()