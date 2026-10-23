import argparse
import base64
import functools
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
import webauthn


ROOT = Path(__file__).resolve().parent
VERSION = '0.1.6.11'
GENERATED_SETUP_TOKEN = None
GENERATED_BACKUP_PASSWORD = None
DB_PATH = Path(os.environ.get('NOTKI_DB_PATH', ROOT / 'data' / 'notki.sqlite3'))
# Canonical public host used when generating links (e.g. invitations). When set, it
# takes precedence over request headers so a client cannot poison generated URLs.
PUBLIC_HOST = os.environ.get('NOTKI_PUBLIC_HOST', '').strip()
# Optional allowlist of hostnames that forwarded/host headers may resolve to.
ALLOWED_HOSTS = {
    value.strip().lower()
    for value in os.environ.get('NOTKI_ALLOWED_HOSTS', '').split(',')
    if value.strip()
}
# Reverse proxies on the loopback interface are trusted by default (typical for a
# local Nginx/Caddy sidecar); other deployments must opt in via NOTKI_TRUST_PROXY.
DEFAULT_TRUSTED_PROXY_NETWORKS = ('127.0.0.0/8', '::1/128')

@functools.lru_cache(maxsize=1)
def _get_trusted_proxy_networks(trust_proxy):
    if trust_proxy in ('0', 'false', 'no'):
        return []
    if trust_proxy in ('1', 'true', 'yes', 'all', '*'):
        return [ipaddress.ip_network('0.0.0.0/0'), ipaddress.ip_network('::/0')]
    specs = [value.strip() for value in trust_proxy.split(',') if value.strip()]
    if not specs:
        specs = list(DEFAULT_TRUSTED_PROXY_NETWORKS)
    networks = []
    for spec in specs:
        try:
            networks.append(ipaddress.ip_network(spec, strict=False))
        except ValueError:
            continue
    return networks

SESSION_COOKIE = 'notki_session'
HOST_SESSION_COOKIE = '__Host-notki_session'
SESSION_DAYS = 30
SESSION_IDLE_HOURS = 24
STEP_UP_WINDOW_MINUTES = 5
INVITE_DAYS = 7
PASSWORD_ITERATIONS = 310_000
# Backup encryption is mandatory. The key is always derived from a password with
# scrypt; there is no server-side key fallback because that would make a backup
# dependent on files outside the single backup archive.
BACKUP_FORMAT = 'notki-backup'
BACKUP_FORMAT_VERSION = 2
SNAPSHOT_FORMAT = 'notki-server-snapshot'
SNAPSHOT_VERSION = 2
SUPPORTED_SNAPSHOT_VERSIONS = (SNAPSHOT_VERSION,)
BACKUP_KDF_ALGORITHM = 'scrypt'
BACKUP_KDF_N = 65536
BACKUP_KDF_R = 8
BACKUP_KDF_P = 1
BACKUP_KDF_MIN_N = 16384
BACKUP_KDF_MAX_N = 262144
BACKUP_KDF_MAX_R = 32
BACKUP_KDF_MAX_P = 4
BACKUP_KDF_MAXMEM = 256 * 1024 * 1024
BACKUP_SALT_BYTES = 16
BACKUP_NONCE_BYTES = 12
BACKUP_KEY_BYTES = 32
BACKUP_PASSWORD_MIN_LENGTH = 12
BACKUP_PASSWORD_MAX_LENGTH = 1024
TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_CLOCK_WINDOW = 1
TOTP_ALGORITHM = 'SHA256'
SCRYPT_N = 65536
SCRYPT_R = 8
SCRYPT_P = 1
MAX_CONCURRENT_REQUESTS = 32
REQUEST_TIMEOUT_SECONDS = 15
MAX_AUTH_TRACKED_IPS = 10_000
MAX_AUTH_ACCOUNTS = 10_000
MAX_ATTEMPTS_PER_KEY = 1_000
FAIL2BAN_PRUNE_INTERVAL = 300

def hash_password(password):
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode('utf-8'), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=1024**3
    )
    return f'scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${derived.hex()}'

# Dummy hash used to mitigate timing side-channel attacks during login when email is not found
# This hash must be generated properly to have exact exact same timing properties.
DUMMY_PASSWORD_HASH = hash_password('')

MAX_REQUEST_BYTES = 3 * 1024 * 1024
# Maximum size of the decrypted snapshot payload.
MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024
# Base64 encoding and the JSON envelope add overhead on top of the payload.
MAX_BACKUP_FILE_BYTES = 140 * 1024 * 1024
# CLI restores read a local file chosen by an administrator and are not subject to
# the HTTP upload limit. The limit remains bounded so a mistyped path or a corrupted
# file cannot exhaust memory unexpectedly.
MAX_CLI_BACKUP_BYTES = 2 * 1024 * 1024 * 1024
MAX_CLI_BACKUP_LIMIT = 16 * 1024 * 1024 * 1024
BACKUP_FILENAME_PATTERN = re.compile(r'^notki-[A-Za-z0-9_-]+\.enc$')
NOTE_COLORS = {'default', 'mint', 'lemon', 'peach', 'lilac', 'sky', 'rose', 'sand', 'sage', 'plum'}
AVATAR_PATTERN = re.compile(r'^data:image/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}$')
MAX_AVATAR_CHARS = 2_900_000
# Upper bounds for unauthenticated, in-memory state so a remote attacker cannot exhaust memory.
MAX_PASSKEY_CHALLENGES = 5_000
MAX_TEMP_2FA_TOKENS = 10_000
STATIC_FILES = {
    'manifest.json', 'index.html', 'app.js', 'i18n.js', 'theme.js', 'setup.html', 'setup.js', 'styles.css',
    'apple-touch-icon.png', 'icon-192.png', 'icon-512.png', 'icon.svg', 'vendor/dompurify.min.js'}
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


TEMP_2FA_TOKENS = {}
TEMP_2FA_LOCK = threading.Lock()
PASSKEY_CHALLENGES = {}
PASSKEY_CHALLENGES_LOCK = threading.Lock()
FAILED_AUTH_ATTEMPTS = {}
UNFLUSHED_FAIL2BAN_ATTEMPTS = []
# Failed attempts attributed to a specific (ip, account) pair. This lets a successful
# login clear only the failures recorded for that account instead of wiping the whole
# per-IP budget (which allowed brute-force protection to be reset with a second account).
FAILED_AUTH_ACCOUNTS = {}
FAILED_AUTH_LOCK = threading.Lock()
# Per-account failures aggregated across source addresses. This prevents a
# distributed password-spraying campaign from staying under the per-IP limit.
ACCOUNT_FAILURES = {}
FAIL2BAN_PRUNE_LOCK = threading.Lock()
LAST_FAIL2BAN_PRUNE = 0.0
LAST_AUTH_STATE_PRUNE = 0.0


def account_key(account):
    return str(account or '').strip().casefold()


def parse_forwarded_elements(value):
    """Parse an RFC 7239 ``Forwarded`` header into a list of parameter dicts.

    Malformed elements are ignored. Quoted values have surrounding quotes removed.
    """
    elements = []
    for element in str(value or '').split(','):
        params = {}
        for pair in element.split(';'):
            key, sep, raw = pair.partition('=')
            if not sep:
                continue
            params[key.strip().lower()] = raw.strip().strip('"')
        if params:
            elements.append(params)
    return elements


def parse_forwarded_for(value):
    """Return the client node identifiers from the RFC 7239 ``Forwarded`` header."""
    nodes = []
    for params in parse_forwarded_elements(value):
        node = params.get('for')
        if not node:
            continue
        node = node.strip().strip('"')
        if not node:
            continue
        node = node.lower()
        if node.startswith('['):
            end = node.find(']')
            node = node[1:end] if end != -1 else node[1:]
        elif node.count(':') == 1:
            node = node.rsplit(':', 1)[0]
        nodes.append(node)
    return nodes


def parse_forwarded_host(value):
    """Return the first host from the RFC 7239 ``Forwarded`` header, if any."""
    for params in parse_forwarded_elements(value):
        host = params.get('host')
        if host:
            return host.split(',')[0].strip()
    return None

_FAIL2BAN_CONFIG_CACHE = None

def get_fail2ban_config():
    global _FAIL2BAN_CONFIG_CACHE
    if _FAIL2BAN_CONFIG_CACHE is not None:
        return _FAIL2BAN_CONFIG_CACHE

    enabled = True
    max_attempts = 15
    ban_time = 60
    try:
        with database() as connection:
            rows = connection.execute("SELECT key, value FROM settings WHERE key LIKE ?", ('fail2ban%',)).fetchall()
            settings_dict = {row['key']: row['value'] for row in rows}
            if 'fail2banEnabled' in settings_dict:
                enabled = settings_dict['fail2banEnabled'] == 'true'
            if 'fail2banMaxAttempts' in settings_dict:
                max_attempts = int(settings_dict['fail2banMaxAttempts'])
            if 'fail2banBanTime' in settings_dict:
                ban_time = int(settings_dict['fail2banBanTime'])
    except Exception:
        pass

    _FAIL2BAN_CONFIG_CACHE = {'enabled': enabled, 'max_attempts': max_attempts, 'ban_time': ban_time}
    return _FAIL2BAN_CONFIG_CACHE

def _prune_auth_state_locked(now):
    """Bound in-memory authentication state and drop stale entries."""
    global LAST_AUTH_STATE_PRUNE
    if now - LAST_AUTH_STATE_PRUNE >= FAIL2BAN_PRUNE_INTERVAL:
        LAST_AUTH_STATE_PRUNE = now
        for ip in tuple(FAILED_AUTH_ATTEMPTS):
            attempts = [t for t in FAILED_AUTH_ATTEMPTS[ip] if now - t < 3600]
            if len(attempts) > MAX_ATTEMPTS_PER_KEY:
                attempts = attempts[-MAX_ATTEMPTS_PER_KEY:]
            if attempts:
                FAILED_AUTH_ATTEMPTS[ip] = attempts
            else:
                FAILED_AUTH_ATTEMPTS.pop(ip, None)
        for key in tuple(FAILED_AUTH_ACCOUNTS):
            attempts = [t for t in FAILED_AUTH_ACCOUNTS[key] if now - t < 3600]
            if len(attempts) > MAX_ATTEMPTS_PER_KEY:
                attempts = attempts[-MAX_ATTEMPTS_PER_KEY:]
            if attempts:
                FAILED_AUTH_ACCOUNTS[key] = attempts
            else:
                FAILED_AUTH_ACCOUNTS.pop(key, None)
        for key in tuple(ACCOUNT_FAILURES):
            attempts = [t for t in ACCOUNT_FAILURES[key] if now - t < 3600]
            if len(attempts) > MAX_ATTEMPTS_PER_KEY:
                attempts = attempts[-MAX_ATTEMPTS_PER_KEY:]
            if attempts:
                ACCOUNT_FAILURES[key] = attempts
            else:
                ACCOUNT_FAILURES.pop(key, None)

    while len(FAILED_AUTH_ATTEMPTS) > MAX_AUTH_TRACKED_IPS:
        FAILED_AUTH_ATTEMPTS.pop(next(iter(FAILED_AUTH_ATTEMPTS)), None)
    while len(FAILED_AUTH_ACCOUNTS) > MAX_AUTH_TRACKED_IPS:
        FAILED_AUTH_ACCOUNTS.pop(next(iter(FAILED_AUTH_ACCOUNTS)), None)
    while len(ACCOUNT_FAILURES) > MAX_AUTH_ACCOUNTS:
        ACCOUNT_FAILURES.pop(next(iter(ACCOUNT_FAILURES)), None)



def _flush_fail2ban_buffer():
    with FAILED_AUTH_LOCK:
        if not UNFLUSHED_FAIL2BAN_ATTEMPTS:
            return
        to_flush = UNFLUSHED_FAIL2BAN_ATTEMPTS[:]
        UNFLUSHED_FAIL2BAN_ATTEMPTS.clear()

    try:
        with database() as connection:
            connection.executemany(
                'INSERT INTO fail2ban_attempts (ip, account, created_at) VALUES (?, ?, ?)',
                to_flush
            )
    except Exception:
        # If DB write fails, re-queue the items but cap at a large limit to avoid memory leaks
        with FAILED_AUTH_LOCK:
            UNFLUSHED_FAIL2BAN_ATTEMPTS.extend(to_flush)
            if len(UNFLUSHED_FAIL2BAN_ATTEMPTS) > MAX_AUTH_TRACKED_IPS * 2:
                del UNFLUSHED_FAIL2BAN_ATTEMPTS[:-MAX_AUTH_TRACKED_IPS * 2]

def _prune_fail2ban_database(now):
    """Delete old fail2ban rows occasionally so the table cannot grow forever."""
    global LAST_FAIL2BAN_PRUNE
    with FAIL2BAN_PRUNE_LOCK:
        if now - LAST_FAIL2BAN_PRUNE < FAIL2BAN_PRUNE_INTERVAL:
            return
        LAST_FAIL2BAN_PRUNE = now

    _flush_fail2ban_buffer()

    try:
        ban_time = get_fail2ban_config()['ban_time']
        with database() as connection:
            connection.execute(
                'DELETE FROM fail2ban_attempts WHERE created_at < ?',
                (now - ban_time,)
            )
            # Cap the table size
            connection.execute(
                'DELETE FROM fail2ban_attempts WHERE rowid IN ('
                '  SELECT rowid FROM fail2ban_attempts ORDER BY created_at DESC LIMIT -1 OFFSET 100000'
                ')'
            )
    except Exception:
        pass


def record_failed_auth(ip, account=None):
    now = time.time()
    key = account_key(account)
    with FAILED_AUTH_LOCK:
        attempts = [t for t in FAILED_AUTH_ATTEMPTS.pop(ip, []) if now - t < 3600]
        attempts.append(now)
        FAILED_AUTH_ATTEMPTS[ip] = attempts[-MAX_ATTEMPTS_PER_KEY:]
        if key:
            account_attempts = [t for t in FAILED_AUTH_ACCOUNTS.pop((ip, key), []) if now - t < 3600]
            account_attempts.append(now)
            FAILED_AUTH_ACCOUNTS[(ip, key)] = account_attempts[-MAX_ATTEMPTS_PER_KEY:]
            global_attempts = [t for t in ACCOUNT_FAILURES.pop(key, []) if now - t < 3600]
            global_attempts.append(now)
            ACCOUNT_FAILURES[key] = global_attempts[-MAX_ATTEMPTS_PER_KEY:]
        _prune_auth_state_locked(now)
        UNFLUSHED_FAIL2BAN_ATTEMPTS.append((ip, key or None, now))

    if len(UNFLUSHED_FAIL2BAN_ATTEMPTS) >= MAX_AUTH_TRACKED_IPS:
        _flush_fail2ban_buffer()

    _prune_fail2ban_database(now)



def is_rate_limited(ip, max_failed=None, window_seconds=None):
    config = get_fail2ban_config()
    if not config['enabled'] and max_failed is None and window_seconds is None:
        return False
    if max_failed is None:
        max_failed = config['max_attempts']
    if window_seconds is None:
        window_seconds = config['ban_time']

    now = time.time()
    cutoff = now - window_seconds

    with FAILED_AUTH_LOCK:
        mem_attempts = [t for t in FAILED_AUTH_ATTEMPTS.get(ip, []) if t > cutoff]
        FAILED_AUTH_ATTEMPTS[ip] = mem_attempts
        if len(mem_attempts) >= max_failed:
            return True

    try:
        with database() as connection:
            row = connection.execute(
                'SELECT COUNT(*) FROM fail2ban_attempts WHERE ip = ? AND created_at > ?',
                (ip, cutoff)
            ).fetchone()
            if row and row[0] >= max_failed:
                return True
    except Exception:
        pass

    return False


def is_account_rate_limited(account, max_failed=None, window_seconds=3600):
    """Limit failures for one account across all source addresses."""
    key = account_key(account)
    if not key:
        return False
    config = get_fail2ban_config()
    if max_failed is None:
        max_failed = max(50, config['max_attempts'] * 5)
    now = time.time()
    cutoff = now - window_seconds
    with FAILED_AUTH_LOCK:
        attempts = [t for t in ACCOUNT_FAILURES.get(key, []) if t > cutoff]
        ACCOUNT_FAILURES[key] = attempts
        return len(attempts) >= max_failed


def unban_ip(ip):
    ip = str(ip or '').strip()
    if not ip:
        return False

    with FAILED_AUTH_LOCK:
        mem_found = ip in FAILED_AUTH_ATTEMPTS
        FAILED_AUTH_ATTEMPTS.pop(ip, None)
        for account_key_value in tuple(k for k in FAILED_AUTH_ACCOUNTS if k[0] == ip):
            FAILED_AUTH_ACCOUNTS.pop(account_key_value, None)

    db_found = False
    try:
        with database() as connection:
            cursor = connection.execute('DELETE FROM fail2ban_attempts WHERE ip = ?', (ip,))
            db_found = cursor.rowcount > 0
    except Exception:
        pass

    return mem_found or db_found

def clear_failed_auth(ip, account=None):
    """Reset the failed authentication counter after a successful login.

    When ``account`` is provided, only the failures recorded for that account are
    removed, so an attacker cannot reset the per-IP budget by logging into an
    unrelated account of their own. When ``account`` is omitted the whole IP counter
    is cleared (used by the admin "unban" tooling and by existing callers).
    """
    ip = str(ip or '').strip()
    if not ip:
        return

    key = account_key(account)
    if key:
        with FAILED_AUTH_LOCK:
            FAILED_AUTH_ACCOUNTS.pop((ip, key), None)
            ACCOUNT_FAILURES.pop(key, None)
        try:
            with database() as connection:
                connection.execute(
                    'DELETE FROM fail2ban_attempts WHERE ip = ? AND account = ?', (ip, key)
                )
        except Exception:
            pass
        return

    with FAILED_AUTH_LOCK:
        FAILED_AUTH_ATTEMPTS.pop(ip, None)
        for account_key_value in tuple(k for k in FAILED_AUTH_ACCOUNTS if k[0] == ip):
            FAILED_AUTH_ACCOUNTS.pop(account_key_value, None)

    try:
        with database() as connection:
            connection.execute('DELETE FROM fail2ban_attempts WHERE ip = ?', (ip,))
    except Exception:
        pass

def unban_all():
    with FAILED_AUTH_LOCK:
        mem_count = len(FAILED_AUTH_ATTEMPTS)
        FAILED_AUTH_ATTEMPTS.clear()
        FAILED_AUTH_ACCOUNTS.clear()
        ACCOUNT_FAILURES.clear()

    db_count = 0
    try:
        with database() as connection:
            cursor = connection.execute('DELETE FROM fail2ban_attempts')
            db_count = cursor.rowcount
    except Exception:
        pass

    return max(mem_count, db_count)

def get_banned_ips():
    config = get_fail2ban_config()
    max_failed = config['max_attempts']
    window_seconds = config['ban_time']
    now = time.time()
    cutoff = now - window_seconds

    ip_attempts = {}

    with FAILED_AUTH_LOCK:
        for ip, attempts in FAILED_AUTH_ATTEMPTS.items():
            valid = [t for t in attempts if t > cutoff]
            if valid:
                ip_attempts[ip] = set(valid)

    try:
        with database() as connection:
            rows = connection.execute(
                'SELECT ip, created_at FROM fail2ban_attempts WHERE created_at > ? '
                'ORDER BY created_at DESC LIMIT 10000',
                (cutoff,)
            ).fetchall()
            for row in rows:
                ip = row['ip']
                t = row['created_at']
                if ip not in ip_attempts:
                    ip_attempts[ip] = set()
                ip_attempts[ip].add(t)
    except Exception:
        pass

    banned_list = []
    for ip, attempts in ip_attempts.items():
        if len(attempts) > 0:
            last_t = max(attempts)
            banned_list.append({
                'ip': ip,
                'attempts': len(attempts),
                'isBanned': len(attempts) >= max_failed,
                'lastAttempt': datetime.fromtimestamp(last_t, timezone.utc).isoformat()
            })

    banned_list.sort(key=lambda x: (x['isBanned'], x['lastAttempt']), reverse=True)
    return banned_list[:5000]

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

def parse_headers(header_str):
    headers = {}
    start = 0
    while True:
        end = header_str.find('\r\n', start)
        line = header_str[start:end] if end != -1 else header_str[start:]
        if ': ' in line:
            name, value = line.split(': ', 1)
            headers[name.lower()] = value
        if end == -1:
            break
        start = end + 2
    return headers

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
            headers = parse_headers(header_str)
            name = None
            if 'content-disposition' in headers:
                _, params = parse_header_params(headers['content-disposition'])
                name = params.get('name')
            if name:
                fields.setdefault(name, []).append(body)
    return fields

def _prune_and_store(store, key, value, max_entries):
    """Store an expiring item in an in-memory map, evicting stale and oldest entries.

    The maps backing passkey challenges and temporary 2FA tokens are populated by
    unauthenticated requests, so they must stay bounded to avoid a memory-exhaustion
    denial of service.
    """
    now = utc_now()
    # Dict preserves insertion order, and expiresAt is monotonically increasing,
    # so we only need to check from the oldest elements to find expired ones.
    while store:
        oldest_k = next(iter(store))
        if store[oldest_k]['expiresAt'] < now:
            del store[oldest_k]
        else:
            break

    # Evict the oldest entries once the cap is reached.
    while len(store) >= max_entries:
        oldest = next(iter(store), None)
        if oldest is None:
            break
        del store[oldest]
    store[key] = value

def generate_passkey_challenge(ip=None):
    challenge_token = secrets.token_hex(16)
    challenge_bytes = secrets.token_bytes(32)
    expires_at = utc_now() + timedelta(minutes=5)
    with PASSKEY_CHALLENGES_LOCK:
        if ip:
            now = utc_now()
            expired_ip = tuple(k for k, v in PASSKEY_CHALLENGES.items() if v.get('ip') == ip and v['expiresAt'] < now)
            for k in expired_ip:
                del PASSKEY_CHALLENGES[k]
            ip_challenges = tuple(k for k, v in PASSKEY_CHALLENGES.items() if v.get('ip') == ip)
            if len(ip_challenges) >= 10:
                oldest_ip_key = ip_challenges[0]
                del PASSKEY_CHALLENGES[oldest_ip_key]
        _prune_and_store(
            PASSKEY_CHALLENGES, challenge_token,
            {'challenge': challenge_bytes, 'expiresAt': expires_at, 'ip': ip},
            MAX_PASSKEY_CHALLENGES,
        )
    return {
        'challengeId': challenge_token,
        'challengeBase64': base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('='),
        'allowCredentials': []
    }

def create_temp_2fa_token(user_id):
    token = secrets.token_urlsafe(32)
    expires_at = utc_now() + timedelta(minutes=5)
    with TEMP_2FA_LOCK:
        _prune_and_store(
            TEMP_2FA_TOKENS, token,
            {'userId': user_id, 'expiresAt': expires_at},
            MAX_TEMP_2FA_TOKENS,
        )
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

def compute_totp_code(secret_b32, time_step=TOTP_PERIOD_SECONDS, counter=None):
    if counter is None:
        counter = int(time.time() // time_step)
    secret_b32 = str(secret_b32 or '').strip().upper()
    missing_padding = len(secret_b32) % 8
    if missing_padding:
        secret_b32 += '=' * (8 - missing_padding)
    key = base64.b32decode(secret_b32, casefold=True)
    msg = struct.pack('>Q', counter)
    hmac_hash = hmac.new(key, msg, hashlib.sha256).digest()
    offset = hmac_hash[-1] & 0x0f
    binary = struct.unpack('>I', hmac_hash[offset:offset+4])[0] & 0x7fffffff
    code = binary % (10 ** TOTP_DIGITS)
    return f'{code:0{TOTP_DIGITS}d}'

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

def verify_totp_counter(secret_b32, code, time_step=TOTP_PERIOD_SECONDS, window=TOTP_CLOCK_WINDOW):
    """Return the matched TOTP counter, or None when the code is invalid.

    Returning the counter lets callers persist it and reject a replay of the same
    code, including a code from an adjacent accepted time window.
    """
    code = str(code or '').strip()
    if not code.isdigit() or len(code) != TOTP_DIGITS:
        return None
    current_counter = int(time.time() // time_step)

    try:
        secret_b32 = str(secret_b32 or '').strip().upper()
        missing_padding = len(secret_b32) % 8
        if missing_padding:
            secret_b32 += '=' * (8 - missing_padding)
        key = base64.b32decode(secret_b32, casefold=True)
    except Exception:
        return None

    for i in range(-window, window + 1):
        try:
            counter = current_counter + i
            msg = struct.pack('>Q', counter)
            hmac_hash = hmac.new(key, msg, hashlib.sha256).digest()
            offset = hmac_hash[-1] & 0x0f
            binary = struct.unpack('>I', hmac_hash[offset:offset+4])[0] & 0x7fffffff
            generated_code = f'{binary % 1_000_000:06d}'
            if hmac.compare_digest(generated_code, code):
                return counter
        except Exception:
            pass
    return None


def verify_totp_code(secret_b32, code, time_step=30, window=1):
    return verify_totp_counter(secret_b32, code, time_step, window) is not None


def generate_backup_codes(count=8):
    """Generate high-entropy one-time recovery codes (96 bits each)."""
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(12).upper()
        codes.append('-'.join(raw[index:index + 4] for index in range(0, len(raw), 4)))
    return codes


def normalize_backup_code(code):
    return re.sub(r'[^A-Z0-9]', '', str(code or '').upper())


def hash_backup_code(code):
    normalized = normalize_backup_code(code)
    return 'sha256$' + hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def verify_backup_code(code, stored_code):
    """Verify a hashed recovery code and reject legacy plaintext values."""
    stored_code = str(stored_code or '')
    if not stored_code:
        return False
    normalized = normalize_backup_code(code)
    if not normalized:
        return False
    if stored_code.startswith('sha256$'):
        expected = stored_code.split('$', 1)[1]
        actual = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        return hmac.compare_digest(actual, expected)
    # PBKDF2 hashes from older releases remain usable until the user rotates their
    # codes, but plaintext values are no longer accepted.
    if stored_code.startswith('pbkdf2_sha256$'):
        return verify_password(normalized, stored_code)
    return False


def parse_version(version_str):
    import re
    match = re.match(r'^v?([0-9]+(?:\.[0-9]+)*)', version_str.strip())
    if match:
        return tuple(map(int, match.group(1).split('.')))
    return (0, 0, 0)


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




def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_time(value=None):
    return (value or utc_now()).isoformat()


def backup_directory():
    return Path(os.environ.get('NOTKI_BACKUP_DIR') or DB_PATH.parent / 'backups')

def get_backup_password():
    return os.environ.get('NOTKI_BACKUP_PASSWORD') or GENERATED_BACKUP_PASSWORD



def totp_is_active(value):
    """Return whether a user has an active TOTP factor."""
    if not value:
        return False
    return not value.startswith('pending:')


def validate_totp_secret(value):
    """Validate a Base32 TOTP secret before it is stored or restored.

    Returns the normalized secret (without the internal ``pending:`` marker) or
    raises ``ValueError``. This prevents malformed or unbounded values from being
    written into the database through a backup import.
    """
    if not isinstance(value, str):
        raise ValueError('invalid TOTP secret')
    secret = value.strip().upper()
    if len(secret) < 16 or len(secret) > 128:
        raise ValueError('invalid TOTP secret length')
    if any(character not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=' for character in secret):
        raise ValueError('invalid TOTP secret alphabet')
    padded = secret + '=' * ((8 - len(secret) % 8) % 8)
    try:
        raw = base64.b32decode(padded, casefold=True)
    except Exception as error:  # binascii.Error / ValueError
        raise ValueError('invalid TOTP secret encoding') from error
    if len(raw) < 10:
        raise ValueError('TOTP secret is too short')
    return secret.rstrip('=')


_BACKUP_OPERATION_LOCK = threading.Lock()


@contextmanager
def backup_operation():
    """Serialize backup creation and restore.

    Concurrent export/restore operations could otherwise capture or apply
    partially-updated state. A non-blocking lock fails fast with a safe response
    instead of piling up admin requests.
    """
    if not _BACKUP_OPERATION_LOCK.acquire(blocking=False):
        raise APIError('Another backup or restore operation is already running.', 409)
    try:
        yield
    finally:
        _BACKUP_OPERATION_LOCK.release()


def _b64encode(value):
    return base64.b64encode(value).decode('ascii')


def _b64decode(value, field):
    if not isinstance(value, str) or not value:
        raise APIError('The backup file has an invalid structure.')
    try:
        return base64.b64decode(value.encode('ascii'), validate=True)
    except Exception as error:
        raise APIError('The backup file has an invalid structure.') from error


def derive_backup_key(password, salt, n, r, p):
    """Derive a 256-bit backup key with scrypt using bounded parameters."""
    if not isinstance(password, str) or not password:
        raise APIError('A backup password is required.', 400)
    if len(password) > BACKUP_PASSWORD_MAX_LENGTH:
        raise APIError('The backup password is too long.')
    if (not isinstance(n, int) or isinstance(n, bool) or not isinstance(r, int)
            or isinstance(r, bool) or not isinstance(p, int) or isinstance(p, bool)):
        raise APIError('The backup file has invalid key-derivation parameters.')
    if n < BACKUP_KDF_MIN_N or n > BACKUP_KDF_MAX_N or n & (n - 1):
        raise APIError('The backup file has invalid key-derivation parameters.')
    if r < 1 or r > BACKUP_KDF_MAX_R or p < 1 or p > BACKUP_KDF_MAX_P:
        raise APIError('The backup file has invalid key-derivation parameters.')
    # Reject expensive parameters before allocating memory (DoS protection).
    if 128 * n * r + 128 * r * p > BACKUP_KDF_MAXMEM:
        raise APIError('The backup file has invalid key-derivation parameters.')
    try:
        password_bytes = bytearray(password.encode('utf-8'))
    except UnicodeEncodeError as error:
        raise APIError('The backup password is invalid.') from error
    try:
        return hashlib.scrypt(
            bytes(password_bytes), salt=salt, n=n, r=r, p=p,
            dklen=BACKUP_KEY_BYTES, maxmem=BACKUP_KDF_MAXMEM,
        )
    except (ValueError, MemoryError, OSError) as error:
        raise APIError('The backup file has invalid key-derivation parameters.') from error
    finally:
        for index in range(len(password_bytes)):
            password_bytes[index] = 0


def _backup_header_aad(header):
    return json.dumps(header, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def encrypt_backup(snapshot, password):
    """Serialize, encrypt, and authenticate a snapshot into one backup file.

    The returned bytes are a self-contained JSON document. All cryptographic
    parameters are authenticated as AES-GCM additional authenticated data, so
    modifying the header invalidates the tag as well.
    """
    if not isinstance(password, str) or not password:
        raise APIError('A backup password is required.', 400)
    if len(password) < BACKUP_PASSWORD_MIN_LENGTH:
        raise APIError('The backup password must be at least 12 characters long.')
    if len(password) > BACKUP_PASSWORD_MAX_LENGTH:
        raise APIError('The backup password is too long.')
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception as error:
        raise APIError('Backup encryption is unavailable.', 500) from error

    plaintext = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(plaintext) > MAX_SNAPSHOT_BYTES:
        raise APIError('The snapshot exceeds the 100 MB limit.', 413)

    salt = secrets.token_bytes(BACKUP_SALT_BYTES)
    nonce = secrets.token_bytes(BACKUP_NONCE_BYTES)
    header = {
        'format': BACKUP_FORMAT,
        'version': BACKUP_FORMAT_VERSION,
        'createdAt': iso_time(),
        'kdf': {
            'algorithm': BACKUP_KDF_ALGORITHM,
            'salt': _b64encode(salt),
            'n': BACKUP_KDF_N,
            'r': BACKUP_KDF_R,
            'p': BACKUP_KDF_P,
        },
        'cipher': {
            'algorithm': 'AES-256-GCM',
            'nonce': _b64encode(nonce),
        },
    }
    key = derive_backup_key(password, salt, BACKUP_KDF_N, BACKUP_KDF_R, BACKUP_KDF_P)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _backup_header_aad(header))
    document = dict(header)
    document['ciphertext'] = _b64encode(ciphertext)
    encoded = json.dumps(document, ensure_ascii=False, indent=2).encode('utf-8')
    if len(encoded) > MAX_BACKUP_FILE_BYTES:
        raise APIError('The backup file exceeds the size limit.', 413)
    return encoded


def _parse_backup_document(raw_bytes, max_file_bytes=None):
    if max_file_bytes is None:
        max_file_bytes = MAX_BACKUP_FILE_BYTES
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise APIError('The backup file has an invalid structure.')
    if not raw_bytes:
        raise APIError('The backup archive cannot be read.')
    if len(raw_bytes) > max_file_bytes:
        raise APIError('The backup file exceeds the size limit.', 413)
    try:
        document = json.loads(bytes(raw_bytes).decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, MemoryError) as error:
        raise APIError('The backup archive cannot be read.') from error
    if not isinstance(document, dict):
        raise APIError('The backup file has an invalid structure.')
    return document


def decrypt_backup(raw_bytes, password, *, max_file_bytes=None,
                   max_snapshot_bytes=None):
    """Decrypt and authenticate a version-2 backup file.

    ``max_file_bytes`` and ``max_snapshot_bytes`` let the offline CLI restore accept
    archives larger than the HTTP upload limit without weakening web endpoints.
    """
    if max_file_bytes is None:
        max_file_bytes = MAX_BACKUP_FILE_BYTES
    if max_snapshot_bytes is None:
        max_snapshot_bytes = MAX_SNAPSHOT_BYTES
    if not isinstance(password, str) or not password:
        raise APIError('A backup password is required.', 400)
    if len(password) > BACKUP_PASSWORD_MAX_LENGTH:
        raise APIError('The backup password is too long.')
    document = _parse_backup_document(raw_bytes, max_file_bytes=max_file_bytes)
    backup_format = document.get('format')
    if backup_format != BACKUP_FORMAT:
        raise APIError('The file is not a valid Notki backup.')
    version = document.get('version')
    if (isinstance(version, bool) or not isinstance(version, int)
            or version != BACKUP_FORMAT_VERSION):
        raise APIError('Unsupported backup format version.')
    expected = {'format', 'version', 'createdAt', 'kdf', 'cipher', 'ciphertext'}
    if set(document) != expected:
        raise APIError('The backup file has an invalid structure.')
    kdf = document.get('kdf')
    cipher = document.get('cipher')
    if not isinstance(kdf, dict) or set(kdf) != {'algorithm', 'salt', 'n', 'r', 'p'}:
        raise APIError('The backup file has invalid key-derivation parameters.')
    if kdf.get('algorithm') != BACKUP_KDF_ALGORITHM:
        raise APIError('The backup file uses an unsupported key-derivation algorithm.')
    if not isinstance(cipher, dict) or set(cipher) != {'algorithm', 'nonce'}:
        raise APIError('The backup file has an invalid structure.')
    if cipher.get('algorithm') != 'AES-256-GCM':
        raise APIError('The backup file uses an unsupported cipher.')
    created_at = document.get('createdAt')
    if not isinstance(created_at, str) or len(created_at) > 64:
        raise APIError('The backup file has an invalid structure.')

    salt = _b64decode(kdf.get('salt'), 'salt')
    nonce = _b64decode(cipher.get('nonce'), 'nonce')
    ciphertext = _b64decode(document.get('ciphertext'), 'ciphertext')
    if len(salt) != BACKUP_SALT_BYTES or len(nonce) != BACKUP_NONCE_BYTES or not ciphertext:
        raise APIError('The backup file has an invalid structure.')
    if len(ciphertext) > max_file_bytes:
        raise APIError('The backup file exceeds the size limit.', 413)

    key = derive_backup_key(password, salt, kdf.get('n'), kdf.get('r'), kdf.get('p'))
    header = {
        'format': document['format'],
        'version': document['version'],
        'createdAt': document['createdAt'],
        'kdf': kdf,
        'cipher': cipher,
    }
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _backup_header_aad(header))
    except Exception as error:
        # Wrong password, modified ciphertext, bad tag and altered metadata all
        # produce the same safe response.
        raise APIError('Invalid backup password or corrupt backup.', 400) from error
    if len(plaintext) > max_snapshot_bytes:
        raise APIError('The snapshot exceeds the size limit.', 413)
    try:
        snapshot = json.loads(plaintext.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, MemoryError) as error:
        raise APIError('The backup archive cannot be read.') from error
    if not isinstance(snapshot, dict):
        raise APIError('The file is not a valid Notki server snapshot.')
    return snapshot


def write_backup_file(data):
    """Atomically write an encrypted backup with restrictive permissions."""
    created_at = utc_now()
    filename = f"notki-backup-{created_at.strftime('%Y%m%d-%H%M%SZ')}-{secrets.token_hex(4)}.enc"
    backup_dir = backup_directory()
    try:
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(backup_dir, 0o700)
        except OSError:
            pass
        descriptor, temporary_path = tempfile.mkstemp(dir=backup_dir, prefix='.tmp-', suffix='.tmp')
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.chmod(temporary_path, 0o600)
            except OSError:
                pass
            backup_path = backup_dir / filename
            os.replace(temporary_path, backup_path)
        except Exception:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
            raise
    except OSError as error:
        raise APIError('Could not save the backup on the server.', 500) from error
    return filename, created_at, backup_path


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


SCHEMA_SQL = '''
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
                expires_at TEXT NOT NULL,
                last_seen_at TEXT,
                authenticated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS invites (
                token_hash TEXT PRIMARY KEY,
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
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
                created_at TEXT NOT NULL,
                sign_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS passkeys_user_idx ON passkeys(user_id);
            CREATE TABLE IF NOT EXISTS fail2ban_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                account TEXT,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS fail2ban_ip_idx ON fail2ban_attempts(ip);
        '''

def initialize_database():
    with database() as connection:
        connection.execute('PRAGMA journal_mode = WAL')
        connection.execute('PRAGMA synchronous = NORMAL')
        connection.executescript(SCHEMA_SQL)
        fail2ban_columns = {row['name'] for row in connection.execute('PRAGMA table_info(fail2ban_attempts)')}
        if 'account' not in fail2ban_columns:
            try:
                connection.execute('ALTER TABLE fail2ban_attempts ADD COLUMN account TEXT')
            except sqlite3.OperationalError:
                pass
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(users)')}
        if 'avatar' not in columns:
            connection.execute('ALTER TABLE users ADD COLUMN avatar TEXT')
        if 'labels_json' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN labels_json TEXT NOT NULL DEFAULT '[]'")
        if 'totp_secret' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT")
        if 'backup_codes_json' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN backup_codes_json TEXT")
        if 'totp_last_used_step' not in columns:
            connection.execute('ALTER TABLE users ADD COLUMN totp_last_used_step INTEGER')

        session_columns = {row['name'] for row in connection.execute('PRAGMA table_info(sessions)')}
        if 'last_seen_at' not in session_columns:
            connection.execute('ALTER TABLE sessions ADD COLUMN last_seen_at TEXT')
            connection.execute('UPDATE sessions SET last_seen_at = ? WHERE last_seen_at IS NULL', (iso_time(),))
        if 'authenticated_at' not in session_columns:
            connection.execute('ALTER TABLE sessions ADD COLUMN authenticated_at TEXT')

        invite_foreign_keys = connection.execute('PRAGMA foreign_key_list(invites)').fetchall()
        if any(row['table'] == 'users' and row['on_delete'] != 'SET NULL' for row in invite_foreign_keys):
            connection.execute('''
                CREATE TABLE invites_new (
                    token_hash TEXT PRIMARY KEY,
                    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                )
            ''')
            connection.execute('''
                INSERT INTO invites_new (token_hash, created_by, created_at, expires_at, used_at)
                SELECT token_hash, created_by, created_at, expires_at, used_at FROM invites
            ''')
            connection.execute('DROP TABLE invites')
            connection.execute('ALTER TABLE invites_new RENAME TO invites')

        note_columns = {row['name'] for row in connection.execute('PRAGMA table_info(notes)')}
        if 'due_date' not in note_columns:
            connection.execute('ALTER TABLE notes ADD COLUMN due_date TEXT')

        passkey_columns = {row['name'] for row in connection.execute('PRAGMA table_info(passkeys)')}
        if 'sign_count' not in passkey_columns:
            try:
                connection.execute('ALTER TABLE passkeys ADD COLUMN sign_count INTEGER NOT NULL DEFAULT 0')
            except sqlite3.OperationalError:
                pass



def password_needs_rehash(encoded):
    try:
        parts = encoded.split('$')
        if parts[0] != 'scrypt':
            return True
        _, n, r, p, _, _ = parts
        if int(n) != SCRYPT_N or int(r) != SCRYPT_R or int(p) != SCRYPT_P:
            return True
        return False
    except Exception:
        return False


def verify_password(password, encoded):
    try:
        parts = encoded.split('$')
        if parts[0] == 'scrypt':
            _, n, r, p, salt_hex, expected_hex = parts
            actual = hashlib.scrypt(
                password.encode('utf-8'), salt=bytes.fromhex(salt_hex),
                n=int(n), r=int(r), p=int(p), maxmem=1024**3
            )
            return hmac.compare_digest(actual.hex(), expected_hex)
        elif parts[0] == 'pbkdf2_sha256':
            _, iterations, salt_hex, expected_hex = parts
            actual = hashlib.pbkdf2_hmac(
                'sha256', password.encode('utf-8'), bytes.fromhex(salt_hex), int(iterations)
            )
            return hmac.compare_digest(actual.hex(), expected_hex)
        return False
    except (ValueError, TypeError, AttributeError):
        return False


EMAIL_LOCAL_PATTERN = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+$")
EMAIL_DOMAIN_LABEL_PATTERN = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$')


def normalize_email(value):
    if not isinstance(value, str):
        raise ValueError('Enter a valid e-mail address.')
    email = value.strip().lower()
    if not email or len(email) > 254 or email.count('@') != 1:
        raise ValueError('Enter a valid e-mail address.')
    if any(ord(character) < 32 or ord(character) == 127 for character in email):
        raise ValueError('Enter a valid e-mail address.')
    if any(character in '<>"\\' or character.isspace() for character in email):
        raise ValueError('Enter a valid e-mail address.')
    local, domain = email.split('@')
    if (not local or len(local) > 64 or '.' not in domain or len(domain) > 253
            or local.startswith('.') or local.endswith('.') or '..' in local
            or not EMAIL_LOCAL_PATTERN.fullmatch(local)):
        raise ValueError('Enter a valid e-mail address.')
    labels = domain.split('.')
    if len(labels) < 2 or any(not label or not EMAIL_DOMAIN_LABEL_PATTERN.fullmatch(label) for label in labels):
        raise ValueError('Enter a valid e-mail address.')
    if not labels[-1].isalpha() or len(labels[-1]) < 2:
        raise ValueError('Enter a valid e-mail address.')
    return email


def public_user(row, connection=None):
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

    has_totp = False
    has_passkey = False
    require_2fa = False

    has_totp_col = False
    totp_secret = None
    try:
        totp_secret = row['totp_secret']
        has_totp_col = True
    except (IndexError, KeyError):
        pass

    def check_user_2fa(conn):
        nonlocal has_totp, has_passkey, require_2fa
        if has_totp_col:
            ts = totp_secret
            # A stored but undecryptable secret must not downgrade the account to
            # password-only authentication.
            has_totp = bool(ts and not ts.startswith('pending:')) or bool(totp_secret and ts is None)
            res = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM passkeys WHERE user_id = ?), "
                "(SELECT value FROM settings WHERE key = 'require2FA')",
                (row['id'],)
            ).fetchone()
            if res:
                has_passkey = bool(res[0])
                require_2fa = bool(res[1] and res[1] == 'true')
        else:
            res = conn.execute(
                "SELECT totp_secret, "
                "EXISTS(SELECT 1 FROM passkeys WHERE user_id = ?), "
                "(SELECT value FROM settings WHERE key = 'require2FA') "
                "FROM users WHERE id = ?",
                (row['id'], row['id'])
            ).fetchone()
            if res:
                ts = res['totp_secret']
                has_totp = bool(ts and not ts.startswith('pending:')) or bool(res['totp_secret'] and ts is None)
                has_passkey = bool(res[1])
                require_2fa = bool(res[2] and res[2] == 'true')

    try:
        if connection:
            check_user_2fa(connection)
        else:
            with database() as conn:
                check_user_2fa(conn)
    except Exception:
        with database() as conn:
            check_user_2fa(conn)

    has_2fa = has_totp or has_passkey
    must_setup_2fa = require_2fa and not has_2fa

    return {
        'id': row['id'], 'email': row['email'], 'isAdmin': row['role'] == 'admin',
        'createdAt': row['created_at'], 'avatar': avatar,
        'labels': labels, 'has2FA': has_2fa, 'mustSetup2FA': must_setup_2fa
    }


def create_admin_account():
    initialize_database()
    with database() as connection:
        if connection.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone():
            print('Administrator account already exists.')
            return
    try:
        email = normalize_email(input('Admin email: '))
        password = getpass.getpass('Password (minimum 12 characters): ')
        confirmation = getpass.getpass('Confirm password: ')
        if len(password) < 12:
            raise ValueError('The password must be at least 12 characters long.')
        if password != confirmation:
            raise ValueError('The passwords do not match.')
        with database() as connection:
            connection.execute(
                'INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)',
                (email, hash_password(password), 'admin', iso_time()),
            )
        print(f'Administrator account {email} created successfully.')
    except (ValueError, sqlite3.IntegrityError) as error:
        print(f'Failed to create administrator account: {error}', file=sys.stderr)
        raise SystemExit(1) from error


def disable_user_2fa_cli(identifier):
    initialize_database()
    identifier = (identifier or '').strip()
    if not identifier:
        print('Please provide a user email or ID.', file=sys.stderr)
        raise SystemExit(1)

    with database() as connection:
        user = None
        if identifier.isdigit():
            user = connection.execute('SELECT id, email FROM users WHERE id = ?', (int(identifier),)).fetchone()
        if not user:
            email = normalize_email(identifier)
            user = connection.execute('SELECT id, email FROM users WHERE email = ?', (email,)).fetchone()

        if not user:
            print(f'User "{identifier}" not found.', file=sys.stderr)
            raise SystemExit(1)

        connection.execute('UPDATE users SET totp_secret = NULL, backup_codes_json = NULL WHERE id = ?', (user['id'],))
        connection.execute('DELETE FROM passkeys WHERE user_id = ?', (user['id'],))
        print(f'Disabled 2FA for user {user["email"]} (ID: {user["id"]}).')


def disable_all_2fa_cli():
    initialize_database()
    with database() as connection:
        connection.execute('UPDATE users SET totp_secret = NULL, backup_codes_json = NULL')
        connection.execute('DELETE FROM passkeys')
        connection.execute("INSERT INTO settings (key, value) VALUES ('require2FA', 'false') ON CONFLICT(key) DO UPDATE SET value = 'false'")
    with TEMP_2FA_LOCK:
        TEMP_2FA_TOKENS.clear()
    print('Disabled 2FA server-wide for all users.')


def unban_ip_cli(ip):
    initialize_database()
    ip = str(ip or '').strip()
    if not ip:
        print('Please provide an IP address.', file=sys.stderr)
        raise SystemExit(1)
    unbanned = unban_ip(ip)
    if unbanned:
        print(f'Unbanned IP {ip}.')
    else:
        print(f'IP {ip} was not found in banned list.')


def unban_all_cli():
    initialize_database()
    count = unban_all()
    print(f'Unbanned all IPs ({count} unbanned).')


class APIError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class NotkiHandler(BaseHTTPRequestHandler):
    server_version = 'NotkiServer'
    sys_version = ''
    timeout = REQUEST_TIMEOUT_SECONDS

    def version_string(self):
        # Do not disclose the exact Notki or Python version in the Server header.
        return self.server_version

    def end_headers(self):
        # Security headers to mitigate Clickjacking, MIME-sniffing, and cross-origin leaks
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none';")
        if self.get_forwarded_proto() == 'https' or os.environ.get('NOTKI_COOKIE_SECURE') == '1':
            self.send_header('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        super().end_headers()

    @property
    def language(self):
        return parse_language(self.headers.get('Accept-Language'))

    def error_message(self, message):
        return message

    def send_error_json(self, message, status=400):
        self.send_json({'error': self.error_message(message)}, status)

    def send_json(self, payload, status=200, extra_headers=()):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            for name, value in extra_headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

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

    def is_trusted_proxy(self):
        """Return True when the peer may set client-identifying proxy headers.

        ``NOTKI_TRUST_PROXY`` accepts boolean values ('1', 'true', 'yes', 'all', '*'),
        explicit disable values ('0', 'false', 'no'), or a comma-separated list of
        proxy IPs/subnets. When unset, only loopback peers are trusted.
        """
        trust_proxy = os.environ.get('NOTKI_TRUST_PROXY', '').strip().lower()
        if trust_proxy in ('0', 'false', 'no'):
            return False
        if trust_proxy in ('1', 'true', 'yes', 'all', '*'):
            return True
        try:
            peer = ipaddress.ip_address(self.client_address[0].split('%', 1)[0])
        except ValueError:
            return False

        networks = _get_trusted_proxy_networks(trust_proxy)
        for network in networks:
            if peer in network:
                return True
        return False

    def trusted_proxy_networks(self):
        trust_proxy = os.environ.get('NOTKI_TRUST_PROXY', '').strip().lower()
        return _get_trusted_proxy_networks(trust_proxy)

    def is_trusted_address(self, value):
        try:
            address = ipaddress.ip_address(str(value).split('%', 1)[0])
        except ValueError:
            return False
        return any(address in network for network in self.trusted_proxy_networks())

    def get_client_ip(self):
        """Return the client IP using the trusted proxy chain from right to left.

        The rightmost untrusted address is the only value a trusted proxy cannot
        have supplied itself. Taking the leftmost X-Forwarded-For entry (the old
        behaviour) let an attacker rotate arbitrary values and bypass rate limits.
        """
        peer = self.client_address[0]
        if not self.is_trusted_proxy():
            return peer

        xff_values = [value.strip() for value in self.headers.get('X-Forwarded-For', '').split(',') if value.strip()]
        forwarded_nodes = parse_forwarded_for(self.headers.get('Forwarded'))
        chain = xff_values or forwarded_nodes
        if not chain:
            real_ip = self.headers.get('X-Real-IP', '').strip()
            if real_ip:
                chain = [real_ip]

        if not chain:
            return peer

        trust_proxy = os.environ.get('NOTKI_TRUST_PROXY', '').strip().lower()
        if trust_proxy in ('1', 'true', 'yes', 'all', '*'):
            candidate = chain[0]
            try:
                return str(ipaddress.ip_address(candidate.split('%', 1)[0]))
            except ValueError:
                return peer

        for candidate in reversed(chain):
            if not self.is_trusted_address(candidate):
                try:
                    return str(ipaddress.ip_address(candidate.split('%', 1)[0]))
                except ValueError:
                    return peer
        return peer

    def get_forwarded_host(self):
        """Return the host to use when building links.

        A configured ``NOTKI_PUBLIC_HOST`` always wins. Otherwise proxy headers are
        honoured only from trusted peers and only when the resulting hostname passes
        the optional ``NOTKI_ALLOWED_HOSTS`` allowlist.
        """
        if PUBLIC_HOST:
            if PUBLIC_HOST.startswith(('http://', 'https://')):
                return urlsplit(PUBLIC_HOST).netloc or PUBLIC_HOST
            return PUBLIC_HOST

        candidate = None
        if self.is_trusted_proxy():
            candidate = self.headers.get('X-Forwarded-Host')
            if not candidate:
                candidate = parse_forwarded_host(self.headers.get('Forwarded'))
        if candidate:
            candidate = candidate.split(',')[0].strip()
        else:
            candidate = self.headers.get('Host')

        if candidate and ALLOWED_HOSTS:
            hostname = (urlsplit(f"//{candidate}").hostname or '').lower()
            if hostname not in ALLOWED_HOSTS:
                return self.headers.get('Host')
        return candidate

    def get_forwarded_proto(self):
        proto = None
        if self.is_trusted_proxy():
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
        """Require a same-origin Origin/Referer for state-changing requests.

        Checking only the hostname allowed an HTTPS page to drive an HTTP origin
        (and vice versa), and accepting a missing header left non-browser clients
        outside the CSRF boundary.
        """
        source = self.headers.get('Origin') or self.headers.get('Referer')
        if not source:
            raise APIError('A cross-origin request was blocked.', 403)
        if source == 'null':
            raise APIError('A cross-origin request was blocked.', 403)

        source_parsed = urlsplit(source)
        expected_host = self.get_forwarded_host()
        if not expected_host or source_parsed.scheme not in ('http', 'https'):
            raise APIError('A cross-origin request was blocked.', 403)

        if PUBLIC_HOST.startswith(('http://', 'https://')):
            expected_scheme = urlsplit(PUBLIC_HOST).scheme
        else:
            expected_scheme = 'https' if self.get_forwarded_proto() == 'https' else 'http'
        if source_parsed.scheme != expected_scheme:
            raise APIError('A cross-origin request was blocked.', 403)

        expected_parsed = urlsplit(f'//{expected_host}')
        origin_hostname = (source_parsed.hostname or '').lower()
        expected_hostname = (expected_parsed.hostname or '').lower()
        if not origin_hostname or origin_hostname != expected_hostname:
            raise APIError('A cross-origin request was blocked.', 403)

        default_port = 443 if expected_scheme == 'https' else 80
        expected_port = expected_parsed.port or default_port
        source_port = source_parsed.port or default_port
        if source_port != expected_port:
            raise APIError('A cross-origin request was blocked.', 403)

    def has_admin(self):
        with database() as connection:
            return connection.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone() is not None

    def check_setup_permission(self):
        """Authorize first-run setup with the one-time setup token only.

        A loopback peer is not sufficient: reverse proxies and local port forwards
        can make a remote client appear local, which was the root cause of the
        original setup bypass.
        """
        expected_token = os.environ.get('NOTKI_SETUP_TOKEN') or GENERATED_SETUP_TOKEN
        provided_token = self.headers.get('X-Setup-Token', '')
        return bool(expected_token and provided_token and hmac.compare_digest(provided_token, expected_token))

    def send_redirect(self, path):
        try:
            self.send_response(302)
            self.send_header('Location', path)
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def get_session_token(self):
        cookie = cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except cookies.CookieError:
            return None
        for name in (HOST_SESSION_COOKIE, SESSION_COOKIE):
            if name in cookie:
                return cookie[name].value
        return None

    def current_user(self):
        token = self.get_session_token()
        if not token:
            return None
        now = utc_now()
        idle_cutoff = now - timedelta(hours=SESSION_IDLE_HOURS)
        with database() as connection:
            row = connection.execute('''
                SELECT users.id, users.email, users.role, users.created_at, users.avatar,
                       users.labels_json, sessions.last_seen_at
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                  AND (sessions.last_seen_at IS NULL OR sessions.last_seen_at > ?)
            ''', (token_hash(token), iso_time(now), iso_time(idle_cutoff))).fetchone()
            if not row:
                connection.execute('DELETE FROM sessions WHERE token_hash = ?', (token_hash(token),))
                return None
            last_seen = row['last_seen_at']
            try:
                last_seen_time = datetime.fromisoformat(last_seen) if last_seen else None
            except (TypeError, ValueError):
                last_seen_time = None
            if last_seen_time is None or now - last_seen_time > timedelta(minutes=1):
                connection.execute(
                    'UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?',
                    (iso_time(now), token_hash(token)),
                )
            return public_user(row, connection)

    def invalidate_user_sessions(self, user_id, keep_token=None):
        """Revoke every session for a user, optionally preserving the current one."""
        with database() as connection:
            if keep_token:
                connection.execute(
                    'DELETE FROM sessions WHERE user_id = ? AND token_hash != ?',
                    (user_id, token_hash(keep_token)),
                )
            else:
                connection.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))

    def require_user(self, admin=False):
        user = self.current_user()
        if not user:
            raise APIError('Sign in to continue.', 401)
        if admin and not user['isAdmin']:
            raise APIError('This section is available only to the administrator.', 403)

        # Enforce the global two-factor requirement for every role, including
        # administrators. Only the endpoints needed to complete 2FA setup (and to
        # inspect/log out the current session) stay reachable until setup is done.
        if user.get('mustSetup2FA'):
            with database() as connection:
                req_row = connection.execute("SELECT value FROM settings WHERE key = 'require2FA'").fetchone()
                require_2fa_enabled = req_row and req_row['value'] == 'true'

            if require_2fa_enabled:
                path = urlsplit(self.path).path
                allowed_paths = (
                    '/api/session', '/api/logout', '/api/account/2fa',
                    '/api/account/totp', '/api/account/totp/verify', '/api/account/passkey',
                )
                if path not in allowed_paths:
                    raise APIError('Two-factor authentication is required. Please configure it.', 403)

        return user

    def require_step_up(self, user):
        """Require fresh password + second-factor proof for sensitive actions."""
        password = self.headers.get('X-Step-Up-Password', '')
        second_factor = self.headers.get('X-Step-Up-Code', '')
        if not password:
            token = self.get_session_token()
            if token:
                with database() as connection:
                    session = connection.execute(
                        'SELECT authenticated_at FROM sessions WHERE token_hash = ? AND user_id = ?',
                        (token_hash(token), user['id']),
                    ).fetchone()
                if session and session['authenticated_at']:
                    try:
                        authenticated_at = datetime.fromisoformat(session['authenticated_at'])
                    except (TypeError, ValueError):
                        authenticated_at = None
                    if authenticated_at and utc_now() - authenticated_at <= timedelta(minutes=STEP_UP_WINDOW_MINUTES):
                        return
            raise APIError('Re-authentication required. Provide your password and second factor.', 403)
        with database() as connection:
            row = connection.execute(
                'SELECT password_hash, totp_secret, backup_codes_json, totp_last_used_step '
                'FROM users WHERE id = ?',
                (user['id'],),
            ).fetchone()
            password_valid = bool(row and verify_password(password, row['password_hash']))
            stored_secret = row['totp_secret'] if row else None
            secret = stored_secret if row else None
            # Fail closed if a configured secret cannot be decrypted.
            has_totp = bool(secret and not secret.startswith('pending:')) or bool(stored_secret and secret is None)
            second_factor_valid = not has_totp
            backup_codes = []
            if has_totp and second_factor and password_valid:
                counter = verify_totp_counter(secret, second_factor) if secret else None
                if counter is not None and (row['totp_last_used_step'] is None or counter > row['totp_last_used_step']):
                    cursor = connection.execute(
                        'UPDATE users SET totp_last_used_step = ? WHERE id = ? '
                        'AND (totp_last_used_step IS NULL OR totp_last_used_step < ?)',
                        (counter, user['id'], counter),
                    )
                    second_factor_valid = cursor.rowcount == 1
                if not second_factor_valid:
                    try:
                        backup_codes = json.loads(row['backup_codes_json']) if row['backup_codes_json'] else []
                    except (TypeError, json.JSONDecodeError):
                        backup_codes = []
                    for stored_code in list(backup_codes):
                        if verify_backup_code(second_factor, stored_code):
                            second_factor_valid = True
                            backup_codes.remove(stored_code)
                            connection.execute(
                                'UPDATE users SET backup_codes_json = ? WHERE id = ?',
                                (json.dumps(backup_codes), user['id']),
                            )
                            break
            if not password_valid or not second_factor_valid:
                record_failed_auth(self.get_client_ip(), user['email'])
                raise APIError('Re-authentication failed.', 403)

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

    def is_https_request(self):
        return (
            os.environ.get('NOTKI_COOKIE_SECURE') == '1'
            or self.get_forwarded_proto() == 'https'
        )

    def session_headers(self, token, max_age=None):
        """Build a hardened session cookie.

        HTTPS uses the ``__Host-`` prefix, which requires Secure, Path=/ and forbids
        a Domain attribute. Plain HTTP development keeps a non-prefixed cookie so
        local login still works.
        """
        if max_age is None:
            max_age = self.get_session_days() * 24 * 60 * 60
        is_https = self.is_https_request()
        cookie_name = HOST_SESSION_COOKIE if is_https else SESSION_COOKIE
        secure = '; Secure' if is_https else ''
        return [('Set-Cookie', f'{cookie_name}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}')]

    def new_session(self, user_id):
        token = secrets.token_urlsafe(32)
        days = self.get_session_days()
        with database() as connection:
            connection.execute('DELETE FROM sessions WHERE expires_at <= ?', (iso_time(),))
            connection.execute(
                'INSERT INTO sessions (token_hash, user_id, expires_at, last_seen_at, authenticated_at) VALUES (?, ?, ?, ?, ?)',
                (token_hash(token), user_id, iso_time(utc_now() + timedelta(days=days)), iso_time(), iso_time()),
            )
        return token

    def create_session_response(self, user_id):
        token = self.new_session(user_id)
        with database() as connection:
            user = connection.execute('SELECT id, email, role, created_at, avatar, labels_json FROM users WHERE id = ?', (user_id,)).fetchone()
            user_data = public_user(user, connection)
        self.send_json({'user': user_data}, 201, self.session_headers(token))

    def handle_setup_get(self, path):
        if path == '/api/setup/status':
            self.send_json({
                'needsSetup': not self.has_admin(),
                'usingGeneratedBackupPassword': not bool(os.environ.get('NOTKI_BACKUP_PASSWORD'))
            })
            return True
        elif path in ('/setup', '/setup.html'):
            if self.has_admin():
                self.send_redirect('/')
            else:
                # The page itself contains no secrets. The setup token is required
                # by every mutating setup endpoint.
                self.serve_static('setup.html')

    def handle_account_get(self, path):
        if path == '/api/session':
            with database() as connection:
                row = connection.execute("SELECT value FROM settings WHERE key = 'announcement'").fetchone()
                announcement = row['value'] if row and row['value'] else ''
            self.send_json({'user': self.current_user(), 'announcement': announcement})
            return True
        elif path == '/api/account/2fa':
            user = self.require_user()
            with database() as connection:
                row = connection.execute('SELECT totp_secret FROM users WHERE id = ?', (user['id'],)).fetchone()
                pk_rows = connection.execute('SELECT id, name, created_at FROM passkeys WHERE user_id = ? ORDER BY created_at DESC', (user['id'],)).fetchall()
            has_totp = bool(row and totp_is_active(row['totp_secret']))
            passkeys = [{'id': r['id'], 'name': r['name'], 'createdAt': r['created_at']} for r in pk_rows]
            self.send_json({'hasTotp': has_totp, 'passkeys': passkeys})
            return True
        return False

    def handle_notes_get(self, path):
        if path == '/api/notes':
            user = self.require_user()
            with database() as connection:
                rows = connection.execute('''
                    SELECT notes.*, COUNT(note_shares.note_id) AS share_count
                    FROM notes
                    LEFT JOIN note_shares ON notes.id = note_shares.note_id
                    WHERE notes.user_id = ?
                    GROUP BY notes.id
                    ORDER BY notes.sort_order DESC
                ''', (user['id'],)).fetchall()
                ann_row = connection.execute("SELECT value FROM settings WHERE key = 'announcement'").fetchone()
                announcement = ann_row['value'] if ann_row and ann_row['value'] else ''
            self.send_json({'notes': [self.note_from_row(row) for row in rows], 'announcement': announcement})
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
                    'has2FA': bool(totp_is_active(row['totp_secret']) or row['passkey_count'] > 0)
                } for row in users],
                'invites': [{'tokenHash': row['token_hash'], 'createdAt': row['created_at'], 'expiresAt': row['expires_at'], 'usedAt': row['used_at']} for row in invites],
                'usingGeneratedBackupPassword': not bool(os.environ.get('NOTKI_BACKUP_PASSWORD')),
            })
            return True
        elif path == '/api/admin/fail2ban':
            self.require_user(admin=True)
            self.send_json({'bannedIps': get_banned_ips(), 'config': get_fail2ban_config()})
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
            self.send_redirect('/setup')
            return True
        filename = 'index.html' if path in ('/', '/admin', '/admin.html') else path.lstrip('/')
        self.serve_static(filename)
        return True

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        try:
            handled = False
            if path == '/api/login/passkey/challenge':
                self.send_json(generate_passkey_challenge(ip=self.get_client_ip()))
                return
            if path == '/api/setup/status' or path in ('/setup', '/setup.html'):
                handled = self.handle_setup_get(path)
            elif path.startswith('/api/admin/'):
                handled = self.handle_admin_get(path)
            elif path.startswith('/api/notes') or path == '/api/shared':
                handled = self.handle_notes_get(path)
            elif path in ('/api/session', '/api/account/2fa'):
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
            except (ValueError, TypeError):
                content_length = 0
            if content_length > MAX_BACKUP_FILE_BYTES:
                raise APIError('The backup file exceeds the size limit.', 413)
            try:
                fields = parse_multipart_data(self.rfile, boundary, content_length)
            except Exception:
                fields = {}
            archive_list = fields.get('archive') or fields.get('file') or []
            archive_bytes = archive_list[0] if archive_list else b''
            if isinstance(archive_bytes, str):
                archive_bytes = archive_bytes.encode('utf-8')
            if not archive_bytes:
                archive_bytes = self.read_body(MAX_BACKUP_FILE_BYTES)
            if not archive_bytes:
                raise APIError('No backup archive provided in request.', 400)
            if len(archive_bytes) > MAX_BACKUP_FILE_BYTES:
                raise APIError('The backup file exceeds the size limit.', 413)
            return archive_bytes
        else:
            archive_bytes = self.read_body(MAX_BACKUP_FILE_BYTES)
            if not archive_bytes:
                raise APIError('No backup archive provided in request.', 400)
            return archive_bytes

    def do_POST(self):
        try:
            self.check_origin()
            path = urlsplit(self.path).path

            # Authenticate before reading a request body. Unauthenticated callers
            # must not be able to allocate large buffers or occupy a worker while
            # slowly uploading data.
            if path.startswith('/api/admin/'):
                self.require_user(admin=True)
            elif path.startswith('/api/account/') or re.fullmatch(r'/api/notes/[^/]+/shares', path):
                self.require_user()

            if path in ('/api/setup/admin', '/api/setup/import', '/api/setup/import-backup'):
                if not self.check_setup_permission():
                    raise APIError('The first-time setup can only be completed with a valid setup token.', 403)

            if path in ('/api/login', '/api/login/2fa', '/api/login/passkey', '/api/account/password', '/api/account/totp/verify'):
                client_ip = self.get_client_ip()
                if is_rate_limited(client_ip):
                    raise APIError('Too many failed attempts. Please try again later.', 429)
            if path == '/api/setup/import-backup':
                archive_bytes = self.read_archive_from_request()
                password = get_backup_password()
                self.import_snapshot_archive(archive_bytes, password=password)
                return
            if path == '/api/admin/backups/upload-restore':
                self.upload_restore_server_backup()
                return

            payload = self.read_json(MAX_SNAPSHOT_BYTES if path == '/api/setup/import' else MAX_REQUEST_BYTES)

            routes_with_payload = {
                '/api/setup/admin': self.create_first_admin,
                '/api/setup/import': self.import_snapshot,
                '/api/login': self.login,
                '/api/login/2fa': self.login_2fa,
                '/api/login/passkey': self.login_passkey,
                '/api/register': self.register,
                '/api/account/password': self.change_password,
                '/api/account/avatar': self.change_avatar,
                '/api/account/labels': self.change_labels,
                '/api/account/totp/verify': self.verify_totp,
                '/api/account/passkey': self.add_passkey,
                '/api/admin/settings': self.save_settings,
                '/api/admin/invites': self.create_invite,
                '/api/admin/backups': self.create_server_backup,
                '/api/admin/update/perform': self.perform_update,
            }

            routes_without_payload = {
                '/api/logout': self.logout,
                '/api/account/totp': self.setup_totp,
            }

            if path in routes_with_payload:
                routes_with_payload[path](payload)
                return
            if path in routes_without_payload:
                routes_without_payload[path]()
                return

            restore_match = re.fullmatch(r'/api/admin/backups/([^/]+)/restore', path)
            if restore_match:
                self.restore_server_backup(restore_match.group(1), payload)
                return

            share_match = re.fullmatch(r'/api/notes/([^/]+)/shares', path)
            if share_match:
                user = self.require_user()
                self.create_share(user, share_match.group(1), payload)
                return

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
                self.require_step_up(user)
                key_id = unquote(passkey_match.group(1))
                with database() as connection:
                    cursor = connection.execute('DELETE FROM passkeys WHERE id = ? AND user_id = ?', (key_id, user['id']))
                    if not cursor.rowcount:
                        raise APIError('Passkey not found.', 404)
                self.invalidate_user_sessions(user['id'], keep_token=self.get_session_token())
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
            fail2ban_match = re.fullmatch(r'/api/admin/fail2ban(?:/(.+))?', path)
            if fail2ban_match:
                self.require_user(admin=True)
                target = fail2ban_match.group(1)
                if not target or target.lower() == 'all':
                    unban_all()
                    self.send_json({'unbannedAll': True})
                else:
                    target_ip = unquote(target)
                    unban_ip(target_ip)
                    self.send_json({'unbannedIp': target_ip})
                return
            self.send_error_json('Endpoint not found.', 404)
        except APIError as error:
            self.send_error_json(str(error), error.status)

    def create_first_admin(self, payload):
        if not self.check_setup_permission():
            raise APIError('The first-time setup can only be completed locally or with a valid setup token.', 403)
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
        self.create_session_response(user_id)

    def build_snapshot(self):
        with database() as connection:
            connection.execute('BEGIN')
            users = connection.execute(
                'SELECT id, email, password_hash, role, created_at, avatar, labels_json, '
                'totp_secret, backup_codes_json, totp_last_used_step FROM users ORDER BY id'
            ).fetchall()
            notes = connection.execute(
                'SELECT id, user_id, title, body, body_format, color, tags_json, pinned, archived, '
                'deleted, created_at, updated_at, sort_order, due_date FROM notes '
                'ORDER BY user_id, sort_order DESC'
            ).fetchall()
            invites = connection.execute('SELECT * FROM invites ORDER BY created_at').fetchall()
            shares = connection.execute('SELECT * FROM note_shares ORDER BY note_id, user_id').fetchall()
            passkeys = connection.execute(
                'SELECT id, user_id, public_key_pem, name, created_at, sign_count '
                'FROM passkeys ORDER BY user_id, created_at'
            ).fetchall()
            settings = connection.execute('SELECT key, value FROM settings ORDER BY key').fetchall()
        snapshot_users = []
        for row in users:
            try:
                labels = json.loads(row['labels_json']) if row['labels_json'] else []
                backup_codes = json.loads(row['backup_codes_json']) if row['backup_codes_json'] else []
            except (TypeError, json.JSONDecodeError) as error:
                raise APIError('The snapshot contains invalid account metadata.', 500) from error
            if not isinstance(labels, list) or not isinstance(backup_codes, list):
                raise APIError('The snapshot contains invalid account metadata.', 500)
            totp_secret = None
            if row['totp_secret']:
                totp_secret = row['totp_secret']
                if totp_secret is None:
                    # Never silently export an account without its MFA factor.
                    raise APIError(
                        'Could not decrypt a stored two-factor secret; backup aborted to avoid losing MFA data.',
                        500,
                    )
            snapshot_users.append({
                'id': row['id'], 'email': row['email'], 'passwordHash': row['password_hash'],
                'role': row['role'], 'createdAt': row['created_at'], 'avatar': row['avatar'],
                'labels': labels,
                'totpSecret': totp_secret,
                'totpLastUsedStep': row['totp_last_used_step'],
                'backupCodes': backup_codes,
            })
        snapshot_notes = []
        for row in notes:
            try:
                tags = json.loads(row['tags_json']) if row['tags_json'] else []
            except (TypeError, json.JSONDecodeError) as error:
                raise APIError('The snapshot contains invalid note metadata.', 500) from error
            snapshot_notes.append({
                'id': row['id'], 'userId': row['user_id'], 'title': row['title'], 'body': row['body'],
                'bodyFormat': row['body_format'], 'color': row['color'], 'tags': tags,
                'pinned': bool(row['pinned']), 'archived': bool(row['archived']), 'deleted': bool(row['deleted']),
                'createdAt': row['created_at'], 'updatedAt': row['updated_at'], 'order': row['sort_order'],
                'dueDate': row['due_date'],
            })
        snapshot = {
            'format': SNAPSHOT_FORMAT,
            'version': SNAPSHOT_VERSION,
            'appVersion': VERSION,
            'createdAt': iso_time(),
            'users': snapshot_users,
            'notes': snapshot_notes,
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
                 'name': row['name'], 'createdAt': row['created_at'], 'signCount': row['sign_count']}
                for row in passkeys
            ],
            'settings': [
                {'key': row['key'], 'value': row['value']}
                for row in settings
            ],
        }
        return snapshot

    def create_server_backup(self, payload=None):
        user = self.require_user(admin=True)
        password = get_backup_password()
        if not password:
            raise APIError('A backup password is required but not set in the environment.', 400)
        with backup_operation():
            snapshot = self.build_snapshot()
            backup_bytes = encrypt_backup(snapshot, password)
            filename, created_at, backup_path = write_backup_file(backup_bytes)
        try:
            size_bytes = backup_path.stat().st_size
        except OSError:
            size_bytes = len(backup_bytes)
        self.send_json({
            'filename': filename,
            'createdAt': iso_time(created_at),
            'sizeBytes': size_bytes,
            'encrypted': True,
            'formatVersion': BACKUP_FORMAT_VERSION,
        }, 201)

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
            if size > MAX_BACKUP_FILE_BYTES:
                raise APIError('The backup file exceeds the size limit.', 413)
            data = path.read_bytes()
        except OSError as error:
            raise APIError('The backup archive cannot be read.', 500) from error
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Disposition', f'attachment; filename="{path.name}"')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def delete_server_backup(self, filename):
        user = self.require_user(admin=True)
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
            try:
                connection.execute('DELETE FROM users WHERE id = ?', (user_id,))
            except sqlite3.IntegrityError as error:
                raise APIError('Could not delete user because related data still references it.', 409) from error
        self.send_json({'deleted': user_id})

    def reset_user_2fa(self, user_id):
        admin = self.require_user(admin=True)
        with database() as connection:
            row = connection.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
            if not row:
                raise APIError('User not found.', 404)
            connection.execute('UPDATE users SET totp_secret = NULL, backup_codes_json = NULL, totp_last_used_step = NULL WHERE id = ?', (user_id,))
            connection.execute('DELETE FROM passkeys WHERE user_id = ?', (user_id,))
            connection.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
        self.send_json({'reset': user_id})

    def delete_invite(self, token_hash):
        self.require_user(admin=True)
        with database() as connection:
            cursor = connection.execute('DELETE FROM invites WHERE token_hash = ?', (token_hash,))
            if not cursor.rowcount:
                raise APIError('Invitation not found.', 404)
        self.send_json({'deleted': token_hash})

    def upload_restore_server_backup(self):
        admin = self.require_user(admin=True)
        # Only a self-contained encrypted backup is accepted. The request body is
        # the raw archive; no plaintext JSON snapshot path exists.
        password = get_backup_password()
        raw_bytes = self.read_archive_from_request()
        with backup_operation():
            snapshot = decrypt_backup(raw_bytes, password)
            self.restore_snapshot(snapshot, replace_existing=True)

    def restore_server_backup(self, filename, payload=None):
        admin = self.require_user(admin=True)
        path = self.find_server_backup(filename)
        try:
            size = path.stat().st_size
        except OSError as error:
            raise APIError('The backup archive cannot be read.') from error
        if size > MAX_BACKUP_FILE_BYTES:
            raise APIError('The backup file exceeds the size limit.', 413)
        password = get_backup_password()
        try:
            raw_bytes = path.read_bytes()
        except OSError as error:
            raise APIError('The backup archive cannot be read.') from error
        with backup_operation():
            snapshot = decrypt_backup(raw_bytes, password)
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
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # pylint: disable=too-many-arguments
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

    @staticmethod
    def _safe_extract(archive, path, members=None):
        if members is None:
            members = archive.getmembers()
        safe_members = []
        base_path = os.path.realpath(path)
        for member in members:
            # Emulate Python 3.12 data_filter for older versions
            if hasattr(tarfile, 'data_filter'):
                safe_members.append(member)
            else:
                if member.issym() or member.islnk():
                    continue
                member_path = os.path.realpath(os.path.join(base_path, member.name))
                if os.path.commonpath([base_path, member_path]) == base_path:
                    safe_members.append(member)

        if hasattr(tarfile, 'data_filter'):
            archive.extractall(path=path, members=safe_members, filter='data')
        else:
            import shutil
            for member in safe_members:
                member_path = os.path.realpath(os.path.join(base_path, member.name))
                if os.path.commonpath([base_path, member_path]) != base_path:
                    continue
                if member.isdir():
                    os.makedirs(member_path, exist_ok=True)
                elif member.isreg():
                    os.makedirs(os.path.dirname(member_path), exist_ok=True)
                    try:
                        src = archive.extractfile(member)
                    except Exception:
                        continue
                    if src:
                        try:
                            with open(member_path, 'wb') as dst:
                                shutil.copyfileobj(src, dst)
                        finally:
                            src.close()
                        try:
                            os.chmod(member_path, member.mode)
                        except OSError:
                            pass
                elif member.issym() or member.islnk():
                    # Safely handle symlinks if needed, or explicitly skip
                    # We explicitly skip symlinks and links in safe_members filtering above
                    pass

    def _extract_update_archive(self, archive, members):
        valid_members = []
        for member in members:
            parts = member.name.split('/', 1)
            if len(parts) > 1:
                member.name = parts[1]
                if not member.name or member.name.startswith('/'):
                    continue
                member_path = Path(member.name)
                if member_path.is_absolute() or '..' in member_path.parts:
                    continue
                if not (member.isreg() or member.isdir()):
                    continue
                valid_members.append(member)

        self._safe_extract(archive, ROOT, valid_members)

    def _update_rollback_path(self):
        return backup_directory() / f'update-rollback-{utc_now().strftime("%Y%m%d-%H%M%S")}-{secrets.token_hex(4)}.tar.gz'

    def _create_update_rollback(self, members):
        """Snapshot the files an update is about to overwrite."""
        names = set()
        for member in members:
            parts = member.name.split('/', 1)
            rel_name = parts[1] if len(parts) > 1 else member.name
            if rel_name and not rel_name.startswith('/') and '..' not in Path(rel_name).parts:
                names.add(rel_name)
        backup_directory().mkdir(parents=True, exist_ok=True)
        rollback_path = self._update_rollback_path()
        with tarfile.open(rollback_path, 'w:gz') as rollback:
            for rel_name in sorted(names):
                source = (ROOT / rel_name).resolve()
                if source.is_relative_to(ROOT.resolve()) and source.is_file():
                    rollback.add(source, arcname=rel_name)
        try:
            os.chmod(rollback_path, 0o600)
        except OSError:
            pass
        return rollback_path

    @staticmethod
    def _restore_update_rollback(rollback_path):
        with tarfile.open(rollback_path, 'r:gz') as rollback:
            valid_members = [m for m in rollback.getmembers() if m.isfile()]
            NotkiHandler._safe_extract(rollback, ROOT, valid_members)

    def perform_update(self, payload):
        admin = self.require_user(admin=True)
        if Path('/.dockerenv').exists():
            raise APIError('admin.update.dockerWarning', 400)

        tarball_url = payload.get('tarballUrl')
        if not tarball_url or not tarball_url.startswith('https://api.github.com/repos/shirou93/Notki/tarball/'):
            raise APIError('Invalid download URL.', 400)

        archive_bytes = self._download_update_archive(tarball_url)
        if len(archive_bytes) > MAX_SNAPSHOT_BYTES:
            raise APIError('The update archive is too large.', 413)

        rollback_path = None
        try:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode='r:gz') as archive:
                members = archive.getmembers()
                if not members:
                    raise ValueError("Empty archive")

                self._verify_update_version(archive, members)
                rollback_path = self._create_update_rollback(members)
                try:
                    self._extract_update_archive(archive, members)
                except Exception:
                    if rollback_path and rollback_path.exists():
                        self._restore_update_rollback(rollback_path)
                    raise
        except APIError:
            raise
        except Exception:
            raise APIError('Could not extract files. The previous version was restored.', 500)

        threading.Timer(1.0, lambda: os._exit(0)).start()
        self.send_json({'success': True})

    def import_snapshot_archive(self, archive_bytes, password=None):
        if not self.check_setup_permission():
            raise APIError('Snapshot import is available only with a valid setup token.', 403)
        with backup_operation():
            snapshot = decrypt_backup(archive_bytes, password)
            self.restore_snapshot(snapshot, replace_existing=False)

    @staticmethod
    def snapshot_from_bytes(raw_bytes, password=None):
        """Decrypt a backup file. Plaintext snapshots are intentionally rejected."""
        return decrypt_backup(raw_bytes, password)

    def import_snapshot(self, payload):
        if not self.check_setup_permission():
            raise APIError('Snapshot import is available only locally or with a valid setup token.', 403)
        raise APIError('Plaintext backups are not supported. Create an encrypted backup with a password.')

    # ---- Snapshot validation -------------------------------------------------
    # Everything below is executed before the restore transaction starts. Values
    # from the archive are treated as untrusted input: no coercing of arbitrary
    # objects to strings, no unbounded collections and no unknown fields.

    @staticmethod
    def _snapshot_str(value, max_length, required=False, allow_none=True):
        if value is None:
            if required:
                raise APIError('The snapshot contains an invalid value.')
            return None if allow_none else ''
        if not isinstance(value, str) or len(value) > max_length:
            raise APIError('The snapshot contains an invalid value.')
        return value

    @staticmethod
    def _snapshot_int(value, minimum, maximum, required=False):
        if value is None:
            if required:
                raise APIError('The snapshot contains an invalid value.')
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise APIError('The snapshot contains an invalid value.')
        return value

    @staticmethod
    def _snapshot_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise APIError('The snapshot contains an invalid value.')

    @staticmethod
    def _reject_unknown_fields(value, allowed, message):
        if not isinstance(value, dict) or not set(value).issubset(allowed):
            raise APIError(message)

    def _prepare_snapshot_users(self, users):
        user_ids = set()
        emails = set()
        prepared_users = []
        allowed = {
            'id', 'email', 'passwordHash', 'role', 'createdAt', 'avatar', 'labels',
            'totpSecret', 'totpLastUsedStep', 'backupCodes',
        }
        for user in users:
            self._reject_unknown_fields(user, allowed, 'Invalid account in the snapshot.')
            user_id = self._snapshot_int(user.get('id'), 1, 2_147_483_647, required=True)
            try:
                email = normalize_email(user.get('email'))
            except ValueError as error:
                raise APIError('Invalid account address or role in the snapshot.') from error
            password_hash = self._snapshot_str(user.get('passwordHash'), 512, required=True, allow_none=False)
            role = user.get('role')
            if user_id in user_ids or email in emails or role not in ('admin', 'user'):
                raise APIError('Invalid account address or role in the snapshot.')
            if not self.valid_password_hash(password_hash):
                raise APIError('The snapshot contains an invalid password hash.')
            avatar = self._snapshot_str(user.get('avatar'), MAX_AVATAR_CHARS)
            if avatar is not None and not AVATAR_PATTERN.fullmatch(avatar):
                raise APIError('The snapshot contains an invalid avatar.')
            labels = user.get('labels')
            if labels is None:
                labels = []
            if (not isinstance(labels, list) or len(labels) > 64
                    or any(not isinstance(label, str) or len(label) > 80 for label in labels)):
                raise APIError('The snapshot contains invalid account metadata.')
            prepared_codes = []
            backup_codes = user.get('backupCodes')
            if backup_codes is not None:
                if not isinstance(backup_codes, list) or len(backup_codes) > 64:
                    raise APIError('The snapshot contains invalid two-factor data.')
                for raw_code in backup_codes:
                    if not isinstance(raw_code, str) or len(raw_code) > 512:
                        raise APIError('The snapshot contains invalid two-factor data.')
                    stored_code = raw_code
                    prepared_codes.append(stored_code)
            totp_secret = user.get('totpSecret')
            stored_totp = None
            if totp_secret is not None:
                totp_secret = self._snapshot_str(totp_secret, 256)
                pending = totp_secret.startswith('pending:')
                candidate = totp_secret.removeprefix('pending:') if pending else totp_secret
                try:
                    candidate = validate_totp_secret(candidate)
                except ValueError as error:
                    raise APIError('The snapshot contains invalid two-factor data.') from error
                stored_totp = (('pending:' if pending else '') + candidate)
            totp_last_step = self._snapshot_int(user.get('totpLastUsedStep'), 0, 10 ** 12)
            backup_codes_json = json.dumps(prepared_codes) if prepared_codes else None
            user_ids.add(user_id)
            emails.add(email)
            prepared_users.append((
                user_id, email, password_hash, role, self.snapshot_date(user.get('createdAt')),
                avatar, json.dumps(labels), stored_totp, backup_codes_json, totp_last_step,
            ))
        if not any(user[3] == 'admin' for user in prepared_users):
            raise APIError('The snapshot must contain an administrator account.')
        return user_ids, emails, prepared_users

    def _validate_snapshot_note_identity(self, note, user_ids, note_ids):
        allowed = {
            'id', 'userId', 'title', 'body', 'bodyFormat', 'color', 'tags', 'pinned',
            'archived', 'deleted', 'createdAt', 'updatedAt', 'order', 'dueDate',
        }
        self._reject_unknown_fields(note, allowed, 'Invalid note in the snapshot.')
        note_id = self._snapshot_str(note.get('id'), 200, required=True, allow_none=False)
        user_id = self._snapshot_int(note.get('userId'), 1, 2_147_483_647, required=True)
        if not note_id or note_id in note_ids or user_id not in user_ids:
            raise APIError('Invalid note or owner in the snapshot.')
        return note_id, user_id

    def _parse_snapshot_note_order(self, note):
        value = note.get('order')
        if value is None:
            return 0.0
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise APIError('Invalid note order in the snapshot.')
        sort_order = float(value)
        if not math.isfinite(sort_order) or abs(sort_order) > 1e15:
            raise APIError('Invalid note order in the snapshot.')
        return sort_order

    def _prepare_snapshot_note(self, note, user_ids, note_ids):
        note_id, user_id = self._validate_snapshot_note_identity(note, user_ids, note_ids)
        title = self._snapshot_str(note.get('title'), 160, allow_none=False)
        body = self._snapshot_str(note.get('body'), 1_000_000, allow_none=False)
        sort_order = self._parse_snapshot_note_order(note)
        note_ids.add(note_id)

        tags = note.get('tags')
        if tags is None:
            tags = []
        if (not isinstance(tags, list) or len(tags) > 64
                or any(not isinstance(tag, str) or len(tag) > 80 for tag in tags)):
            raise APIError('Invalid note in the snapshot.')
        body_format = note.get('bodyFormat')
        if body_format is None:
            body_format = 0
        if isinstance(body_format, bool) or not isinstance(body_format, int) or body_format not in (0, 1):
            raise APIError('Invalid note in the snapshot.')
        color = note.get('color')
        if color is None:
            color = 'default'
        if not isinstance(color, str) or color not in NOTE_COLORS:
            raise APIError('Invalid note in the snapshot.')
        archived = self._snapshot_bool(note.get('archived'))
        deleted = self._snapshot_bool(note.get('deleted'))
        pinned = False if (archived or deleted) else self._snapshot_bool(note.get('pinned'))
        due_date = self._snapshot_str(note.get('dueDate'), 64)
        return (
            note_id, user_id, title, body, body_format, color,
            json.dumps(tags, ensure_ascii=False),
            int(pinned), int(archived), int(deleted),
            self.snapshot_date(note.get('createdAt')), self.snapshot_date(note.get('updatedAt')), sort_order,
            due_date,
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
        allowed = {'tokenHash', 'createdBy', 'createdAt', 'expiresAt', 'usedAt'}
        for invite in invites:
            self._reject_unknown_fields(invite, allowed, 'Invalid invitation in the snapshot.')
            token = invite.get('tokenHash')
            created_by = invite.get('createdBy')
            if (not isinstance(token, str) or len(token) != 64
                    or any(character not in '0123456789abcdef' for character in token)):
                raise APIError('Invalid invitation hash in the snapshot.')
            if created_by is not None:
                created_by = self._snapshot_int(created_by, 1, 2_147_483_647, required=True)
                if created_by not in user_ids:
                    raise APIError('Invalid invitation or administrator in the snapshot.')
            if token in invite_hashes:
                raise APIError('Invalid invitation or administrator in the snapshot.')
            invite_hashes.add(token)
            used_at = invite.get('usedAt')
            prepared_invites.append((
                token, created_by, self.snapshot_date(invite.get('createdAt')),
                self.snapshot_date(invite.get('expiresAt')),
                self.snapshot_date(used_at) if used_at else None,
            ))
        return prepared_invites

    def _prepare_snapshot_shares(self, shares, user_ids, note_ids):
        prepared_shares = []
        share_keys = set()
        allowed = {'noteId', 'userId', 'permission', 'createdAt'}
        for share in shares:
            self._reject_unknown_fields(share, allowed, 'The snapshot contains an invalid sharing entry.')
            note_id = share.get('noteId')
            user_id = self._snapshot_int(share.get('userId'), 1, 2_147_483_647, required=True)
            permission = share.get('permission')
            if not isinstance(note_id, str) or note_id not in note_ids:
                raise APIError('The snapshot contains an invalid sharing entry.')
            if user_id not in user_ids or permission not in ('read', 'write'):
                raise APIError('The snapshot contains an invalid sharing entry.')
            if (note_id, user_id) in share_keys:
                raise APIError('The snapshot contains an invalid sharing entry.')
            share_keys.add((note_id, user_id))
            prepared_shares.append((note_id, user_id, permission, self.snapshot_date(share.get('createdAt'))))
        return prepared_shares

    def _prepare_snapshot_passkeys(self, passkeys, user_ids):
        prepared_passkeys = []
        passkey_ids = set()
        allowed = {'id', 'userId', 'publicKeyPem', 'name', 'createdAt', 'signCount'}
        for pk in passkeys:
            self._reject_unknown_fields(pk, allowed, 'The snapshot contains invalid security keys.')
            pk_id = self._snapshot_str(pk.get('id'), 512, required=True, allow_none=False)
            user_id = self._snapshot_int(pk.get('userId'), 1, 2_147_483_647, required=True)
            pub_pem = self._snapshot_str(pk.get('publicKeyPem'), 10_000, required=True, allow_none=False)
            name = self._snapshot_str(pk.get('name'), 80) or 'Passkey'
            sign_count = self._snapshot_int(pk.get('signCount'), 0, 2_147_483_647)
            if (not pk_id or pk_id in passkey_ids or user_id not in user_ids or not pub_pem):
                raise APIError('The snapshot contains invalid security keys.')
            passkey_ids.add(pk_id)
            prepared_passkeys.append((
                pk_id, user_id, pub_pem, name, self.snapshot_date(pk.get('createdAt')),
                sign_count if sign_count is not None else 0,
            ))
        return prepared_passkeys

    _SNAPSHOT_SETTING_KEYS = {
        'require2FA', 'logLevel', 'sessionDays', 'announcement',
        'fail2banEnabled', 'fail2banMaxAttempts', 'fail2banBanTime',
    }

    def _prepare_snapshot_settings(self, settings):
        prepared_settings = []
        setting_keys = set()
        allowed = {'key', 'value'}
        for st in settings:
            self._reject_unknown_fields(st, allowed, 'The snapshot contains invalid settings.')
            key = self._snapshot_str(st.get('key'), 100, required=True, allow_none=False)
            value = self._snapshot_str(st.get('value'), 65_536, required=True, allow_none=False)
            if not key or key in setting_keys or key not in self._SNAPSHOT_SETTING_KEYS:
                raise APIError('The snapshot contains invalid settings.')
            self._validate_snapshot_setting(key, value)
            setting_keys.add(key)
            prepared_settings.append((key, value))
        return prepared_settings

    @staticmethod
    def _validate_snapshot_setting(key, value):
        if key == 'require2FA' and value not in ('true', 'false'):
            raise APIError('The snapshot contains invalid settings.')
        if key == 'logLevel' and value not in ('INFO', 'WARNING', 'ERROR', 'DEBUG'):
            raise APIError('The snapshot contains invalid settings.')
        if key in ('sessionDays', 'fail2banMaxAttempts', 'fail2banBanTime'):
            try:
                number = int(value)
            except (TypeError, ValueError) as error:
                raise APIError('The snapshot contains invalid settings.') from error
            limits = {'sessionDays': (1, 3650), 'fail2banMaxAttempts': (1, 1000), 'fail2banBanTime': (1, 86400)}
            low, high = limits[key]
            if not low <= number <= high:
                raise APIError('The snapshot contains invalid settings.')
        if key == 'fail2banEnabled' and value not in ('true', 'false'):
            raise APIError('The snapshot contains invalid settings.')
        if key == 'announcement' and len(value) > 2000:
            raise APIError('The snapshot contains invalid settings.')

    def _apply_snapshot_data(self, prepared_users, prepared_notes, prepared_invites, prepared_shares, prepared_passkeys, prepared_settings, replace_existing):
        global _FAIL2BAN_CONFIG_CACHE
        try:
            with database() as connection:
                try:
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
                        connection.execute('DELETE FROM fail2ban_attempts')
                        connection.execute('DELETE FROM users')
                    connection.executemany(
                        'INSERT INTO users (id, email, password_hash, role, created_at, avatar, labels_json, '
                        'totp_secret, backup_codes_json, totp_last_used_step) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        prepared_users,
                    )
                    connection.executemany('''
                        INSERT INTO notes (id, user_id, title, body, body_format, color, tags_json, pinned, archived,
                                           deleted, created_at, updated_at, sort_order, due_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', prepared_notes)
                    connection.executemany(
                        'INSERT INTO invites (token_hash, created_by, created_at, expires_at, used_at) '
                        'VALUES (?, ?, ?, ?, ?)',
                        prepared_invites,
                    )
                    connection.executemany(
                        'INSERT INTO note_shares (note_id, user_id, permission, created_at) VALUES (?, ?, ?, ?)',
                        prepared_shares,
                    )
                    if prepared_passkeys:
                        connection.executemany(
                            'INSERT INTO passkeys (id, user_id, public_key_pem, name, created_at, sign_count) '
                            'VALUES (?, ?, ?, ?, ?, ?)',
                            prepared_passkeys,
                        )
                    if prepared_settings:
                        connection.executemany(
                            'INSERT INTO settings (key, value) VALUES (?, ?) '
                            'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                            prepared_settings,
                        )
                except APIError:
                    connection.rollback()
                    raise
                except (sqlite3.Error, OSError) as error:
                    connection.rollback()
                    raise APIError('Could not restore the backup. No data was changed.', 500) from error
        except APIError:
            raise
        except (sqlite3.Error, OSError) as error:
            raise APIError('Could not restore the backup. No data was changed.', 500) from error
        _FAIL2BAN_CONFIG_CACHE = None

    def restore_snapshot(self, snapshot, replace_existing=False):
        allowed = {
            'format', 'version', 'appVersion', 'createdAt', 'users', 'notes',
            'invites', 'shares', 'passkeys', 'settings',
        }
        self._reject_unknown_fields(snapshot, allowed, 'The file is not a valid Notki server snapshot.')
        if snapshot.get('format') != SNAPSHOT_FORMAT:
            raise APIError('The file is not a valid Notki server snapshot.')
        version = snapshot.get('version')
        if (isinstance(version, bool) or not isinstance(version, int)
                or version not in SUPPORTED_SNAPSHOT_VERSIONS):
            raise APIError('Unsupported backup format version.')
        app_version = snapshot.get('appVersion')
        if app_version is not None and (not isinstance(app_version, str) or len(app_version) > 64):
            raise APIError('The file is not a valid Notki server snapshot.')
        if snapshot.get('createdAt') is not None:
            self.snapshot_date(snapshot.get('createdAt'))

        users = snapshot.get('users')
        notes = snapshot.get('notes')
        invites = snapshot.get('invites')
        shares = snapshot.get('shares', [])
        passkeys = snapshot.get('passkeys', [])
        settings = snapshot.get('settings', [])
        if not isinstance(users, list) or not isinstance(notes, list) or not isinstance(invites, list):
            raise APIError('The snapshot does not contain a complete list of accounts, notes, and invitations.')
        if not isinstance(shares, list) or not isinstance(passkeys, list) or not isinstance(settings, list):
            raise APIError('The snapshot has an invalid structure.')
        if not users or len(users) > 10_000 or len(notes) > 100_000 or len(invites) > 100_000:
            raise APIError('The snapshot is empty or exceeds the data limit.')
        if len(shares) > 500_000 or len(passkeys) > 100_000 or len(settings) > 100:
            raise APIError('The snapshot is empty or exceeds the data limit.')

        user_ids, _, prepared_users = self._prepare_snapshot_users(users)
        note_ids, prepared_notes = self._prepare_snapshot_notes(notes, user_ids)
        prepared_invites = self._prepare_snapshot_invites(invites, user_ids)
        prepared_shares = self._prepare_snapshot_shares(shares, user_ids, note_ids)
        prepared_passkeys = self._prepare_snapshot_passkeys(passkeys, user_ids)
        prepared_settings = self._prepare_snapshot_settings(settings)

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
            if not isinstance(password_hash, str) or len(password_hash) > 1024:
                return False
            parts = password_hash.split('$')
            if parts[0] == 'scrypt':
                _, n, r, p, salt_hex, digest_hex = parts
                if len(salt_hex) > 128 or len(digest_hex) > 256:
                    return False
                return (
                    1024 <= int(n) <= 1_048_576 and 1 <= int(r) <= 32 and 1 <= int(p) <= 10
                    and len(bytes.fromhex(salt_hex)) == 16 and len(bytes.fromhex(digest_hex)) >= 16
                )
            elif parts[0] == 'pbkdf2_sha256':
                _, iterations, salt_hex, digest_hex = parts
                if len(salt_hex) > 128 or len(digest_hex) > 256:
                    return False
                count = int(iterations)
                return (
                    100_000 <= count <= 2_000_000
                    and len(bytes.fromhex(salt_hex)) == 16 and len(bytes.fromhex(digest_hex)) == 32
                )
            return False
        except (ValueError, TypeError, AttributeError):
            return False

    @staticmethod
    def snapshot_date(value):
        if not isinstance(value, str) or len(value) > 64:
            raise APIError('The snapshot contains an invalid date.')
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
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
        if is_account_rate_limited(email):
            raise APIError('Too many failed attempts. Please try again later.', 429)
        with database() as connection:
            row = connection.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
            # Verify password using dummy hash if user does not exist to mitigate timing side-channel attacks for email enumeration
            password_hash = row['password_hash'] if row else DUMMY_PASSWORD_HASH
            valid_password = verify_password(password, password_hash)
            has_totp = False
            has_passkey = False
            require_2fa = False
            user_data = None
            if row and valid_password:
                if password_needs_rehash(password_hash):
                    connection.execute('UPDATE users SET password_hash = ? WHERE id = ?', (hash_password(password), row['id']))
                totp_secret = row['totp_secret']
                # Fail closed: an undecryptable stored secret still requires a
                # second factor and must never result in a password-only session.
                has_totp = (
                    bool(totp_secret and not totp_secret.startswith('pending:'))
                    or bool(row['totp_secret'] and totp_secret is None)
                )
                pk_count = connection.execute('SELECT COUNT(*) FROM passkeys WHERE user_id = ?', (row['id'],)).fetchone()[0]
                has_passkey = pk_count > 0
                req_row = connection.execute("SELECT value FROM settings WHERE key = 'require2FA'").fetchone()
                require_2fa = bool(req_row and req_row['value'] == 'true')
                user_data = public_user(row, connection)
        if not row or not valid_password:
            record_failed_auth(self.get_client_ip(), email)
            self.send_error_json('Invalid e-mail or password.', 401)
            return

        if require_2fa and not (has_totp or has_passkey):
            raise APIError('Two-factor authentication is required by the administrator. Please configure it.', 403)

        if has_totp or has_passkey:
            temp_token = create_temp_2fa_token(row['id'])
            self.send_json({'requires2FA': True, 'tempToken': temp_token, 'hasTotp': has_totp, 'hasPasskey': has_passkey})
            return

        clear_failed_auth(self.get_client_ip(), email)
        token = self.new_session(row['id'])
        self.send_json({'user': user_data}, extra_headers=self.session_headers(token))

    def login_2fa(self, payload):
        user_id = consume_temp_2fa_token(payload.get('tempToken'))
        if not user_id:
            raise APIError('2FA session expired or invalid.', 401)
        totp_code = payload.get('totpCode')
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
            if not row:
                raise APIError('User not found.', 404)
            if is_account_rate_limited(row['email']):
                raise APIError('Too many failed attempts. Please try again later.', 429)
            secret = row['totp_secret']
            backup_raw = row['backup_codes_json']
            try:
                backup_codes = json.loads(backup_raw) if backup_raw else []
            except (TypeError, json.JSONDecodeError):
                backup_codes = []

            totp_valid = False
            if secret and not secret.startswith('pending:'):
                counter = verify_totp_counter(secret, totp_code)
                if counter is not None and (row['totp_last_used_step'] is None or counter > row['totp_last_used_step']):
                    cursor = connection.execute(
                        'UPDATE users SET totp_last_used_step = ? WHERE id = ? '
                        'AND (totp_last_used_step IS NULL OR totp_last_used_step < ?)',
                        (counter, user_id, counter),
                    )
                    totp_valid = cursor.rowcount == 1

            backup_valid = False
            if not totp_valid and backup_codes:
                for stored_code in list(backup_codes):
                    if verify_backup_code(totp_code, stored_code):
                        backup_valid = True
                        backup_codes.remove(stored_code)
                        connection.execute('UPDATE users SET backup_codes_json = ? WHERE id = ?', (json.dumps(backup_codes), user_id))
                        break

            auth_invalid = not totp_valid and not backup_valid
        if auth_invalid:
            record_failed_auth(self.get_client_ip(), row['email'])
            raise APIError('Invalid two-factor code.', 401)
        clear_failed_auth(self.get_client_ip(), row['email'])
        token = self.new_session(user_id)
        with database() as connection:
            user_data = public_user(row, connection)
        self.send_json({'user': user_data}, extra_headers=self.session_headers(token))

    def login_passkey(self, payload):
        key_id = payload.get('id')
        auth_data_b64 = payload.get('authenticatorData')
        client_data_b64 = payload.get('clientDataJSON')
        sig_b64 = payload.get('signature')
        challenge_id = payload.get('challengeId')
        if not key_id or not auth_data_b64 or not client_data_b64 or not sig_b64 or not challenge_id:
            raise APIError('Invalid key data.', 400)

        with PASSKEY_CHALLENGES_LOCK:
            challenge_data = PASSKEY_CHALLENGES.pop(challenge_id, None)
            if not challenge_data or challenge_data['expiresAt'] < utc_now():
                raise APIError('Passkey challenge expired or invalid.', 401)
            expected_challenge = challenge_data['challenge']

        temp_token = payload.get('tempToken')
        with database() as connection:
            if temp_token:
                user_id = consume_temp_2fa_token(temp_token)
                if not user_id:
                    raise APIError('2FA session expired or invalid.', 401)
                row = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
                pk_row = connection.execute('SELECT public_key_pem, sign_count FROM passkeys WHERE id = ? AND user_id = ?', (key_id, user_id)).fetchone()
            else:
                pk_row = connection.execute('SELECT user_id, public_key_pem, sign_count FROM passkeys WHERE id = ?', (key_id,)).fetchone()
                if not pk_row:
                    raise APIError('Passkey not found.', 401)
                user_id = pk_row['user_id']
                row = connection.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

            if not pk_row or not row:
                raise APIError('Passkey not found.', 401)

        origin = f"{self.get_forwarded_proto() or 'http'}://{self.get_forwarded_host() or self.headers.get('Host')}"
        expected_rp_id = (self.get_forwarded_host() or self.headers.get('Host') or '').split(':')[0]

        pk_str = pk_row['public_key_pem']
        if pk_str.startswith('-----BEGIN PUBLIC KEY-----'):
            pub_key_bytes = pk_str.encode('utf-8')
        else:
            try:
                pub_key_bytes = base64.b64decode(pk_str)
            except Exception:
                pub_key_bytes = b''

        try:
            credential = {
                'id': key_id,
                'rawId': key_id,
                'response': {
                    'authenticatorData': auth_data_b64,
                    'clientDataJSON': client_data_b64,
                    'signature': sig_b64,
                },
                'type': 'public-key'
            }

            verification = webauthn.verify_authentication_response(
                credential=credential,
                expected_challenge=expected_challenge,
                expected_origin=origin,
                expected_rp_id=expected_rp_id,
                credential_public_key=pub_key_bytes,
                credential_current_sign_count=pk_row['sign_count']
            )
            new_sign_count = verification.new_sign_count
        except Exception as err:
            client_ip = self.get_client_ip()
            record_failed_auth(client_ip, row['email'])
            raise APIError('Invalid passkey signature.', 401) from err

        clear_failed_auth(self.get_client_ip(), row['email'])
        token = self.new_session(user_id)
        with database() as connection:
            connection.execute('UPDATE passkeys SET sign_count = ? WHERE id = ?', (new_sign_count, key_id))
            user_data = public_user(row, connection)
        self.send_json({'user': user_data}, extra_headers=self.session_headers(token))

    def setup_totp(self):
        user = self.require_user()
        self.require_step_up(user)
        secret = generate_totp_secret()
        with database() as connection:
            connection.execute(
                'UPDATE users SET totp_secret = ?, totp_last_used_step = NULL WHERE id = ?',
                (f'pending:{secret}', user['id']),
            )
        otpauth_url = (
            f"otpauth://totp/Notki:{quote(user['email'])}?secret={secret}&issuer=Notki"
            f"&algorithm={TOTP_ALGORITHM}&digits={TOTP_DIGITS}&period={TOTP_PERIOD_SECONDS}"
        )
        qr_svg = qr.generate_qr_svg(otpauth_url)
        self.send_json({'secret': secret, 'qrSvg': qr_svg, 'otpauthUrl': otpauth_url})

    def verify_totp(self, payload):
        user = self.require_user()
        self.require_step_up(user)
        code = payload.get('code')
        with database() as connection:
            row = connection.execute(
                'SELECT totp_secret, totp_last_used_step FROM users WHERE id = ?', (user['id'],)
            ).fetchone()
        if not row or not row['totp_secret']:
            raise APIError('Invalid two-factor code.', 400)
        totp_secret = row['totp_secret']
        if not totp_secret:
            raise APIError('Invalid two-factor code.', 400)
        secret = totp_secret.removeprefix('pending:') if totp_secret.startswith('pending:') else totp_secret
        counter = verify_totp_counter(secret, code)
        if counter is None:
            record_failed_auth(self.get_client_ip(), user['email'])
            raise APIError('Invalid two-factor code.', 400)

        backup_codes_display = generate_backup_codes()
        backup_codes_store = [hash_backup_code(c) for c in backup_codes_display]

        # Re-check the replay counter inside the write transaction so two concurrent
        # requests cannot both consume the same time step.
        with database() as connection:
            connection.execute('BEGIN IMMEDIATE')
            cursor = connection.execute(
                'UPDATE users SET totp_secret = ?, backup_codes_json = ?, totp_last_used_step = ? '
                'WHERE id = ? AND (totp_last_used_step IS NULL OR totp_last_used_step < ?)',
                (secret, json.dumps(backup_codes_store), counter, user['id'], counter),
            )
            if cursor.rowcount != 1:
                raise APIError('Invalid two-factor code.', 400)
        self.invalidate_user_sessions(user['id'], keep_token=self.get_session_token())
        self.send_json({'verified': True, 'backupCodes': backup_codes_display})

    def remove_totp(self):
        user = self.require_user()
        self.require_step_up(user)
        with database() as connection:
            connection.execute(
                'UPDATE users SET totp_secret = NULL, backup_codes_json = NULL, totp_last_used_step = NULL WHERE id = ?',
                (user['id'],),
            )
        self.invalidate_user_sessions(user['id'], keep_token=self.get_session_token())
        self.send_json({'removed': True})

    def add_passkey(self, payload):
        user = self.require_user()
        self.require_step_up(user)
        key_id = payload.get('id')
        if not isinstance(key_id, str) or not (1 <= len(key_id) <= 512):
            raise APIError('Invalid key data.', 400)
        raw_name = payload.get('name')
        if raw_name is not None and not isinstance(raw_name, str):
            raise APIError('Invalid key data.', 400)
        name = str(raw_name or 'Passkey').strip()[:80] or 'Passkey'
        pub_b64 = payload.get('publicKey')
        auth_data_b64 = payload.get('authenticatorData')
        client_data_b64 = payload.get('clientDataJSON')
        att_obj_b64 = payload.get('attestationObject')
        challenge_id = payload.get('challengeId')

        if not pub_b64 or not client_data_b64 or not att_obj_b64 or not challenge_id:
            raise APIError('Invalid key data.', 400)

        with PASSKEY_CHALLENGES_LOCK:
            challenge_data = PASSKEY_CHALLENGES.pop(challenge_id, None)
            if not challenge_data or challenge_data['expiresAt'] < utc_now():
                raise APIError('Passkey challenge expired or invalid.', 401)
            expected_challenge = challenge_data['challenge']

        origin = f"{self.get_forwarded_proto() or 'http'}://{self.get_forwarded_host() or self.headers.get('Host')}"
        expected_rp_id = (self.get_forwarded_host() or self.headers.get('Host') or '').split(':')[0]

        try:
            credential = {
                'id': key_id,
                'rawId': key_id,
                'response': {
                    'attestationObject': att_obj_b64,
                    'clientDataJSON': client_data_b64,
                },
                'type': 'public-key'
            }

            verification = webauthn.verify_registration_response(
                credential=credential,
                expected_challenge=expected_challenge,
                expected_origin=origin,
                expected_rp_id=expected_rp_id
            )

            pem = base64.b64encode(verification.credential_public_key).decode('utf-8')
            sign_count = verification.sign_count
        except Exception as err:
            raise APIError('Invalid key data.', 400) from err

        with database() as connection:
            existing = connection.execute('SELECT user_id FROM passkeys WHERE id = ?', (key_id,)).fetchone()
            if existing and existing['user_id'] != user['id']:
                raise APIError('Conflict: Passkey ID already exists and belongs to another user.', 409)

            connection.execute(
                'INSERT INTO passkeys (id, user_id, public_key_pem, name, created_at, sign_count) VALUES (?, ?, ?, ?, ?, ?) '
                'ON CONFLICT(id) DO UPDATE SET public_key_pem = excluded.public_key_pem, name = excluded.name, sign_count = excluded.sign_count '
                'WHERE passkeys.user_id = excluded.user_id',
                (key_id, user['id'], pem, name, iso_time(), sign_count)
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
        self.create_session_response(user_id)

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
                client_ip = self.get_client_ip()
                record_failed_auth(client_ip, user['email'])
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
        token = self.get_session_token()
        if token:
            with database() as connection:
                connection.execute('DELETE FROM sessions WHERE token_hash = ?', (token_hash(token),))
        headers = self.session_headers('', 0)
        if self.is_https_request():
            headers.append(('Set-Cookie', f'{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'))
        self.send_json({'loggedOut': True}, extra_headers=headers)

    def create_invite(self, payload=None):
        user = self.require_user(admin=True)
        token = secrets.token_urlsafe(32)
        created = utc_now()
        payload = payload or {}
        try:
            days = int(payload.get('days', INVITE_DAYS))
        except (TypeError, ValueError):
            days = INVITE_DAYS
        days = max(1, min(3650, days))
        expires = created + timedelta(days=days)
        with database() as connection:
            connection.execute(
                'INSERT INTO invites (token_hash, created_by, created_at, expires_at) VALUES (?, ?, ?, ?)',
                (token_hash(token), user['id'], iso_time(created), iso_time(expires)),
            )
        if PUBLIC_HOST:
            if PUBLIC_HOST.startswith(('http://', 'https://')):
                invite_url = f"{PUBLIC_HOST.rstrip('/')}/?invite={token}"
            else:
                proto = self.get_forwarded_proto()
                scheme = 'https' if (proto == 'https' or os.environ.get('NOTKI_PUBLIC_HTTPS') == '1') else 'http'
                invite_url = f"{scheme}://{PUBLIC_HOST}/?invite={token}"
        else:
            host = self.get_forwarded_host() or 'localhost:8000'
            proto = self.get_forwarded_proto()
            scheme = 'https' if (proto == 'https' or os.environ.get('NOTKI_PUBLIC_HTTPS') == '1') else 'http'
            invite_url = f"{scheme}://{host}/?invite={token}"
        self.send_json({'url': invite_url, 'expiresAt': iso_time(expires)}, 201)

    @staticmethod
    def _prepare_note_for_db(note, user_id, seen, default_now=None):
        if not isinstance(note, dict):
            raise APIError('Invalid note.')
        note_id = str(note.get('id') or '')
        title = str(note.get('title') or '')
        body = str(note.get('body') or '')
        tags = note.get('tags') if isinstance(note.get('tags'), list) else []
        if not note_id or len(note_id) > 200 or note_id in seen or len(title) > 160 or len(body) > 1_000_000:
            raise APIError('The note data is invalid or too large.')
        seen.add(note_id)
        created = str(note.get('createdAt') or (default_now if default_now is not None else iso_time()))[:64]
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
        due_date = str(note.get('dueDate'))[:64] if note.get('dueDate') else None
        return (
            note_id, user_id, title, body, 1 if note.get('bodyFormat') == 1 else 0,
            note.get('color') if note.get('color') in NOTE_COLORS else 'default',
            json.dumps([str(tag)[:80] for tag in tags[:64]], ensure_ascii=False),
            int(pinned), int(archived), int(deleted),
            created, updated, sort_order,
            due_date,
        )

    def save_notes(self, user_id, notes):
        if not isinstance(notes, list) or len(notes) > 10_000:
            raise APIError('Invalid note list.')
        prepared = []
        seen = set()
        default_now = iso_time()
        for note in notes:
            prepared.append(NotkiHandler._prepare_note_for_db(note, user_id, seen, default_now))
        with database() as connection:
            if seen:
                connection.execute('DELETE FROM notes WHERE user_id = ? AND id NOT IN (SELECT value FROM json_each(?))', (user_id, json.dumps(list(seen))))
            else:
                connection.execute('DELETE FROM notes WHERE user_id = ?', (user_id,))
            connection.executemany('''
                INSERT INTO notes (id, user_id, title, body, body_format, color, tags_json, pinned, archived,
                                   deleted, created_at, updated_at, sort_order, due_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    sort_order = excluded.sort_order,
                    due_date = excluded.due_date
                WHERE user_id = excluded.user_id
            ''', prepared)

    @staticmethod
    def note_from_row(row):
        note = {
            'id': row['id'], 'title': row['title'], 'body': row['body'], 'bodyFormat': row['body_format'],
            'color': row['color'], 'tags': json.loads(row['tags_json']), 'pinned': bool(row['pinned']),
            'archived': bool(row['archived']), 'deleted': bool(row['deleted']), 'createdAt': row['created_at'],
            'updatedAt': row['updated_at'], 'order': row['sort_order'],
            'dueDate': row['due_date'] if 'due_date' in row.keys() else None,
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

    def directory(self, user_id, query=None):
        """Look up a share recipient by exact e-mail address.

        Enumerating every account is no longer possible: callers must provide an
        exact address and only the id/e-mail are returned (never avatar payloads).
        """
        if not query:
            return []
        try:
            email = normalize_email(query)
        except ValueError:
            return []
        with database() as connection:
            row = connection.execute(
                'SELECT id, email FROM users WHERE id != ? AND email = ?', (user_id, email)
            ).fetchone()
        return [{'id': row['id'], 'email': row['email']}] if row else []

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
                # Do not reveal whether an account exists. Re-render the current
                # share list with the same success shape as a normal request.
                pass
            elif target['id'] == user['id']:
                raise APIError('You cannot share a note with yourself.')
            else:
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
        try:
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            if filename.endswith('.html'):
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Robots-Tag', 'noindex, nofollow')
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def get_settings(self):
        self.require_user(admin=True)
        with database() as connection:
            rows = connection.execute('SELECT key, value FROM settings').fetchall()
            settings_dict = {row['key']: row['value'] for row in rows}
        require_2fa = settings_dict.get('require2FA') == 'true'
        log_level = settings_dict.get('logLevel', 'INFO')
        announcement = settings_dict.get('announcement', '')
        try:
            session_days = int(settings_dict.get('sessionDays', SESSION_DAYS))
        except (ValueError, TypeError):
            session_days = SESSION_DAYS
        fail2ban_config = get_fail2ban_config()
        self.send_json({
            'require2FA': require_2fa,
            'logLevel': log_level,
            'sessionDays': session_days,
            'announcement': announcement,
            'fail2banEnabled': fail2ban_config['enabled'],
            'fail2banMaxAttempts': fail2ban_config['max_attempts'],
            'fail2banBanTime': fail2ban_config['ban_time'],
        })

    def save_settings(self, payload):
        global _FAIL2BAN_CONFIG_CACHE
        _FAIL2BAN_CONFIG_CACHE = None
        user = self.require_user(admin=True)
        require_2fa = 'true' if payload.get('require2FA') else 'false'
        if require_2fa == 'true' and not user.get('has2FA'):
            raise APIError('Configure two-factor authentication before enabling the global requirement.')
        log_level = str(payload.get('logLevel') or 'INFO').upper()
        if log_level not in ('INFO', 'WARNING', 'ERROR', 'DEBUG'):
            raise APIError('Invalid log level.')
        announcement = str(payload.get('announcement', '') if payload.get('announcement') is not None else '')
        if len(announcement) > 2000:
            raise APIError('The announcement exceeds the maximum length of 2000 characters.')
        try:
            session_days = max(1, min(3650, int(payload.get('sessionDays', SESSION_DAYS))))
        except (ValueError, TypeError):
            session_days = SESSION_DAYS
        fail2ban_enabled = 'true' if payload.get('fail2banEnabled', True) else 'false'
        try:
            fail2ban_max_attempts = max(1, min(1000, int(payload.get('fail2banMaxAttempts', 15))))
        except (ValueError, TypeError):
            fail2ban_max_attempts = 15
        try:
            fail2ban_ban_time = max(1, min(86400, int(payload.get('fail2banBanTime', 60))))
        except (ValueError, TypeError):
            fail2ban_ban_time = 60

        with database() as connection:
            connection.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', ('require2FA', require_2fa))
            connection.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', ('logLevel', log_level))
            connection.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', ('sessionDays', str(session_days)))
            connection.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', ('announcement', announcement))
            if any(k in payload for k in ('fail2banEnabled', 'fail2banMaxAttempts', 'fail2banBanTime')):
                connection.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', ('fail2banEnabled', fail2ban_enabled))
                connection.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', ('fail2banMaxAttempts', str(fail2ban_max_attempts)))
                connection.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', ('fail2banBanTime', str(fail2ban_ban_time)))

        self.send_json({
            'require2FA': require_2fa == 'true',
            'logLevel': log_level,
            'sessionDays': session_days,
            'announcement': announcement,
            'fail2banEnabled': fail2ban_enabled == 'true',
            'fail2banMaxAttempts': fail2ban_max_attempts,
            'fail2banBanTime': fail2ban_ban_time,
        })

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


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Threading server with a hard concurrency cap and socket timeouts."""
    daemon_threads = True

    def __init__(self, server_address, request_handler_class, bind_and_activate=True):
        super().__init__(server_address, request_handler_class, bind_and_activate)
        self._request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)

    def process_request(self, request, client_address):
        try:
            request.settimeout(REQUEST_TIMEOUT_SECONDS)
        except OSError:
            pass
        if not self._request_slots.acquire(blocking=False):
            try:
                request.close()
            except OSError:
                pass
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


class _HeadlessRestoreHandler(NotkiHandler):
    """Run snapshot validation/apply without a socket or request state.

    ``restore_snapshot`` only needs the validation helpers on the handler and a
    ``send_json`` sink. The CLI uses this subclass so the destructive restore path
    is exactly the same code as the HTTP admin endpoint.
    """

    def __init__(self):
        self.restore_result = None

    def send_json(self, payload, status=200, extra_headers=()):
        self.restore_result = payload


def _read_cli_backup_password(password_file=None):
    """Read a backup password without putting it on the command line."""
    if password_file:
        try:
            if password_file == '-':
                line = sys.stdin.readline()
            else:
                with Path(password_file).expanduser().open('r', encoding='utf-8') as stream:
                    line = stream.readline()
        except OSError as error:
            raise APIError('Could not read the backup password file.', 400) from error
        password = line.rstrip('\r\n')
        if not password:
            raise APIError('The backup password file is empty.', 400)
        return password

    configured = os.environ.get('NOTKI_BACKUP_PASSWORD')
    if configured:
        return configured
    try:
        return getpass.getpass('Backup password: ')
    except (EOFError, KeyboardInterrupt) as error:
        raise APIError('Backup password entry was cancelled.', 400) from error


def _confirm_cli_restore(assume_yes=False):
    """Require an explicit confirmation for a destructive offline restore."""
    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise APIError('Refusing to restore without confirmation. Re-run with --yes.', 400)
    answer = input('This replaces ALL server data. Type RESTORE to continue: ')
    if answer.strip() != 'RESTORE':
        raise APIError('Restore cancelled.', 400)


def restore_backup_cli(backup_path, password, *, max_bytes=MAX_CLI_BACKUP_BYTES):
    """Restore a local encrypted backup, bypassing the HTTP upload limit.

    The backup still uses the same authenticated encryption, KDF bounds, snapshot
    validation and transaction as the web endpoint. Only the file-size cap is
    raised, and it remains explicitly bounded.
    """
    if (isinstance(max_bytes, bool) or not isinstance(max_bytes, int)
            or max_bytes <= 0 or max_bytes > MAX_CLI_BACKUP_LIMIT):
        raise APIError('Invalid backup size limit.', 400)
    path = Path(backup_path).expanduser()
    try:
        if not path.is_file():
            raise APIError('Backup file not found.', 404)
        size = path.stat().st_size
    except OSError as error:
        raise APIError('Could not read the backup file.', 400) from error
    if size <= 0:
        raise APIError('The backup archive cannot be read.', 400)
    if size > max_bytes:
        raise APIError('The backup file exceeds the CLI size limit.', 413)
    try:
        raw_bytes = path.read_bytes()
    except OSError as error:
        raise APIError('Could not read the backup file.', 400) from error
    if len(raw_bytes) > max_bytes:
        raise APIError('The backup file exceeds the CLI size limit.', 413)

    with backup_operation():
        snapshot = decrypt_backup(
            raw_bytes, password,
            max_file_bytes=max_bytes,
            max_snapshot_bytes=max_bytes,
        )
        handler = _HeadlessRestoreHandler()
        handler.restore_snapshot(snapshot, replace_existing=True)
    return handler.restore_result


def main():
    parser = argparse.ArgumentParser(description='Notki server with SQLite database.')
    parser.add_argument('--create-admin', action='store_true', help='Create the initial administrator account.')
    parser.add_argument('--disable-2fa', metavar='USER', help='Disable two-factor authentication (2FA) for the specified user email or ID.')
    parser.add_argument('--disable-all-2fa', action='store_true', help='Completely disable two-factor authentication (2FA) server-wide for all users.')
    parser.add_argument('--unban', '--unban-ip', metavar='IP', help='Unban a specific IP address from fail2ban.')
    parser.add_argument('--unban-all', action='store_true', help='Unban all IP addresses from fail2ban.')
    parser.add_argument('--restore-backup', metavar='FILE', help='Restore a local encrypted backup and exit. Existing data is replaced.')
    parser.add_argument('--backup-password-file', metavar='FILE', help='Read the backup password from the first line of FILE (use - for stdin).')
    parser.add_argument('--max-backup-size-mb', type=int, default=MAX_CLI_BACKUP_BYTES // (1024 * 1024), metavar='MB', help='Maximum CLI restore file size in MiB (default: 2048).')
    parser.add_argument('--yes', action='store_true', help='Skip the destructive restore confirmation.')
    parser.add_argument('--host', default=os.environ.get('NOTKI_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('NOTKI_PORT', '8000')))
    args = parser.parse_args()

    cli_actions = [
        args.create_admin,
        bool(args.disable_2fa),
        args.disable_all_2fa,
        bool(args.unban),
        args.unban_all,
        bool(args.restore_backup),
    ]
    if sum(bool(action) for action in cli_actions) > 1:
        parser.error('Only one CLI action can be used at a time.')

    initialize_database()
    if args.restore_backup:
        max_bytes = args.max_backup_size_mb * 1024 * 1024
        if max_bytes <= 0 or max_bytes > MAX_CLI_BACKUP_LIMIT:
            parser.error('--max-backup-size-mb is outside the supported range.')
        try:
            _confirm_cli_restore(args.yes)
            password = _read_cli_backup_password(args.backup_password_file)
            result = restore_backup_cli(args.restore_backup, password, max_bytes=max_bytes)
        except APIError as error:
            print(f'Restore failed: {error}', file=sys.stderr)
            raise SystemExit(1) from error
        print(
            'Restore complete: {users} users, {notes} notes, {invites} invitations, {shares} shares.'.format(
                users=result.get('users', 0),
                notes=result.get('notes', 0),
                invites=result.get('invites', 0),
                shares=result.get('shares', 0),
            )
        )
        return
    if args.create_admin:
        create_admin_account()
        return
    if args.disable_2fa:
        disable_user_2fa_cli(args.disable_2fa)
        return
    if args.disable_all_2fa:
        disable_all_2fa_cli()
        return
    if args.unban:
        unban_ip_cli(args.unban)
        return
    if args.unban_all:
        unban_all_cli()
        return
    if not os.environ.get('NOTKI_BACKUP_PASSWORD'):
        global GENERATED_BACKUP_PASSWORD
        GENERATED_BACKUP_PASSWORD = secrets.token_urlsafe(32)
        print('\nWARNING: NOTKI_BACKUP_PASSWORD is not set in the environment.')
        print(f'A temporary backup password has been generated: {GENERATED_BACKUP_PASSWORD}')
        print('Please copy this password and set it as NOTKI_BACKUP_PASSWORD in your .env file.\n')

    server = BoundedThreadingHTTPServer((args.host, args.port), NotkiHandler)
    print(f'Notki running at http://{args.host}:{args.port}')
    with database() as connection:
        needs_setup = connection.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone() is None
    if needs_setup:
        if not os.environ.get('NOTKI_SETUP_TOKEN'):
            global GENERATED_SETUP_TOKEN
            GENERATED_SETUP_TOKEN = secrets.token_hex(16)
            print(f'SETUP TOKEN: {GENERATED_SETUP_TOKEN}')
        print(f'Initial admin setup: http://127.0.0.1:{args.port}/setup')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopping server...')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()