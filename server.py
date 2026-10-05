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
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('NOTKI_DB_PATH', ROOT / 'data' / 'notki.sqlite3'))
SESSION_COOKIE = 'notki_session'
SESSION_DAYS = 30
INVITE_DAYS = 7
PASSWORD_ITERATIONS = 310_000
MAX_REQUEST_BYTES = 3 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024
BACKUP_FILENAME_PATTERN = re.compile(r'^notki-server-\d{8}-\d{6}Z-[a-f0-9]{8}\.tgz$')
NOTE_COLORS = {'default', 'mint', 'lemon', 'peach', 'lilac', 'sky'}
STATIC_FILES = {'index.html', 'admin.html', 'admin.js', 'app.js', 'i18n.js', 'theme.js', 'setup.html', 'setup.js', 'styles.css'}
DEFAULT_LANGUAGE = 'pl'
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
}


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
                created_at TEXT NOT NULL
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
        ''')


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
    return {'id': row['id'], 'email': row['email'], 'isAdmin': row['role'] == 'admin', 'createdAt': row['created_at']}


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


class NotkiHandler(BaseHTTPRequestHandler):
    server_version = 'NotkiServer/1.0'

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
                SELECT users.id, users.email, users.role, users.created_at
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
            elif path in ('/', '/index.html', '/admin', '/admin.html') or path.lstrip('/') in STATIC_FILES:
                if path in ('/', '/index.html') and not self.has_admin():
                    if not self.is_local_setup_request():
                        self.send_error_json('Pierwsza konfiguracja administratora wymaga dostępu lokalnego.', 403)
                        return
                    self.send_redirect('/setup')
                    return
                filename = 'index.html' if path == '/' else 'admin.html' if path == '/admin' else path.lstrip('/')
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
                if self.headers.get('Content-Type', '').split(';', 1)[0].strip() not in ('application/gzip', 'application/x-gzip'):
                    raise APIError('Oczekiwano archiwum .tgz.', 415)
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
            elif path == '/api/admin/invites':
                self.create_invite()
            elif path == '/api/admin/backups':
                self.create_server_backup()
            elif path.startswith('/api/admin/backups/'):
                match = re.fullmatch(r'/api/admin/backups/([^/]+)/restore', path)
                if not match:
                    self.send_error_json('Nie znaleziono endpointu.', 404)
                else:
                    self.restore_server_backup(match.group(1))
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
            match = re.fullmatch(r'/api/admin/backups/([^/]+)', path)
            if not match:
                self.send_error_json('Nie znaleziono endpointu.', 404)
                return
            self.delete_server_backup(match.group(1))
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
            user = connection.execute('SELECT id, email, role, created_at FROM users WHERE id = ?', (user_id,)).fetchone()
        self.send_json({'user': public_user(user)}, 201, self.session_headers(token))

    def build_snapshot(self):
        with database() as connection:
            connection.execute('BEGIN')
            users = connection.execute('SELECT id, email, password_hash, role, created_at FROM users ORDER BY id').fetchall()
            notes = connection.execute('SELECT * FROM notes ORDER BY user_id, sort_order DESC').fetchall()
            invites = connection.execute('SELECT * FROM invites ORDER BY created_at').fetchall()
        snapshot = {
            'format': 'notki-server-snapshot',
            'version': 1,
            'createdAt': iso_time(),
            'users': [
                {'id': row['id'], 'email': row['email'], 'passwordHash': row['password_hash'], 'role': row['role'], 'createdAt': row['created_at']}
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
        }
        return snapshot

    def create_server_backup(self):
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

        backup_dir = backup_directory()
        backup_dir.mkdir(parents=True, exist_ok=True)
        filename = f"notki-server-{created_at.strftime('%Y%m%d-%H%M%SZ')}-{secrets.token_hex(4)}.tgz"
        backup_path = backup_dir / filename
        temporary_path = backup_dir / f'.{secrets.token_hex(16)}.tmp'
        try:
            with temporary_path.open('xb') as stream:
                stream.write(archive_buffer.getvalue())
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

    def restore_server_backup(self, filename):
        self.require_user(admin=True)
        path = self.find_server_backup(filename)
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise APIError('Plik backupu przekracza limit rozmiaru.', 413)
        try:
            snapshot = self.snapshot_from_archive(path.read_bytes())
        except OSError as error:
            raise APIError('Nie można odczytać archiwum backupu.') from error
        self.restore_snapshot(snapshot, replace_existing=True)

    def import_snapshot_archive(self, archive_bytes):
        if not self.is_local_setup_request():
            raise APIError('Import snapshotu jest dostępny tylko lokalnie.', 403)
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
            user_ids.add(user_id)
            emails.add(email)
            prepared_users.append((user_id, email, password_hash, role, self.snapshot_date(user.get('createdAt'))))
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
                connection.execute('DELETE FROM notes')
                connection.execute('DELETE FROM invites')
                connection.execute('DELETE FROM users')
            connection.executemany(
                'INSERT INTO users (id, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)', prepared_users,
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
        result = {
            'users': len(prepared_users),
            'notes': len(prepared_notes),
            'invites': len(prepared_invites),
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
            if urlsplit(self.path).path != '/api/notes':
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
            user = connection.execute('SELECT id, email, role, created_at FROM users WHERE id = ?', (user_id,)).fetchone()
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

    def serve_static(self, filename):
        if filename not in STATIC_FILES:
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