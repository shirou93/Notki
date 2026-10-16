import argparse
import base64
import getpass
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
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
import urllib.request
import qr


ROOT = Path(__file__).resolve().parent
VERSION = '0.1.5.83'
DB_PATH = Path(os.environ.get('NOTKI_DB_PATH', ROOT / 'data' / 'notki.sqlite3'))
SESSION_COOKIE = 'notki_session'
SESSION_DAYS = 30
INVITE_DAYS = 7
PASSWORD_ITERATIONS = 310_000

def hash_password(password):
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PASSWORD_ITERATIONS)
    return f'pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${derived.hex()}'

# Dummy hash used to mitigate timing side-channel attacks during login when email is not found
# This hash must be generated properly to have exact exact same timing properties.
DUMMY_PASSWORD_HASH = hash_password('')

MAX_REQUEST_BYTES = 3 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024
BACKUP_FILENAME_PATTERN = re.compile(r'^notki-[A-Za-z0-9_-]+\.json$')
NOTE_COLORS = {'default', 'mint', 'lemon', 'peach', 'lilac', 'sky', 'rose', 'sand', 'sage', 'plum'}
AVATAR_PATTERN = re.compile(r'^data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}$')
MAX_AVATAR_CHARS = 2_900_000
STATIC_FILES = {
    'manifest.json', 'index.html', 'app.js', 'i18n.js', 'theme.js', 'setup.html', 'setup.js', 'styles.css',
    'apple-touch-icon.png', 'icon-192.png', 'icon-512.png', 'icon.svg'}
TRANSLATION_FILES = {
    'translations/pl.js', 'translations/en.js', 'translations/de.js',
    'translations/fr.js', 'translations/ja.js', 'translations/ko.js',
    'translations/it.js', 'translations/es.js'
}
DEFAULT_LANGUAGE = 'en'
SUPPORTED_LANGUAGES = ('pl', 'en', 'de', 'fr', 'ja', 'ko', 'it', 'es')

LOG_BUFFER = []
LOG_BUFFER_LOCK = threading.Lock()
MAX_LOG_ENTRIES = 200

def add_log(level, message):
    entry = {
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'level': level,
        'message': message
    }
    with LOG_BUFFER_LOCK:
        LOG_BUFFER.append(entry)
        if len(LOG_BUFFER) > MAX_LOG_ENTRIES:
            LOG_BUFFER.pop(0)

# Polish messages are the source strings; this catalog provides their English counterparts.
POLISH_MESSAGES = {
    'Enter a valid e-mail address.': 'Podaj poprawny adres e-mail.',
    'The password must be at least 12 characters long.': 'Hasło musi mieć co najmniej 12 znaków.',
    'The password is too long.': 'Hasło jest zbyt długie.',
    'The passwords do not match.': 'Podane hasła nie są takie same.',
    'Invalid request size.': 'Nieprawidłowy rozmiar żądania.',
    'The request is too large.': 'Żądanie jest zbyt duże.',
    'JSON data was expected.': 'Oczekiwano danych JSON.',
    'A .tgz or .json archive was expected.': 'Oczekiwano archiwum .tgz lub .json.',
    'Invalid JSON format.': 'Nieprawidłowy format JSON.',
    'Invalid request data.': 'Nieprawidłowe dane żądania.',
    'A cross-origin request was blocked.': 'Żądanie z innej domeny zostało zablokowane.',
    'Sign in to continue.': 'Zaloguj się, aby kontynuować.',
    'This section is available only to the administrator.': 'Ta sekcja jest dostępna tylko dla administratora.',
    'The first-time setup can only be completed locally.': 'Pierwszą konfigurację można wykonać wyłącznie lokalnie.',
    'Creating the first administrator requires local access.': 'Pierwsza konfiguracja administratora wymaga dostępu lokalnego.',
    'Endpoint not found.': 'Nie znaleziono endpointu.',
    'Page not found.': 'Nie znaleziono strony.',
    'File not found.': 'Nie znaleziono pliku.',
    'The administrator account has already been created.': 'Konto administratora zostało już utworzone.',
    'An account with this e-mail address already exists.': 'Konto z tym adresem e-mail już istnieje.',
    'Invalid e-mail or password.': 'Nieprawidłowy e-mail lub hasło.',
    'The current password is incorrect.': 'Aktualne hasło jest nieprawidłowe.',
    'Registration requires a valid invitation.': 'Rejestracja wymaga ważnego zaproszenia.',
    'The invitation is invalid or has expired.': 'Zaproszenie jest nieprawidłowe lub wygasło.',
    'The snapshot exceeds the 100 MB limit.': 'Snapshot przekracza limit 100 MB.',
    'Could not save the backup on the server.': 'Nie udało się zapisać backupu na serwerze.',
    'Backup not found.': 'Nie znaleziono backupu.',
    'The backup file exceeds the size limit.': 'Plik backupu przekracza limit rozmiaru.',
    'The backup archive cannot be read.': 'Nie można odczytać archiwum backupu.',
    'The backup archive has invalid contents.': 'Archiwum backupu ma nieprawidłową zawartość.',
    'The snapshot cannot be read from the archive.': 'Nie można odczytać snapshotu z archiwum.',
    'Snapshot import is available only locally.': 'Import snapshotu jest dostępny tylko lokalnie.',
    'The file is not a valid Notki server snapshot.': 'Plik nie jest prawidłowym snapshotem serwera Notki.',
    'The snapshot does not contain a complete list of accounts, notes, and invitations.': 'Snapshot nie zawiera kompletnej listy kont, notatek i zaproszeń.',
    'The snapshot is empty or exceeds the data limit.': 'Snapshot jest pusty lub przekracza limit danych.',
    'Invalid account in the snapshot.': 'Nieprawidłowe konto w snapshocie.',
    'Invalid account identifier in the snapshot.': 'Nieprawidłowy identyfikator konta w snapshocie.',
    'Invalid account address or role in the snapshot.': 'Nieprawidłowy adres lub rola konta w snapshocie.',
    'The snapshot contains an invalid password hash.': 'Snapshot zawiera nieprawidłowy hash hasła.',
    'The snapshot contains an invalid avatar.': 'Snapshot zawiera nieprawidłowy avatar.',
    'The avatar is too large.': 'Avatar jest zbyt duży.',
    'The avatar must be a PNG, JPEG, WebP, or GIF image.': 'Avatar musi być obrazem PNG, JPEG, WebP lub GIF.',
    'The snapshot must contain an administrator account.': 'Snapshot musi zawierać konto administratora.',
    'Invalid note in the snapshot.': 'Nieprawidłowa notatka w snapshocie.',
    'Invalid note or owner in the snapshot.': 'Nieprawidłowa notatka lub właściciel w snapshocie.',
    'A note in the snapshot exceeds the size limit.': 'Notatka w snapshocie przekracza limit rozmiaru.',
    'Invalid note order in the snapshot.': 'Nieprawidłowa kolejność notatek w snapshocie.',
    'Invalid invitation in the snapshot.': 'Nieprawidłowe zaproszenie w snapshocie.',
    'Invalid invitation hash in the snapshot.': 'Nieprawidłowy hash zaproszenia w snapshocie.',
    'Invalid invitation or administrator in the snapshot.': 'Nieprawidłowe zaproszenie lub administrator w snapshocie.',
    'Import is possible only into a completely empty database.': 'Import jest możliwy tylko do całkowicie pustej bazy danych.',
    'The snapshot contains an invalid date.': 'Snapshot zawiera nieprawidłową datę.',
    'The snapshot contains a date without a time zone.': 'Snapshot zawiera datę bez strefy czasowej.',
    'Invalid note list.': 'Nieprawidłowa lista notatek.',
    'Invalid note.': 'Nieprawidłowa notatka.',
    'The note data is invalid or too large.': 'Dane notatki są nieprawidłowe lub zbyt duże.',
    'Invalid note order.': 'Nieprawidłowa kolejność notatek.',
    'Note not found.': 'Nie znaleziono notatki.',
    'You cannot share a note with yourself.': 'Nie możesz udostępnić notatki samemu sobie.',
    'No user with that e-mail address was found.': 'Nie znaleziono użytkownika o tym adresie e-mail.',
    'Invalid permission level.': 'Nieprawidłowy poziom uprawnień.',
    'This note is no longer shared with that user.': 'Ta notatka nie jest już udostępniona temu użytkownikowi.',
    'You do not have permission to edit this note.': 'Nie masz uprawnień do edycji tej notatki.',
    'You cannot change permissions of a note you do not own.': 'Nie możesz zmieniać uprawnień notatki, której nie jesteś właścicielem.',
    'No newer version available.': 'Brak nowszej wersji.',
    'Could not fetch update information.': 'Nie udało się pobrać informacji o aktualizacji.',
    'No tarball address in response.': 'Brak adresu tarball w odpowiedzi.',
    'An error occurred while downloading the archive.': 'Wystąpił błąd podczas pobierania archiwum.',
    'Could not extract files.': 'Nie udało się wyodrębnić plików.',
    'Invalid download URL.': 'Nieprawidłowy adres pobierania.',
    '2FA session expired or invalid.': 'Sesja 2FA wygasła lub jest nieprawidłowa.',
    'Invalid two-factor code.': 'Nieprawidłowy kod dwuskładnikowy.',
    'Passkey not found.': 'Nie znaleziono klucza zabezpieczeń.',
    'Invalid passkey signature.': 'Nieprawidłowy podpis klucza zabezpieczeń.',
    'Invalid key data.': 'Nieprawidłowe dane klucza.',
    'User not found.': 'Nie znaleziono użytkownika.',
    'Invitation not found.': 'Nie znaleziono zaproszenia.',
    'Could not delete backup.': 'Nie udało się usunąć backupu.',
    'You cannot delete your own account from the admin panel.': 'Nie możesz usunąć własnego konta z panelu administratora.',
    'No backup archive provided in request.': 'Brak archiwum w żądaniu.',
    'Expected .json, .tgz, or multipart/form-data file.': 'Oczekiwano pliku .json, .tgz lub multipart/form-data.',
}


TEMP_2FA_TOKENS = {}
TEMP_2FA_LOCK = threading.Lock()
FAILED_AUTH_ATTEMPTS = {}
FAILED_AUTH_LOCK = threading.Lock()

def record_failed_auth(ip):
    now = time.time()
    with FAILED_AUTH_LOCK:
        attempts = [t for t in FAILED_AUTH_ATTEMPTS.get(ip, []) if now - t < 60]
        attempts.append(now)
        FAILED_AUTH_ATTEMPTS[ip] = attempts

def is_rate_limited(ip, max_failed=15, window_seconds=60):
    now = time.time()
    with FAILED_AUTH_LOCK:
        attempts = [t for t in FAILED_AUTH_ATTEMPTS.get(ip, []) if now - t < window_seconds]
        FAILED_AUTH_ATTEMPTS[ip] = attempts
        return len(attempts) >= max_failed

def parse_header_params(header_str):
    if not header_str:
        return '', {}
    parts = header_str.split(';')
    main_val = parts[0].strip().lower()
    params = {}
    for part in parts[1:]:
        if '=' in part:
            k, v = part.split('=', 1)
            params[k.strip().lower()] = v.strip().strip('"\'')
    return main_val, params

def parse_multipart_data(rfile, boundary, content_length):
    if isinstance(boundary, str):
        boundary = boundary.encode('utf-8')
    data = rfile.read(content_length)
    fields = {}
    delimiter = b'--' + boundary
    parts = data.split(delimiter)
    for part in parts:
        if not part or part.startswith(b'--'):
            continue
        if b'\r\n\r\n' in part:
            header_bytes, body = part.split(b'\r\n\r\n', 1)
            if body.endswith(b'\r\n'):
                body = body[:-2]
            header_str = header_bytes.decode('utf-8', errors='ignore')
            name = None
            for line in header_str.split('\r\n'):
                if line.lower().startswith('content-disposition:'):
                    _, params = parse_header_params(line)
                    name = params.get('name')
                    break
            if name:
                fields.setdefault(name, []).append(body)
    return fields

def create_temp_2fa_token(user_id):
    token = secrets.token_urlsafe(32)
    expires_at = utc_now() + timedelta(minutes=5)
    with TEMP_2FA_LOCK:
        now = utc_now()
        expired = [k for k, v in TEMP_2FA_TOKENS.items() if v['expiresAt'] < now]
        for k in expired:
            del TEMP_2FA_TOKENS[k]
        TEMP_2FA_TOKENS[token] = {'userId': user_id, 'expiresAt': expires_at}
    return token

def consume_temp_2fa_token(token):
    if not token:
        return None
    with TEMP_2FA_LOCK:
        data = TEMP_2FA_TOKENS.pop(token, None)
        if not data:
            return None
        if data['expiresAt'] < utc_now():
            return None
        return data['userId']

def generate_totp_secret():
    alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
    return ''.join(secrets.choice(alphabet) for _ in range(16))

def compute_totp_code(secret_b32, time_step=30, counter=None):
    if counter is None:
        counter = int(time.time() // time_step)
    secret_b32 = str(secret_b32 or '').strip().upper()
    missing_padding = len(secret_b32) % 8
    if missing_padding:
        secret_b32 += '=' * (8 - missing_padding)
    key = base64.b32decode(secret_b32, casefold=True)
    msg = struct.pack('>Q', counter)
    hmac_hash = hmac.new(key, msg, hashlib.sha1).digest()
    offset = hmac_hash[-1] & 0x0f
    binary = struct.unpack('>I', hmac_hash[offset:offset+4])[0] & 0x7fffffff
    code = binary % 1_000_000
    return f'{code:06d}'

def safe_b64decode(val):
    if not val:
        return b''
    val_str = str(val).strip().replace('-', '+').replace('_', '/')
    missing_padding = len(val_str) % 4
    if missing_padding:
        val_str += '=' * (4 - missing_padding)
    return base64.b64decode(val_str)

SPKI_P256_HEADER = bytes.fromhex('3059301306072a8648ce3d020106082a8648ce3d03010703420004')

def extract_spki_der(pub_bytes):
    if not pub_bytes:
        return None
    if len(pub_bytes) == 91 and pub_bytes.startswith(SPKI_P256_HEADER):
        return pub_bytes
    if len(pub_bytes) == 65 and pub_bytes[0] == 4:
        return SPKI_P256_HEADER[:-1] + pub_bytes
    if len(pub_bytes) == 64:
        return SPKI_P256_HEADER + pub_bytes

    idx_x = pub_bytes.find(b'\x21\x58\x20')
    idx_y = pub_bytes.find(b'\x22\x58\x20')
    if idx_x != -1 and idx_y != -1:
        x = pub_bytes[idx_x + 3 : idx_x + 35]
        y = pub_bytes[idx_y + 3 : idx_y + 35]
        if len(x) == 32 and len(y) == 32:
            return SPKI_P256_HEADER + x + y
    return None

def verify_totp_code(secret_b32, code, time_step=30, window=1):
    code = str(code or '').strip()
    if not code.isdigit() or len(code) != 6:
        return False
    current_counter = int(time.time() // time_step)

    try:
        secret_b32 = str(secret_b32 or '').strip().upper()
        missing_padding = len(secret_b32) % 8
        if missing_padding:
            secret_b32 += '=' * (8 - missing_padding)
        key = base64.b32decode(secret_b32, casefold=True)
    except Exception:
        return False

    for i in range(-window, window + 1):
        try:
            msg = struct.pack('>Q', current_counter + i)
            hmac_hash = hmac.new(key, msg, hashlib.sha1).digest()
            offset = hmac_hash[-1] & 0x0f
            binary = struct.unpack('>I', hmac_hash[offset:offset+4])[0] & 0x7fffffff
            generated_code = f'{binary % 1_000_000:06d}'
            if hmac.compare_digest(generated_code, code):
                return True
        except Exception:
            pass
    return False

def verify_passkey_signature(public_key_pem, sig_bytes, signed_data):
    pub_file = tempfile.NamedTemporaryFile('wb', delete=False)
    sig_file = tempfile.NamedTemporaryFile('wb', delete=False)
    data_file = tempfile.NamedTemporaryFile('wb', delete=False)
    try:
        pub_file.write(public_key_pem.encode('utf-8'))
        pub_file.close()
        sig_file.write(sig_bytes)
        sig_file.close()
        data_file.write(signed_data)
        data_file.close()
        proc = subprocess.run(
            ['openssl', 'dgst', '-sha256', '-verify', pub_file.name, '-signature', sig_file.name, data_file.name],
            capture_output=True
        )
        return proc.returncode == 0
    except Exception:
        return False
    finally:
        for path in (pub_file.name, sig_file.name, data_file.name):
            try:
                os.unlink(path)
            except OSError:
                pass


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
    if language == 'pl':
        return POLISH_MESSAGES.get(message, message)
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
        connection.execute('PRAGMA journal_mode = WAL')
        connection.execute('PRAGMA synchronous = NORMAL')
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
            CREATE INDEX IF NOT EXISTS notes_user_sort_idx ON notes(user_id, sort_order DESC);
            CREATE TABLE IF NOT EXISTS note_shares (
                note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                permission TEXT NOT NULL DEFAULT 'read' CHECK (permission IN ('read', 'write')),
                created_at TEXT NOT NULL,
                PRIMARY KEY (note_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS note_shares_user_idx ON note_shares(user_id);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS passkeys (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                public_key_pem TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS passkeys_user_idx ON passkeys(user_id);
        ''')
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(users)')}
        if 'avatar' not in columns:
            connection.execute('ALTER TABLE users ADD COLUMN avatar TEXT')
        if 'labels_json' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN labels_json TEXT NOT NULL DEFAULT '[]'")
        if 'totp_secret' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT")
        if 'backup_codes_json' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN backup_codes_json TEXT")


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
        raise ValueError('Enter a valid e-mail address.')
    local, domain = email.split('@')
    if not local or not domain or '.' not in domain or any(character.isspace() for character in email):
        raise ValueError('Enter a valid e-mail address.')
    return email


def public_user(row):
    labels = []
    try:
        if row['labels_json']:
            labels = json.loads(row['labels_json'])
    except (IndexError, KeyError, json.JSONDecodeError):
        pass

    avatar = None
    try:
        avatar = row['avatar']
    except (IndexError, KeyError):
        pass

    return {
        'id': row['id'], 'email': row['email'], 'isAdmin': row['role'] == 'admin',
        'createdAt': row['created_at'], 'avatar': avatar,
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
        password = getpass.getpass('Hasło (minimum 12 znaków): ')
        confirmation = getpass.getpass('Powtórz hasło: ')
        if len(password) < 12:
            raise ValueError('The password must be at least 12 characters long.')
        if password != confirmation:
            raise ValueError('The passwords do not match.')
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
    server_version = f'NotkiServer/{VERSION}'

    def end_headers(self):
        # Security headers to mitigate Clickjacking, MIME-sniffing, and cross-origin referrer leaks
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none';")
        super().end_headers()

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
            raise APIError('Invalid request size.') from error
        if length < 0 or length > max_bytes:
            raise APIError('The request is too large.', 413)
        return self.rfile.read(length)

    def read_json(self, max_bytes=MAX_REQUEST_BYTES):
        if 'application/json' not in self.headers.get('Content-Type', ''):
            raise APIError('JSON data was expected.', 415)
        body = self.read_body(max_bytes)
        if not body:
            return {}
        try:
            value = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise APIError('Invalid JSON format.') from error
        if not isinstance(value, dict):
            raise APIError('Invalid request data.')
        return value

    def get_forwarded_host(self):
        forwarded = self.headers.get('X-Forwarded-Host')
        if forwarded:
            return forwarded.split(',')[0].strip()
        return self.headers.get('Host')

    def get_forwarded_proto(self):
        proto = self.headers.get('X-Forwarded-Proto')
        if not proto:
            proto = self.headers.get('X-Forwarded-Scheme') or self.headers.get('X-Url-Scheme')
        if not proto:
            front_end = self.headers.get('Front-End-Https') or self.headers.get('X-Forwarded-Ssl')
            if front_end and front_end.lower() in ('on', '1', 'true'):
                return 'https'
        if proto:
            first_proto = proto.split(',')[0].strip().lower()
            if first_proto in ('https', 'http'):
                return first_proto
        return 'http' if self.headers.get('Host') else ''

    def check_origin(self):
        origin = self.headers.get('Origin')
        if origin:
            expected_host = self.get_forwarded_host()
            if expected_host:
                origin_parsed = urlsplit(origin)
                origin_hostname = (origin_parsed.hostname or '').lower()

                expected_parsed = urlsplit(f"//{expected_host}")
                expected_hostname = (expected_parsed.hostname or '').lower()

                if origin_hostname != expected_hostname:
                    raise APIError('A cross-origin request was blocked.', 403)

                if expected_parsed.port is not None:
                    origin_port = origin_parsed.port
                    if origin_port is None:
                        origin_port = 443 if origin_parsed.scheme == 'https' else (80 if origin_parsed.scheme == 'http' else None)
                    if origin_port != expected_parsed.port:
                        raise APIError('A cross-origin request was blocked.', 403)

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
        host = urlsplit(f"//{self.get_forwarded_host() or ''}").hostname or ''
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
            raise APIError('Sign in to continue.', 401)
        if admin and not user['isAdmin']:
            raise APIError('This section is available only to the administrator.', 403)
        return user

    def get_session_days(self):
        if hasattr(self, '_session_days'):
            return self._session_days
        try:
            with database() as connection:
                row = connection.execute("SELECT value FROM settings WHERE key = 'sessionDays'").fetchone()
                if row and row['value']:
                    self._session_days = max(1, min(3650, int(row['value'])))
                    return self._session_days
        except Exception:
            pass
        self._session_days = SESSION_DAYS
        return self._session_days

    def session_headers(self, token, max_age=None):
        if max_age is None:
            max_age = self.get_session_days() * 24 * 60 * 60
        is_https = (
            os.environ.get('NOTKI_COOKIE_SECURE') == '1' or
            self.get_forwarded_proto() == 'https'
        )
        secure = '; Secure' if is_https else ''
        return [('Set-Cookie', f'{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}')]

    def new_session(self, user_id):
        token = secrets.token_urlsafe(32)
        days = self.get_session_days()
        with database() as connection:
            connection.execute('DELETE FROM sessions WHERE expires_at <= ?', (iso_time(),))
            connection.execute(
                'INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)',
                (token_hash(token), user_id, iso_time(utc_now() + timedelta(days=days))),
            )
        return token

    def handle_setup_get(self, path):
        if path == '/api/setup/status':
            self.send_json({'needsSetup': not self.has_admin()})
            return True
        elif path in ('/setup', '/setup.html'):
            if self.has_admin():
                self.send_redirect('/')
            elif not self.is_local_setup_request():
                self.send_error_json('The first-time setup can only be completed locally.', 403)
            else:
                self.serve_static('setup.html')

    def handle_account_get(self, path):
        if path == '/api/session':
            self.send_json({'user': self.current_user()})
            return True
        elif path == '/api/account/2fa':
            user = self.require_user()
            with database() as connection:
                row = connection.execute('SELECT totp_secret FROM users WHERE id = ?', (user['id'],)).fetchone()
                pk_rows = connection.execute('SELECT id, name, created_at FROM passkeys WHERE user_id = ? ORDER BY created_at DESC', (user['id'],)).fetchall()
            has_totp = bool(row and row['totp_secret'] and not row['totp_secret'].startswith('pending:'))
            passkeys = [{'id': r['id'], 'name': r['name'], 'createdAt': r['created_at']} for r in pk_rows]
            self.send_json({'hasTotp': has_totp, 'passkeys': passkeys})
            return True
        elif path == '/api/users':
            user = self.require_user()
            self.send_json({'users': self.directory(user['id'])})
            return True
        return False

    def handle_notes_get(self, path):
        if path == '/api/notes':
            user = self.require_user()
            with database() as connection:
                rows = connection.execute('''
                    SELECT notes.*, (SELECT COUNT(*) FROM note_shares WHERE note_shares.note_id = notes.id) AS share_count
                    FROM notes WHERE user_id = ? ORDER BY sort_order DESC
                ''', (user['id'],)).fetchall()
            self.send_json({'notes': [self.note_from_row(row) for row in rows]})
            return True
        elif path == '/api/shared':
            user = self.require_user()
            self.send_json({'notes': self.shared_notes(user['id'])})
            return True
        elif path.startswith('/api/notes/') and path.endswith('/shares'):
            user = self.require_user()
            note_id = path[len('/api/notes/'):-len('/shares')]
            self.send_json({'shares': self.list_shares(user, note_id)})
            return True
        return False

    def handle_admin_get(self, path):
        if path == '/api/admin/settings':
            self.get_settings()
            return True
        elif path == '/api/admin/logs':
            self.get_logs()
            return True
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
                    SELECT users.id, users.email, users.role, users.created_at, users.totp_secret,
                           COUNT(DISTINCT notes.id) AS note_count,
                           (SELECT COUNT(*) FROM passkeys WHERE passkeys.user_id = users.id) AS passkey_count
                    FROM users LEFT JOIN notes ON notes.user_id = users.id
                    GROUP BY users.id ORDER BY users.created_at DESC
                ''').fetchall()
                invites = connection.execute('''
                    SELECT token_hash, created_at, expires_at, used_at FROM invites ORDER BY created_at DESC LIMIT 30
                ''').fetchall()
                pending = connection.execute(
                    'SELECT COUNT(*) FROM invites WHERE used_at IS NULL AND expires_at > ?', (iso_time(),)
                ).fetchone()[0]
            self.send_json({
                'stats': {key: stats[key] or 0 for key in ('users', 'notes', 'active', 'archived', 'trash')}
                          | {'pendingInvites': pending},
                'users': [{
                    'id': row['id'], 'email': row['email'], 'role': row['role'], 'createdAt': row['created_at'], 'notes': row['note_count'],
                    'has2FA': bool((row['totp_secret'] and not row['totp_secret'].startswith('pending:')) or row['passkey_count'] > 0)
                } for row in users],
                'invites': [{'tokenHash': row['token_hash'], 'createdAt': row['created_at'], 'expiresAt': row['expires_at'], 'usedAt': row['used_at']} for row in invites],
            })
            return True
        elif path == '/api/admin/backups':
            self.list_server_backups()
            return True
        elif path.startswith('/api/admin/backups/'):
            filename = path.removeprefix('/api/admin/backups/')
            self.download_server_backup(filename)
            return True
        elif path == '/api/admin/update/check':
            self.check_update()
            return True
        return False

    def handle_static_get(self, path):
        if path in ('/', '/index.html') and not self.has_admin():
            if not self.is_local_setup_request():
                self.send_error_json('Creating the first administrator requires local access.', 403)
                return True
            self.send_redirect('/setup')
            return True
        filename = 'index.html' if path in ('/', '/admin', '/admin.html') else path.lstrip('/')
        self.serve_static(filename)
        return True

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        try:
            handled = False
            if path == '/api/setup/status' or path in ('/setup', '/setup.html'):
                handled = self.handle_setup_get(path)
            elif path.startswith('/api/admin/'):
                handled = self.handle_admin_get(path)
            elif path.startswith('/api/notes') or path == '/api/shared':
                handled = self.handle_notes_get(path)
            elif path in ('/api/session', '/api/account/2fa', '/api/users'):
                handled = self.handle_account_get(path)
            elif path in ('/', '/index.html', '/admin', '/admin.html') or path.lstrip('/') in STATIC_FILES or path.lstrip('/') in TRANSLATION_FILES:
                handled = self.handle_static_get(path)

            if not handled:
                if path.startswith('/api/'):
                    self.send_error_json('Endpoint not found.', 404)
                else:
                    self.send_error_json('Page not found.', 404)
        except APIError as error:
            self.send_error_json(str(error), error.status)
        except ValueError as error:
            self.send_error_json(str(error), 400)

    def read_archive_from_request(self):
        ctype, params = parse_header_params(self.headers.get('Content-Type', ''))
        if ctype == 'multipart/form-data':
            boundary = params.get('boundary')
            if not boundary:
                raise APIError('Invalid request data.', 400)
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                fields = parse_multipart_data(self.rfile, boundary, content_length)
            except Exception:
                fields = {}
            archive_list = fields.get('archive') or fields.get('file') or []
            archive_bytes = archive_list[0] if archive_list else b''
            if isinstance(archive_bytes, str):
                archive_bytes = archive_bytes.encode('utf-8')
            if not archive_bytes:
                archive_bytes = self.read_body(MAX_SNAPSHOT_BYTES)
            if not archive_bytes:
                raise APIError('No backup archive provided in request.', 400)
            if len(archive_bytes) > MAX_SNAPSHOT_BYTES:
                raise APIError('The backup file exceeds the size limit.', 413)
            return archive_bytes
        else:
            archive_bytes = self.read_body(MAX_SNAPSHOT_BYTES)
            if not archive_bytes:
                raise APIError('No backup archive provided in request.', 400)
            return archive_bytes

    def handle_setup_post(self, path, payload):
        if path == '/api/setup/admin':
            self.create_first_admin(payload)
            return True
        elif path == '/api/setup/import':
            self.import_snapshot(payload)
            return True
        return False

    def handle_login_post(self, path, payload):
        if path == '/api/login':
            self.login(payload)
            return True
        elif path == '/api/login/2fa':
            self.login_2fa(payload)
            return True
        elif path == '/api/login/passkey':
            self.login_passkey(payload)
            return True
        elif path == '/api/register':
            self.register(payload)
            return True
        elif path == '/api/logout':
            self.logout()
            return True
        return False

    def handle_account_post(self, path, payload):
        if path == '/api/account/password':
            self.change_password(payload)
            return True
        elif path == '/api/account/avatar':
            self.change_avatar(payload)
            return True
        elif path == '/api/account/labels':
            self.change_labels(payload)
            return True
        elif path == '/api/account/totp':
            self.setup_totp()
            return True
        elif path == '/api/account/totp/verify':
            self.verify_totp(payload)
            return True
        elif path == '/api/account/passkey':
            self.add_passkey(payload)
            return True
        return False

    def handle_notes_post(self, path, payload):
        if path.startswith('/api/notes/') and path.endswith('/shares'):
            user = self.require_user()
            note_id = path[len('/api/notes/'):-len('/shares')]
            self.create_share(user, note_id, payload)
            return True
        return False

    def handle_admin_post(self, path, payload):
        if path == '/api/admin/settings':
            self.save_settings(payload)
            return True
        elif path == '/api/admin/invites':
            self.create_invite(payload)
            return True
        elif path == '/api/admin/backups':
            self.create_server_backup(payload)
            return True
        elif path.startswith('/api/admin/backups/'):
            match = re.fullmatch(r'/api/admin/backups/([^/]+)/restore', path)
            if match:
                self.restore_server_backup(match.group(1), payload)
                return True
        elif path == '/api/admin/update/perform':
            self.perform_update(payload)
            return True
        return False

    def do_POST(self):
        try:
            self.check_origin()
            path = urlsplit(self.path).path
            if path in ('/api/login', '/api/login/2fa', '/api/login/passkey', '/api/account/password', '/api/account/totp/verify'):
                client_ip = self.headers.get('X-Forwarded-For', '').split(',')[0].strip() or self.client_address[0]
                if is_rate_limited(client_ip):
                    raise APIError('Too many failed attempts. Please try again later.', 429)
            if path == '/api/setup/import-backup':
                archive_bytes = self.read_archive_from_request()
                self.import_snapshot_archive(archive_bytes)
                return
            if path == '/api/admin/backups/upload-restore':
                self.upload_restore_server_backup()
                return

            payload = self.read_json(MAX_SNAPSHOT_BYTES if path == '/api/setup/import' else MAX_REQUEST_BYTES)

            handled = False
            if path.startswith('/api/setup/'):
                handled = self.handle_setup_post(path, payload)
            elif path.startswith('/api/admin/'):
                handled = self.handle_admin_post(path, payload)
            elif path.startswith('/api/login') or path in ('/api/register', '/api/logout'):
                handled = self.handle_login_post(path, payload)
            elif path.startswith('/api/account/'):
                handled = self.handle_account_post(path, payload)
            elif path.startswith('/api/notes/'):
                handled = self.handle_notes_post(path, payload)

            if not handled:
                self.send_error_json('Endpoint not found.', 404)
        except APIError as error:
            self.send_error_json(str(error), error.status)
        except ValueError as error:
            self.send_error_json(str(error), 400)

    def do_DELETE(self):
        try:
            self.check_origin()
            path = unquote(urlsplit(self.path).path)
            if path == '/api/account/totp':
                self.remove_totp()
                return
            passkey_match = re.fullmatch(r'/api/account/passkey/([^/]+)', path)
            if passkey_match:
                user = self.require_user()
                key_id = unquote(passkey_match.group(1))
                with database() as connection:
                    cursor = connection.execute('DELETE FROM passkeys WHERE id = ? AND user_id = ?', (key_id, user['id']))
                    if not cursor.rowcount:
                        raise APIError('Passkey not found.', 404)
                self.send_json({'deleted': True})
                return
            share_match = re.fullmatch(r'/api/notes/([^/]+)/shares/(\d+)', path)
            if share_match:
                user = self.require_user()
                self.delete_share(user, share_match.group(1), int(share_match.group(2)))
                return
            match = re.fullmatch(r'/api/admin/backups/([^/]+)', path)
            if match:
                self.delete_server_backup(match.group(1))
                return
            invite_match = re.fullmatch(r'/api/admin/invites/([^/]+)', path)
            if invite_match:
                self.delete_invite(invite_match.group(1))
                return
            user_2fa_match = re.fullmatch(r'/api/admin/users/(\d+)/2fa', path)
            if user_2fa_match:
                self.reset_user_2fa(int(user_2fa_match.group(1)))
                return
            user_match = re.fullmatch(r'/api/admin/users/(\d+)', path)
            if user_match:
                self.delete_user(int(user_match.group(1)))
                return
            self.send_error_json('Endpoint not found.', 404)
        except APIError as error:
            self.send_error_json(str(error), error.status)

    def create_first_admin(self, payload):
        if not self.is_local_setup_request():
            raise APIError('The first-time setup can only be completed locally.', 403)
        email = normalize_email(payload.get('email'))
        password = str(payload.get('password') or '')
        if len(password) < 12:
            raise APIError('The password must be at least 12 characters long.')
        if len(password) > 1024:
            raise APIError('The password is too long.')
        now = iso_time()
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone():
                raise APIError('The administrator account has already been created.', 409)
            try:
                cursor = connection.execute(
                    'INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)',
                    (email, hash_password(password), 'admin', now),
                )
            except sqlite3.IntegrityError as error:
                raise APIError('An account with this e-mail address already exists.', 409) from error
            user_id = cursor.lastrowid
        token = self.new_session(user_id)
        with database() as connection:
            user = connection.execute('SELECT id, email, role, created_at, avatar, labels_json FROM users WHERE id = ?', (user_id,)).fetchone()
        self.send_json({'user': public_user(user)}, 201, self.session_headers(token))

    def build_snapshot(self):
        with database() as connection:
            connection.execute('BEGIN')
            users = connection.execute('SELECT id, email, password_hash, role, created_at, avatar, labels_json, totp_secret, backup_codes_json FROM users ORDER BY id').fetchall()
            notes = connection.execute('SELECT * FROM notes ORDER BY user_id, sort_order DESC').fetchall()
            invites = connection.execute('SELECT * FROM invites ORDER BY created_at').fetchall()
            shares = connection.execute('SELECT * FROM note_shares ORDER BY note_id, user_id').fetchall()
            passkeys = connection.execute('SELECT id, user_id, public_key_pem, name, created_at FROM passkeys ORDER BY user_id, created_at').fetchall()
            settings = connection.execute('SELECT key, value FROM settings ORDER BY key').fetchall()
        snapshot = {
            'format': 'notki-server-snapshot',
            'version': 1,
            'createdAt': iso_time(),
            'users': [
                {'id': row['id'], 'email': row['email'], 'passwordHash': row['password_hash'], 'role': row['role'],
                 'createdAt': row['created_at'], 'avatar': row['avatar'],
                 'labels': json.loads(row['labels_json']) if row['labels_json'] else [],
                 'totpSecret': row['totp_secret'],
                 'backupCodes': json.loads(row['backup_codes_json']) if row['backup_codes_json'] else []}
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
            'passkeys': [
                {'id': row['id'], 'userId': row['user_id'], 'publicKeyPem': row['public_key_pem'],
                 'name': row['name'], 'createdAt': row['created_at']}
                for row in passkeys
            ],
            'settings': [
                {'key': row['key'], 'value': row['value']}
                for row in settings
            ],
        }
        return snapshot

    def create_server_backup(self, payload=None):
        self.require_user(admin=True)
        created_at = utc_now()
        snapshot = self.build_snapshot()
        backup_bytes = json.dumps(snapshot, ensure_ascii=False, indent=2).encode('utf-8')
        if len(backup_bytes) > MAX_SNAPSHOT_BYTES:
            raise APIError('The snapshot exceeds the 100 MB limit.', 413)

        backup_dir = backup_directory()
        backup_dir.mkdir(parents=True, exist_ok=True)
        filename = f"notki-backup-{created_at.strftime('%Y%m%d-%H%M%SZ')}-{secrets.token_hex(4)}.json"
        backup_path = backup_dir / filename
        temporary_path = backup_dir / f'.{secrets.token_hex(16)}.tmp'
        try:
            with temporary_path.open('xb') as stream:
                stream.write(backup_bytes)
            os.replace(temporary_path, backup_path)
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            raise APIError('Could not save the backup on the server.', 500) from error
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
            try:
                stat = path.stat()
                backups.append({
                    'filename': path.name,
                    'createdAt': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    'sizeBytes': stat.st_size,
                })
            except OSError:
                continue
        backups.sort(key=lambda backup: backup['createdAt'], reverse=True)
        self.send_json({'backups': backups})

    def find_server_backup(self, filename):
        if not BACKUP_FILENAME_PATTERN.fullmatch(filename):
            raise APIError('Backup not found.', 404)
        backup_dir = backup_directory().resolve()
        path = (backup_dir / filename).resolve()
        if not path.is_relative_to(backup_dir) or path.is_symlink() or not path.is_file():
            raise APIError('Backup not found.', 404)
        return path

    def download_server_backup(self, filename):
        self.require_user(admin=True)
        path = self.find_server_backup(filename)
        try:
            size = path.stat().st_size
            if size > MAX_SNAPSHOT_BYTES:
                raise APIError('The backup file exceeds the size limit.', 413)
            data = path.read_bytes()
        except OSError as error:
            raise APIError('The backup archive cannot be read.', 500) from error
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Content-Disposition', f'attachment; filename="{path.name}"')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def delete_server_backup(self, filename):
        self.require_user(admin=True)
        path = self.find_server_backup(filename)
        try:
            path.unlink()
        except FileNotFoundError:
            raise APIError('Backup not found.', 404)
        except OSError as error:
            raise APIError('Could not delete backup.', 500) from error
        self.send_json({'deleted': filename})

    def delete_user(self, user_id):
        admin = self.require_user(admin=True)
        if admin['id'] == user_id:
            raise APIError('You cannot delete your own account from the admin panel.', 400)
        with database() as connection:
            row = connection.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
            if not row:
                raise APIError('User not found.', 404)
            connection.execute('DELETE FROM users WHERE id = ?', (user_id,))
        self.send_json({'deleted': user_id})

    def reset_user_2fa(self, user_id):
        self.require_user(admin=True)
        with database() as connection:
            row = connection.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
            if not row:
                raise APIError('User not found.', 404)
            connection.execute('UPDATE users SET totp_secret = NULL, backup_codes_json = NULL WHERE id = ?', (user_id,))
            connection.execute('DELETE FROM passkeys WHERE user_id = ?', (user_id,))
        self.send_json({'reset': user_id})

    def delete_invite(self, token_hash):
        self.require_user(admin=True)
        with database() as connection:
            cursor = connection.execute('DELETE FROM invites WHERE token_hash = ?', (token_hash,))
            if not cursor.rowcount:
                raise APIError('Invitation not found.', 404)
        self.send_json({'deleted': token_hash})

    def upload_restore_server_backup(self):
        self.require_user(admin=True)
        content_type = self.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            payload = self.read_json(MAX_SNAPSHOT_BYTES)
            snapshot = payload.get('snapshot') if isinstance(payload, dict) and 'snapshot' in payload else payload
        else:
            raw_bytes = self.read_archive_from_request()
            snapshot = self.snapshot_from_bytes(raw_bytes)
        self.restore_snapshot(snapshot, replace_existing=True)

    def restore_server_backup(self, filename, payload=None):
        self.require_user(admin=True)
        path = self.find_server_backup(filename)
        if path.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise APIError('The backup file exceeds the size limit.', 413)
        try:
            raw_bytes = path.read_bytes()
            snapshot = self.snapshot_from_bytes(raw_bytes)
        except OSError as error:
            raise APIError('The backup archive cannot be read.') from error
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

                valid_tags = [t for t in tags if isinstance(t, dict) and re.match(r'^v?[0-9.]+$', t.get('name', ''))]
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
            raise APIError('Could not fetch update information.', 500)

    def _download_update_archive(self, tarball_url):
        class UpdateRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if not newurl.startswith('https://codeload.github.com/shirou93/Notki/'):
                    raise urllib.error.URLError("Invalid redirect URL.")
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        req = urllib.request.Request(tarball_url)
        req.add_header('User-Agent', 'Notki-App')
        opener = urllib.request.build_opener(UpdateRedirectHandler())
        try:
            with opener.open(req, timeout=30) as response:
                return response.read()
        except Exception:
            raise APIError('An error occurred while downloading the archive.', 500)

    def _verify_update_version(self, archive, members):
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
                        raise APIError('No newer version available.', 400)

    def _extract_update_archive(self, archive, members):
        for member in members:
            parts = member.name.split('/', 1)
            if len(parts) > 1:
                member.name = parts[1]
                if not member.name or member.name.startswith('/') or '..' in member.name:
                    continue
                target_path = (ROOT / member.name).resolve()
                if target_path.is_relative_to(ROOT):
                    if hasattr(tarfile, 'data_filter'):
                        archive.extract(member, path=ROOT, filter='data')
                    else:
                        archive.extract(member, path=ROOT)

    def perform_update(self, payload):
        self.require_user(admin=True)
        tarball_url = payload.get('tarballUrl')
        if not tarball_url or not tarball_url.startswith('https://api.github.com/repos/shirou93/Notki/tarball/'):
            raise APIError('Invalid download URL.', 400)

        archive_bytes = self._download_update_archive(tarball_url)

        try:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode='r:gz') as archive:
                members = archive.getmembers()
                if not members:
                    raise ValueError("Empty archive")

                self._verify_update_version(archive, members)
                self._extract_update_archive(archive, members)
        except APIError:
            raise
        except Exception:
            raise APIError('Could not extract files.', 500)

        threading.Timer(1.0, lambda: os._exit(0)).start()
        self.send_json({'success': True})

    def import_snapshot_archive(self, archive_bytes):
        if not self.is_local_setup_request():
            raise APIError('Snapshot import is available only locally.', 403)
        self.restore_snapshot(self.snapshot_from_bytes(archive_bytes), replace_existing=False)

    @staticmethod
    def snapshot_from_bytes(raw_bytes):
        if len(raw_bytes) > MAX_SNAPSHOT_BYTES:
            raise APIError('The snapshot exceeds the 100 MB limit.', 413)
        try:
            return json.loads(raw_bytes.decode('utf-8-sig'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            try:
                with tarfile.open(fileobj=io.BytesIO(raw_bytes), mode='r:*') as archive:
                    members = archive.getmembers()
                    valid_members = [
                        m for m in members
                        if m.isfile() and Path(m.name).name == 'snapshot.json' and not Path(m.name).name.startswith('._')
                    ]
                    if len(valid_members) == 1:
                        snapshot_member = valid_members[0]
                        snapshot_file = archive.extractfile(snapshot_member)
                        if snapshot_file:
                            return json.loads(snapshot_file.read(MAX_SNAPSHOT_BYTES + 1).decode('utf-8-sig'))
            except Exception as e:
                add_log('ERROR', f'Failed to extract backup archive: {e}')
            raise APIError('The backup archive cannot be read.')

    def import_snapshot(self, payload):
        if not self.is_local_setup_request():
            raise APIError('Snapshot import is available only locally.', 403)
        self.restore_snapshot(payload.get('snapshot'), replace_existing=False)

    def _prepare_snapshot_users(self, users):
        user_ids = set()
        emails = set()
        prepared_users = []
        for user in users:
            if not isinstance(user, dict):
                raise APIError('Invalid account in the snapshot.')
            user_id = user.get('id')
            email = normalize_email(user.get('email'))
            password_hash = str(user.get('passwordHash') or '')
            role = user.get('role')
            if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0 or user_id in user_ids:
                raise APIError('Invalid account identifier in the snapshot.')
            if email in emails or role not in ('admin', 'user'):
                raise APIError('Invalid account address or role in the snapshot.')
            if not self.valid_password_hash(password_hash):
                raise APIError('The snapshot contains an invalid password hash.')
            avatar = user.get('avatar')
            if avatar is not None:
                avatar = str(avatar)
                if len(avatar) > MAX_AVATAR_CHARS or not AVATAR_PATTERN.fullmatch(avatar):
                    raise APIError('The snapshot contains an invalid avatar.')
            totp_secret = user.get('totpSecret')
            if totp_secret is not None:
                totp_secret = str(totp_secret)
                if len(totp_secret) > 256:
                    totp_secret = None
            backup_codes = user.get('backupCodes')
            backup_codes_json = json.dumps(backup_codes) if isinstance(backup_codes, list) else None
            user_ids.add(user_id)
            emails.add(email)
            labels = user.get('labels')
            labels_json = json.dumps(labels if isinstance(labels, list) else [])
            prepared_users.append((user_id, email, password_hash, role, self.snapshot_date(user.get('createdAt')), avatar, labels_json, totp_secret, backup_codes_json))
        if not any(user[3] == 'admin' for user in prepared_users):
            raise APIError('The snapshot must contain an administrator account.')
        return user_ids, emails, prepared_users

    def _prepare_snapshot_note(self, note, user_ids, note_ids):
        if not isinstance(note, dict):
            raise APIError('Invalid note in the snapshot.')
        note_id = str(note.get('id') or '')
        user_id = note.get('userId')
        title = str(note.get('title') or '')
        body = str(note.get('body') or '')
        tags = note.get('tags') if isinstance(note.get('tags'), list) else []
        if (not note_id or len(note_id) > 200 or note_id in note_ids or isinstance(user_id, bool)
                or not isinstance(user_id, int) or user_id not in user_ids):
            raise APIError('Invalid note or owner in the snapshot.')
        if len(title) > 160 or len(body) > 1_000_000:
            raise APIError('A note in the snapshot exceeds the size limit.')
        try:
            sort_order = float(note.get('order') or 0)
        except (TypeError, ValueError) as error:
            raise APIError('Invalid note order in the snapshot.') from error
        if not math.isfinite(sort_order):
            raise APIError('Invalid note order in the snapshot.')
        note_ids.add(note_id)
        color = note.get('color')
        archived = bool(note.get('archived'))
        deleted = bool(note.get('deleted'))
        pinned = False if (archived or deleted) else bool(note.get('pinned'))
        return (
            note_id, user_id, title, body, 1 if note.get('bodyFormat') == 1 else 0,
            color if isinstance(color, str) and color in NOTE_COLORS else 'default',
            json.dumps([str(tag)[:80] for tag in tags[:64]], ensure_ascii=False),
            int(pinned), int(archived), int(deleted),
            self.snapshot_date(note.get('createdAt')), self.snapshot_date(note.get('updatedAt')), sort_order,
        )

    def _prepare_snapshot_notes(self, notes, user_ids):
        prepared_notes = []
        note_ids = set()
        for note in notes:
            prepared_notes.append(self._prepare_snapshot_note(note, user_ids, note_ids))
        return note_ids, prepared_notes

    def _prepare_snapshot_invites(self, invites, user_ids):
        prepared_invites = []
        invite_hashes = set()
        for invite in invites:
            if not isinstance(invite, dict):
                raise APIError('Invalid invitation in the snapshot.')
            token = str(invite.get('tokenHash') or '')
            created_by = invite.get('createdBy')
            if len(token) != 64 or any(character not in '0123456789abcdef' for character in token):
                raise APIError('Invalid invitation hash in the snapshot.')
            if (token in invite_hashes or isinstance(created_by, bool) or not isinstance(created_by, int)
                    or created_by not in user_ids):
                raise APIError('Invalid invitation or administrator in the snapshot.')
            invite_hashes.add(token)
            prepared_invites.append((
                token, created_by, self.snapshot_date(invite.get('createdAt')),
                self.snapshot_date(invite.get('expiresAt')), self.snapshot_date(invite['usedAt']) if invite.get('usedAt') else None,
            ))
        return prepared_invites

    def _prepare_snapshot_shares(self, shares, user_ids, note_ids):
        prepared_shares = []
        share_keys = set()
        for share in shares:
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
        return prepared_shares

    def _prepare_snapshot_passkeys(self, passkeys, user_ids):
        prepared_passkeys = []
        passkey_ids = set()
        for pk in passkeys:
            if not isinstance(pk, dict):
                raise APIError('Nieprawidłowy klucz zabezpieczeń w snapshocie.')
            pk_id = str(pk.get('id') or '')
            user_id = pk.get('userId')
            pub_pem = str(pk.get('publicKeyPem') or '')
            name = str(pk.get('name') or 'Passkey')[:80]
            if not pk_id or len(pk_id) > 500 or pk_id in passkey_ids or isinstance(user_id, bool) or not isinstance(user_id, int) or user_id not in user_ids or not pub_pem:
                raise APIError('Nieprawidłowy klucz zabezpieczeń w snapshocie.')
            passkey_ids.add(pk_id)
            prepared_passkeys.append((pk_id, user_id, pub_pem, name, self.snapshot_date(pk.get('createdAt'))))
        return prepared_passkeys

    def _prepare_snapshot_settings(self, settings):
        prepared_settings = []
        setting_keys = set()
        for st in settings:
            if not isinstance(st, dict):
                raise APIError('Nieprawidłowe ustawienie w snapshocie.')
            key = str(st.get('key') or '')
            value = str(st.get('value') or '')
            if not key or len(key) > 100 or key in setting_keys:
                raise APIError('Nieprawidłowe ustawienie w snapshocie.')
            setting_keys.add(key)
            prepared_settings.append((key, value))
        return prepared_settings

    def _apply_snapshot_data(self, prepared_users, prepared_notes, prepared_invites, prepared_shares, prepared_passkeys, prepared_settings, replace_existing):
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            has_existing_data = bool(connection.execute(
                'SELECT 1 WHERE '
                'EXISTS(SELECT 1 FROM users) OR '
                'EXISTS(SELECT 1 FROM notes) OR '
                'EXISTS(SELECT 1 FROM invites) OR '
                'EXISTS(SELECT 1 FROM sessions) OR '
                'EXISTS(SELECT 1 FROM passkeys) OR '
                'EXISTS(SELECT 1 FROM settings)'
            ).fetchone())
            if has_existing_data and not replace_existing:
                raise APIError('Import is possible only into a completely empty database.', 409)
            if replace_existing:
                connection.execute('DELETE FROM sessions')
                connection.execute('DELETE FROM note_shares')
                connection.execute('DELETE FROM notes')
                connection.execute('DELETE FROM invites')
                connection.execute('DELETE FROM passkeys')
                connection.execute('DELETE FROM settings')
                connection.execute('DELETE FROM users')
            connection.executemany(
                'INSERT INTO users (id, email, password_hash, role, created_at, avatar, labels_json, totp_secret, backup_codes_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                prepared_users,
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
            if prepared_passkeys:
                connection.executemany(
                    'INSERT INTO passkeys (id, user_id, public_key_pem, name, created_at) VALUES (?, ?, ?, ?, ?)',
                    prepared_passkeys,
                )
            if prepared_settings:
                connection.executemany(
                    'INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                    prepared_settings,
                )

    def restore_snapshot(self, snapshot, replace_existing=False):
        if not isinstance(snapshot, dict) or snapshot.get('format') != 'notki-server-snapshot' or snapshot.get('version') != 1:
            raise APIError('The file is not a valid Notki server snapshot.')
        users = snapshot.get('users')
        notes = snapshot.get('notes')
        invites = snapshot.get('invites')
        if not isinstance(users, list) or not isinstance(notes, list) or not isinstance(invites, list):
            raise APIError('The snapshot does not contain a complete list of accounts, notes, and invitations.')
        if not users or len(users) > 10_000 or len(notes) > 100_000 or len(invites) > 100_000:
            raise APIError('The snapshot is empty or exceeds the data limit.')

        user_ids, _, prepared_users = self._prepare_snapshot_users(users)
        note_ids, prepared_notes = self._prepare_snapshot_notes(notes, user_ids)
        prepared_invites = self._prepare_snapshot_invites(invites, user_ids)
        prepared_shares = self._prepare_snapshot_shares(snapshot.get('shares') or [], user_ids, note_ids)
        prepared_passkeys = self._prepare_snapshot_passkeys(snapshot.get('passkeys') or [], user_ids)
        prepared_settings = self._prepare_snapshot_settings(snapshot.get('settings') or [])

        self._apply_snapshot_data(
            prepared_users, prepared_notes, prepared_invites, prepared_shares,
            prepared_passkeys, prepared_settings, replace_existing
        )

        result = {
            'users': len(prepared_users),
            'notes': len(prepared_notes),
            'invites': len(prepared_invites),
            'shares': len(prepared_shares),
        }
        if 'passkeys' in snapshot:
            result['passkeys'] = len(prepared_passkeys)
        if 'settings' in snapshot:
            result['settings'] = len(prepared_settings)
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
            raise APIError('The snapshot contains an invalid date.') from error
        if parsed.tzinfo is None:
            raise APIError('The snapshot contains a date without a time zone.')
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
                self.send_error_json('Endpoint not found.', 404)
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
            self.send_error_json('Invalid e-mail or password.', 401)
            return
        with database() as connection:
            row = connection.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
            # Verify password using dummy hash if user does not exist to mitigate timing side-channel attacks for email enumeration
            password_hash = row['password_hash'] if row else DUMMY_PASSWORD_HASH
            valid_password = verify_password(password, password_hash)
            if not row or not valid_password:
                client_ip = self.headers.get('X-Forwarded-For', '').split(',')[0].strip() or self.client_address[0]
                record_failed_auth(client_ip)
                self.send_error_json('Invalid e-mail or password.', 401)
                return
            totp_secret = row['totp_secret']
            has_totp = bool(totp_secret and not totp_secret.startswith('pending:'))
            pk_count = connection.execute('SELECT COUNT(*) FROM passkeys WHERE user_id = ?', (row['id'],)).fetchone()[0]
            has_passkey = pk_count > 0
            req_row = connection.execute("SELECT value FROM settings WHERE key = 'require2FA'").fetchone()
            require_2fa = req_row and req_row['value'] == 'true'

        if has_totp or has_passkey or require_2fa:
            temp_token = create_temp_2fa_token(row['id'])
            self.send_json({'requires2FA': True, 'tempToken': temp_token, 'hasTotp': has_totp, 'hasPasskey': has_passkey})
            return

        token = self.new_session(row['id'])
        self.send_json({'user': public_user(row)}, extra_headers=self.session_headers(token))

    def login_2fa(self, payload):
        user_id = consume_temp_2fa_token(payload.get('tempToken'))
        if not user_id:
            raise APIError('2FA session expired or invalid.', 401)
        totp_code = payload.get('totpCode')
        with database() as connection:
            row = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
            if not row:
                raise APIError('User not found.', 404)
            secret = row['totp_secret']
            backup_raw = row['backup_codes_json']
            backup_codes = json.loads(backup_raw) if backup_raw else []

            clean_code = str(totp_code or '').replace('-', '').replace(' ', '').strip().upper()
            totp_valid = secret and not secret.startswith('pending:') and verify_totp_code(secret, totp_code)
            backup_valid = False

            if not totp_valid and clean_code and clean_code in backup_codes:
                backup_valid = True
                backup_codes.remove(clean_code)
                connection.execute('UPDATE users SET backup_codes_json = ? WHERE id = ?', (json.dumps(backup_codes), user_id))

            if not totp_valid and not backup_valid:
                client_ip = self.headers.get('X-Forwarded-For', '').split(',')[0].strip() or self.client_address[0]
                record_failed_auth(client_ip)
                raise APIError('Invalid two-factor code.', 401)
        token = self.new_session(user_id)
        self.send_json({'user': public_user(row)}, extra_headers=self.session_headers(token))

    def login_passkey(self, payload):
        key_id = payload.get('id')
        auth_data_b64 = payload.get('authenticatorData')
        client_data_b64 = payload.get('clientDataJSON')
        sig_b64 = payload.get('signature')
        if not key_id or not auth_data_b64 or not client_data_b64 or not sig_b64:
            raise APIError('Invalid key data.', 400)

        temp_token = payload.get('tempToken')
        with database() as connection:
            if temp_token:
                user_id = consume_temp_2fa_token(temp_token)
                if not user_id:
                    raise APIError('2FA session expired or invalid.', 401)
                row = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
                pk_row = connection.execute('SELECT public_key_pem FROM passkeys WHERE id = ? AND user_id = ?', (key_id, user_id)).fetchone()
            else:
                pk_row = connection.execute('SELECT user_id, public_key_pem FROM passkeys WHERE id = ?', (key_id,)).fetchone()
                if not pk_row:
                    raise APIError('Passkey not found.', 401)
                user_id = pk_row['user_id']
                row = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

            if not pk_row or not row:
                raise APIError('Passkey not found.', 401)
        try:
            auth_bytes = safe_b64decode(auth_data_b64)
            client_bytes = safe_b64decode(client_data_b64)
            sig_bytes = safe_b64decode(sig_b64)
            client_hash = hashlib.sha256(client_bytes).digest()
            signed_data = auth_bytes + client_hash
        except Exception as err:
            raise APIError('Invalid key data.', 400) from err

        if not verify_passkey_signature(pk_row['public_key_pem'], sig_bytes, signed_data):
            client_ip = self.headers.get('X-Forwarded-For', '').split(',')[0].strip() or self.client_address[0]
            record_failed_auth(client_ip)
            raise APIError('Invalid passkey signature.', 401)

        token = self.new_session(user_id)
        self.send_json({'user': public_user(row)}, extra_headers=self.session_headers(token))

    def setup_totp(self):
        user = self.require_user()
        secret = generate_totp_secret()
        with database() as connection:
            connection.execute('UPDATE users SET totp_secret = ? WHERE id = ?', (f'pending:{secret}', user['id']))
        otpauth_url = f"otpauth://totp/Notki:{quote(user['email'])}?secret={secret}&issuer=Notki"
        qr_svg = qr.generate_qr_svg(otpauth_url)
        self.send_json({'secret': secret, 'qrSvg': qr_svg, 'otpauthUrl': otpauth_url})

    def verify_totp(self, payload):
        user = self.require_user()
        code = payload.get('code')
        with database() as connection:
            row = connection.execute('SELECT totp_secret FROM users WHERE id = ?', (user['id'],)).fetchone()
            if not row or not row['totp_secret']:
                raise APIError('Invalid two-factor code.', 400)
            totp_secret = row['totp_secret']
            secret = totp_secret.removeprefix('pending:') if totp_secret.startswith('pending:') else totp_secret
            if not verify_totp_code(secret, code):
                client_ip = self.headers.get('X-Forwarded-For', '').split(',')[0].strip() or self.client_address[0]
                record_failed_auth(client_ip)
                raise APIError('Invalid two-factor code.', 400)

            backup_codes_display = [f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}" for _ in range(8)]
            backup_codes_store = [c.replace('-', '') for c in backup_codes_display]

            connection.execute('UPDATE users SET totp_secret = ?, backup_codes_json = ? WHERE id = ?', (secret, json.dumps(backup_codes_store), user['id']))
        self.send_json({'verified': True, 'backupCodes': backup_codes_display})

    def remove_totp(self):
        user = self.require_user()
        with database() as connection:
            connection.execute('UPDATE users SET totp_secret = NULL, backup_codes_json = NULL WHERE id = ?', (user['id'],))
        self.send_json({'removed': True})

    def add_passkey(self, payload):
        user = self.require_user()
        key_id = payload.get('id')
        name = str(payload.get('name') or 'Passkey')[:80]
        pub_b64 = payload.get('publicKey')
        if not key_id or not pub_b64:
            raise APIError('Invalid key data.', 400)
        try:
            raw_bytes = safe_b64decode(pub_b64)
            spki_bytes = extract_spki_der(raw_bytes)
            if not spki_bytes:
                raise ValueError("Could not parse public key")
            pem = f"-----BEGIN PUBLIC KEY-----\n{base64.b64encode(spki_bytes).decode('utf-8')}\n-----END PUBLIC KEY-----\n"
        except Exception as err:
            raise APIError('Invalid key data.', 400) from err
        with database() as connection:
            connection.execute(
                'INSERT INTO passkeys (id, user_id, public_key_pem, name, created_at) VALUES (?, ?, ?, ?, ?) '
                'ON CONFLICT(id) DO UPDATE SET public_key_pem = excluded.public_key_pem, name = excluded.name',
                (key_id, user['id'], pem, name, iso_time())
            )
        self.send_json({'added': True}, 201)

    def register(self, payload):
        email = normalize_email(payload.get('email'))
        password = str(payload.get('password') or '')
        invite = str(payload.get('invite') or '')
        if len(password) < 12:
            raise APIError('The password must be at least 12 characters long.')
        if len(password) > 1024:
            raise APIError('The password is too long.')
        if not invite or len(invite) > 256:
            raise APIError('Registration requires a valid invitation.', 403)
        now = iso_time()
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            invitation = connection.execute(
                'SELECT token_hash FROM invites WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?',
                (token_hash(invite), now),
            ).fetchone()
            if not invitation:
                raise APIError('The invitation is invalid or has expired.', 403)
            try:
                cursor = connection.execute(
                    'INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)',
                    (email, hash_password(password), 'user', now),
                )
            except sqlite3.IntegrityError as error:
                raise APIError('An account with this e-mail address already exists.', 409) from error
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
            raise APIError('The password is too long.')
        if len(password) < 12:
            raise APIError('The password must be at least 12 characters long.')
        with database() as connection:
            row = connection.execute('SELECT password_hash FROM users WHERE id = ?', (user['id'],)).fetchone()
            if not row or not verify_password(current, row['password_hash']):
                client_ip = self.headers.get('X-Forwarded-For', '').split(',')[0].strip() or self.client_address[0]
                record_failed_auth(client_ip)
                raise APIError('The current password is incorrect.', 403)
            connection.execute('UPDATE users SET password_hash = ? WHERE id = ?', (hash_password(password), user['id']))
            connection.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))
        token = self.new_session(user['id'])
        self.send_json({'changed': True}, extra_headers=self.session_headers(token))

    def change_labels(self, payload):
        user = self.require_user()
        labels = payload.get('labels')
        if not isinstance(labels, list):
            raise APIError('JSON data was expected.')
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
                raise APIError('The avatar is too large.')
            if not AVATAR_PATTERN.fullmatch(avatar):
                raise APIError('The avatar must be a PNG, JPEG, WebP, or GIF image.')
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

    def create_invite(self, payload=None):
        user = self.require_user(admin=True)
        token = secrets.token_urlsafe(32)
        created = utc_now()
        payload = payload or {}
        try:
            days = int(payload.get('days', INVITE_DAYS))
        except ValueError:
            days = INVITE_DAYS
        expires = created + timedelta(days=days)
        with database() as connection:
            connection.execute(
                'INSERT INTO invites (token_hash, created_by, created_at, expires_at) VALUES (?, ?, ?, ?)',
                (token_hash(token), user['id'], iso_time(created), iso_time(expires)),
            )
        host = self.get_forwarded_host() or 'localhost:8000'
        proto = self.get_forwarded_proto()
        scheme = 'https' if (proto == 'https' or os.environ.get('NOTKI_PUBLIC_HTTPS') == '1') else 'http'
        self.send_json({'url': f'{scheme}://{host}/?invite={token}', 'expiresAt': iso_time(expires)}, 201)

    @staticmethod
    def _prepare_note_for_db(note, user_id, seen):
        if not isinstance(note, dict):
            raise APIError('Invalid note.')
        note_id = str(note.get('id') or '')
        title = str(note.get('title') or '')
        body = str(note.get('body') or '')
        tags = note.get('tags') if isinstance(note.get('tags'), list) else []
        if not note_id or len(note_id) > 200 or note_id in seen or len(title) > 160 or len(body) > 1_000_000:
            raise APIError('The note data is invalid or too large.')
        seen.add(note_id)
        created = str(note.get('createdAt') or iso_time())[:64]
        updated = str(note.get('updatedAt') or created)[:64]
        try:
            sort_order = float(note.get('order') or 0)
        except (TypeError, ValueError) as error:
            raise APIError('Invalid note order.') from error
        if not math.isfinite(sort_order):
            raise APIError('Invalid note order.')
        archived = bool(note.get('archived'))
        deleted = bool(note.get('deleted'))
        pinned = False if (archived or deleted) else bool(note.get('pinned'))
        return (
            note_id, user_id, title, body, 1 if note.get('bodyFormat') == 1 else 0,
            note.get('color') if note.get('color') in NOTE_COLORS else 'default',
            json.dumps([str(tag)[:80] for tag in tags[:64]], ensure_ascii=False),
            int(pinned), int(archived), int(deleted),
            created, updated, sort_order,
        )

    def save_notes(self, user_id, notes):
        if not isinstance(notes, list) or len(notes) > 10_000:
            raise APIError('Invalid note list.')
        prepared = []
        seen = set()
        for note in notes:
            prepared.append(NotkiHandler._prepare_note_for_db(note, user_id, seen))
        with database() as connection:
            if seen:
                connection.execute('DELETE FROM notes WHERE user_id = ? AND id NOT IN (SELECT value FROM json_each(?))', (user_id, json.dumps(list(seen))))
            else:
                connection.execute('DELETE FROM notes WHERE user_id = ?', (user_id,))
            connection.executemany('''
                INSERT INTO notes (id, user_id, title, body, body_format, color, tags_json, pinned, archived,
                                   deleted, created_at, updated_at, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    body = excluded.body,
                    body_format = excluded.body_format,
                    color = excluded.color,
                    tags_json = excluded.tags_json,
                    pinned = excluded.pinned,
                    archived = excluded.archived,
                    deleted = excluded.deleted,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    sort_order = excluded.sort_order
                WHERE user_id = excluded.user_id
            ''', prepared)

    @staticmethod
    def note_from_row(row):
        note = {
            'id': row['id'], 'title': row['title'], 'body': row['body'], 'bodyFormat': row['body_format'],
            'color': row['color'], 'tags': json.loads(row['tags_json']), 'pinned': bool(row['pinned']),
            'archived': bool(row['archived']), 'deleted': bool(row['deleted']), 'createdAt': row['created_at'],
            'updatedAt': row['updated_at'], 'order': row['sort_order'],
        }
        try:
            note['shareCount'] = row['share_count']
        except (IndexError, KeyError):
            pass
        return note

    def owned_note(self, connection, user_id, note_id):
        """Return the note only when the given user owns it."""
        row = connection.execute('SELECT * FROM notes WHERE id = ? AND user_id = ?', (note_id, user_id)).fetchone()
        if not row:
            raise APIError('Note not found.', 404)
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
            raise APIError('Invalid permission level.')
        email = normalize_email(payload.get('email'))
        with database() as connection:
            self.owned_note(connection, user['id'], note_id)
            target = connection.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
            if not target:
                raise APIError('No user with that e-mail address was found.', 404)
            if target['id'] == user['id']:
                raise APIError('You cannot share a note with yourself.')
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
                raise APIError('This note is no longer shared with that user.', 404)
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

    def update_shared_note(self, user, note_id, payload):
        """Let a recipient with write access update the content of a note shared with them.

        Only the fields a recipient may change are copied; ownership, ordering and the owner's own
        flags stay untouched.
        """
        title = str(payload.get('title') or '')
        body = str(payload.get('body') or '')
        if len(title) > 160 or len(body) > 1_000_000:
            raise APIError('The note data is invalid or too large.')
        tags = payload.get('tags') if isinstance(payload.get('tags'), list) else []
        with database() as connection:
            row = connection.execute(
                'SELECT permission FROM note_shares WHERE note_id = ? AND user_id = ?', (note_id, user['id'])
            ).fetchone()
            if not row:
                raise APIError('Note not found.', 404)
            if row['permission'] != 'write':
                raise APIError('You do not have permission to edit this note.', 403)
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
            self.send_error_json('File not found.', 404)
            return
        file_path = ROOT / filename
        data = file_path.read_bytes()
        content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        if content_type.startswith('text/') or content_type in ('application/javascript',):
            content_type += '; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def get_settings(self):
        self.require_user(admin=True)
        with database() as connection:
            rows = connection.execute('SELECT key, value FROM settings').fetchall()
            settings_dict = {row['key']: row['value'] for row in rows}
        require_2fa = settings_dict.get('require2FA') == 'true'
        log_level = settings_dict.get('logLevel', 'INFO')
        try:
            session_days = int(settings_dict.get('sessionDays', SESSION_DAYS))
        except (ValueError, TypeError):
            session_days = SESSION_DAYS
        self.send_json({'require2FA': require_2fa, 'logLevel': log_level, 'sessionDays': session_days})

    def save_settings(self, payload):
        self.require_user(admin=True)
        require_2fa = 'true' if payload.get('require2FA') else 'false'
        log_level = str(payload.get('logLevel') or 'INFO').upper()
        if log_level not in ('INFO', 'WARNING', 'ERROR', 'DEBUG'):
            raise APIError('Invalid log level.')
        try:
            session_days = max(1, min(3650, int(payload.get('sessionDays', SESSION_DAYS))))
        except (ValueError, TypeError):
            session_days = SESSION_DAYS
        with database() as connection:
            connection.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', ('require2FA', require_2fa))
            connection.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', ('logLevel', log_level))
            connection.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', ('sessionDays', str(session_days)))
        self.send_json({'require2FA': require_2fa == 'true', 'logLevel': log_level, 'sessionDays': session_days})

    def get_logs(self):
        self.require_user(admin=True)
        with LOG_BUFFER_LOCK:
            logs = list(LOG_BUFFER)
        self.send_json({'logs': logs})

    def log_message(self, format_string, *args):
        msg = format_string % args
        add_log('INFO', msg)
        command = getattr(self, 'command', None) or '-'
        path = getattr(self, 'path', None)
        path_str = urlsplit(path).path if path else '-'
        super().log_message('%s %s', command, path_str)


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