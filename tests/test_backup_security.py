"""Security-focused tests for encrypted backup and restore.

These tests intentionally exercise failure paths: wrong passwords, tampered
ciphertext/metadata, malformed snapshots, oversized input, path traversal and
undecryptable MFA secrets. They use the real HTTP server and a temporary SQLite
database, so no production data is touched.
"""

import base64
import contextlib
import http.cookiejar
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

import server


PASSWORD = 'correct horse battery staple'


def iso_now():
    return server.iso_time()


def make_snapshot(*, users=None, notes=None, invites=None, shares=None,
                  passkeys=None, settings=None, version=server.SNAPSHOT_VERSION,
                  format_value=server.SNAPSHOT_FORMAT):
    snapshot = {
        'format': format_value,
        'version': version,
        'appVersion': server.VERSION,
        'createdAt': iso_now(),
        'users': users if users is not None else [{
            'id': 1,
            'email': 'backup-admin@example.com',
            'passwordHash': server.hash_password('backup-admin-password'),
            'role': 'admin',
            'createdAt': iso_now(),
        }],
        'notes': notes if notes is not None else [],
        'invites': invites if invites is not None else [],
        'shares': shares if shares is not None else [],
        'passkeys': passkeys if passkeys is not None else [],
        'settings': settings if settings is not None else [],
    }
    return snapshot


def make_note(note_id='note-1', user_id=1, title='Title', body='Body'):
    return {
        'id': note_id,
        'userId': user_id,
        'title': title,
        'body': body,
        'bodyFormat': 0,
        'color': 'default',
        'tags': [],
        'pinned': False,
        'archived': False,
        'deleted': False,
        'createdAt': iso_now(),
        'updatedAt': iso_now(),
        'order': 1,
        'dueDate': None,
    }


def with_same_origin(base_url, headers=None):
    headers = dict(headers or {})
    if getattr(server, 'GENERATED_SETUP_TOKEN', None) and 'X-Setup-Token' not in headers:
        headers['X-Setup-Token'] = server.GENERATED_SETUP_TOKEN
    if 'Origin' in headers or 'Referer' in headers:
        return headers
    forwarded_host = headers.get('X-Forwarded-Host', '').split(',')[0].strip()
    host = forwarded_host or urlsplit(base_url).netloc
    proto = 'http'
    forwarded_proto = headers.get('X-Forwarded-Proto', '').split(',')[0].strip().lower()
    if forwarded_proto == 'https' or str(headers.get('X-Forwarded-Ssl', '')).lower() in ('on', '1', 'true'):
        proto = 'https'
    headers['Origin'] = f'{proto}://{host}'
    return headers


def decode_backup_document(raw_bytes):
    return json.loads(raw_bytes.decode('utf-8'))


class BackupCryptoTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_snapshot(notes=[make_note(body='TOP-SECRET-NOTE-BODY')])

    def test_backup_is_authenticated_encrypted_and_self_contained(self):
        raw = server.encrypt_backup(self.snapshot, PASSWORD)
        document = decode_backup_document(raw)

        self.assertEqual(document['format'], server.BACKUP_FORMAT)
        self.assertEqual(document['version'], server.BACKUP_FORMAT_VERSION)
        self.assertEqual(document['cipher']['algorithm'], 'AES-256-GCM')
        self.assertEqual(document['kdf']['algorithm'], 'scrypt')
        self.assertEqual(document['kdf']['n'], server.BACKUP_KDF_N)
        self.assertEqual(document['kdf']['r'], server.BACKUP_KDF_R)
        self.assertEqual(document['kdf']['p'], server.BACKUP_KDF_P)
        self.assertNotIn('password', document)
        self.assertNotIn(PASSWORD, raw.decode('utf-8'))

        raw_text = raw.decode('utf-8')
        for plaintext in ('TOP-SECRET-NOTE-BODY', 'backup-admin@example.com', 'Title'):
            self.assertNotIn(plaintext, raw_text)

        restored = server.decrypt_backup(raw, PASSWORD)
        self.assertEqual(restored, self.snapshot)

    def test_every_backup_uses_a_unique_salt_and_nonce(self):
        first = decode_backup_document(server.encrypt_backup(self.snapshot, PASSWORD))
        second = decode_backup_document(server.encrypt_backup(self.snapshot, PASSWORD))

        self.assertNotEqual(first['kdf']['salt'], second['kdf']['salt'])
        self.assertNotEqual(first['cipher']['nonce'], second['cipher']['nonce'])
        self.assertNotEqual(first['ciphertext'], second['ciphertext'])

    def test_backup_password_is_mandatory_and_has_a_minimum_length(self):
        with self.assertRaises(server.APIError) as context:
            server.encrypt_backup(self.snapshot, '')
        self.assertEqual(context.exception.status, 400)

        with self.assertRaises(server.APIError) as context:
            server.encrypt_backup(self.snapshot, 'short')
        self.assertEqual(context.exception.status, 400)

        with self.assertRaises(server.APIError) as context:
            server.decrypt_backup(server.encrypt_backup(self.snapshot, PASSWORD), '')
        self.assertEqual(context.exception.status, 400)

    def test_wrong_password_uses_a_safe_error(self):
        raw = server.encrypt_backup(self.snapshot, PASSWORD)
        with self.assertRaises(server.APIError) as context:
            server.decrypt_backup(raw, 'wrong password entirely')
        self.assertEqual(context.exception.status, 400)
        self.assertEqual(str(context.exception), 'Invalid backup password or corrupt backup.')
        self.assertNotIn(PASSWORD, str(context.exception))

    def test_tampered_ciphertext_is_rejected(self):
        document = decode_backup_document(server.encrypt_backup(self.snapshot, PASSWORD))
        ciphertext = bytearray(base64.b64decode(document['ciphertext']))
        ciphertext[len(ciphertext) // 2] ^= 1
        document['ciphertext'] = base64.b64encode(bytes(ciphertext)).decode('ascii')

        with self.assertRaises(server.APIError) as context:
            server.decrypt_backup(json.dumps(document).encode('utf-8'), PASSWORD)
        self.assertEqual(context.exception.status, 400)

    def test_tampered_authenticated_metadata_is_rejected(self):
        for mutate in (
            lambda doc: doc.__setitem__('createdAt', '1999-01-01T00:00:00+00:00'),
            lambda doc: doc['kdf'].__setitem__('salt', base64.b64encode(b'0' * 16).decode('ascii')),
            lambda doc: doc['cipher'].__setitem__('nonce', base64.b64encode(b'1' * 12).decode('ascii')),
        ):
            document = decode_backup_document(server.encrypt_backup(self.snapshot, PASSWORD))
            mutate(document)
            with self.assertRaises(server.APIError):
                server.decrypt_backup(json.dumps(document).encode('utf-8'), PASSWORD)

    def test_unknown_version_and_extra_fields_are_rejected(self):
        for version in (3, 2.0, '2'):
            document = decode_backup_document(server.encrypt_backup(self.snapshot, PASSWORD))
            document['version'] = version
            with self.assertRaises(server.APIError):
                server.decrypt_backup(json.dumps(document).encode('utf-8'), PASSWORD)

        document = decode_backup_document(server.encrypt_backup(self.snapshot, PASSWORD))
        document['unexpected'] = 'value'
        with self.assertRaises(server.APIError):
            server.decrypt_backup(json.dumps(document).encode('utf-8'), PASSWORD)

    def test_kdf_parameters_are_bounded_before_key_derivation(self):
        salt = b's' * server.BACKUP_SALT_BYTES
        invalid_parameters = [
            (server.BACKUP_KDF_MIN_N // 2, 8, 1),
            (server.BACKUP_KDF_MAX_N * 2, 8, 1),
            (server.BACKUP_KDF_N + 1, 8, 1),       # not a power of two
            (server.BACKUP_KDF_N, 0, 1),
            (server.BACKUP_KDF_N, server.BACKUP_KDF_MAX_R + 1, 1),
            (server.BACKUP_KDF_N, 8, server.BACKUP_KDF_MAX_P + 1),
            (server.BACKUP_KDF_MAX_N, server.BACKUP_KDF_MAX_R, 1),
        ]
        for n, r, p in invalid_parameters:
            with self.assertRaises(server.APIError):
                server.derive_backup_key(PASSWORD, salt, n, r, p)

    def test_oversized_backup_is_rejected_before_parsing(self):
        raw = server.encrypt_backup(self.snapshot, PASSWORD)
        with unittest.mock.patch.object(server, 'MAX_BACKUP_FILE_BYTES', 32):
            with self.assertRaises(server.APIError) as context:
                server.decrypt_backup(raw, PASSWORD)
        self.assertEqual(context.exception.status, 413)

    def test_plaintext_and_archive_snapshots_are_not_accepted(self):
        plaintext = json.dumps(make_snapshot()).encode('utf-8')
        with self.assertRaises(server.APIError):
            server.decrypt_backup(plaintext, PASSWORD)

        # A gzip-compressed legacy archive is not a self-contained encrypted backup.
        import gzip
        with self.assertRaises(server.APIError):
            server.decrypt_backup(gzip.compress(plaintext), PASSWORD)

    def test_invalid_json_and_deep_json_fail_safely(self):
        with self.assertRaises(server.APIError) as context:
            server.decrypt_backup(b'not json', PASSWORD)
        self.assertEqual(context.exception.status, 400)

        deeply_nested = (b'[' * 4000) + b'0' + (b']' * 4000)
        with self.assertRaises(server.APIError):
            server.decrypt_backup(deeply_nested, PASSWORD)

    def test_legacy_v1_backup_format_is_rejected(self):
        legacy = {
            'format': 'notki-encrypted-snapshot',
            'version': 1,
            'createdAt': iso_now(),
            'salt': (b's' * 16).hex(),
            'nonce': (b'n' * 12).hex(),
            'ciphertext': base64.b64encode(b'x' * 32).decode('ascii'),
            'iterations': 100_000,
        }
        with self.assertRaises(server.APIError) as context:
            server.decrypt_backup(json.dumps(legacy).encode('utf-8'), PASSWORD)
        self.assertIn('not a valid Notki backup', str(context.exception))

    def test_legacy_snapshot_version_is_rejected(self):
        snapshot = make_snapshot(version=1)
        handler = server._HeadlessRestoreHandler()
        with self.assertRaises(server.APIError) as context:
            handler.restore_snapshot(snapshot, replace_existing=True)
        self.assertIn('Unsupported backup format version', str(context.exception))

    def test_backup_operation_lock_is_non_blocking(self):
        with server.backup_operation():
            with self.assertRaises(server.APIError) as context:
                with server.backup_operation():
                    pass
            self.assertEqual(context.exception.status, 409)
        # The lock must be released after the first operation.
        with server.backup_operation():
            pass


class CLIRestoreTests(unittest.TestCase):
    """Offline restore is the supported path for archives above the HTTP limit."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / 'cli.sqlite3'
        server.initialize_database()
        self.backup_path = Path(self.temp_dir.name) / 'large-backup.enc'

    def tearDown(self):
        server.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_cli_limit_is_larger_than_the_http_limit(self):
        self.assertGreater(server.MAX_CLI_BACKUP_BYTES, server.MAX_BACKUP_FILE_BYTES)

    def test_cli_restore_accepts_an_archive_above_a_small_limit(self):
        note = make_note(body='x' * 4096)
        raw = server.encrypt_backup(make_snapshot(notes=[note]), PASSWORD)
        self.backup_path.write_bytes(raw)

        with self.assertRaises(server.APIError) as context:
            server.decrypt_backup(raw, PASSWORD, max_file_bytes=512, max_snapshot_bytes=256)
        self.assertEqual(context.exception.status, 413)

        result = server.restore_backup_cli(
            self.backup_path, PASSWORD, max_bytes=1024 * 1024,
        )
        self.assertTrue(result['restored'])
        self.assertEqual(result['users'], 1)
        self.assertEqual(result['notes'], 1)

        with server.database() as connection:
            restored_note = connection.execute('SELECT title, body FROM notes').fetchone()
        self.assertEqual(restored_note['title'], note['title'])
        self.assertEqual(restored_note['body'], note['body'])

    def test_cli_restore_rejects_wrong_password_without_data_change(self):
        with server.database() as connection:
            connection.execute(
                'INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)',
                ('kept@example.com', server.hash_password('kept-password-123'), 'admin', iso_now()),
            )
        raw = server.encrypt_backup(make_snapshot(notes=[make_note()]), PASSWORD)
        self.backup_path.write_bytes(raw)

        with self.assertRaises(server.APIError) as context:
            server.restore_backup_cli(self.backup_path, 'wrong password entirely')
        self.assertEqual(context.exception.status, 400)

        with server.database() as connection:
            users = connection.execute('SELECT email FROM users').fetchall()
        self.assertEqual([row['email'] for row in users], ['kept@example.com'])

    def test_cli_restore_enforces_the_configured_size_limit(self):
        raw = server.encrypt_backup(make_snapshot(), PASSWORD)
        self.backup_path.write_bytes(raw)

        with self.assertRaises(server.APIError) as context:
            server.restore_backup_cli(
                self.backup_path, PASSWORD, max_bytes=len(raw) - 1,
            )
        self.assertEqual(context.exception.status, 413)

    def test_main_restore_option_reads_password_file(self):
        note = make_note(title='Restored through CLI')
        raw = server.encrypt_backup(make_snapshot(notes=[note]), PASSWORD)
        self.backup_path.write_bytes(raw)
        password_path = Path(self.temp_dir.name) / 'password.txt'
        password_path.write_text(PASSWORD + '\n', encoding='utf-8')

        stdout = io.StringIO()
        argv = [
            'server.py',
            '--restore-backup', str(self.backup_path),
            '--backup-password-file', str(password_path),
            '--yes',
        ]
        with unittest.mock.patch('sys.argv', argv):
            with contextlib.redirect_stdout(stdout):
                server.main()

        self.assertIn('Restore complete', stdout.getvalue())
        with server.database() as connection:
            restored_note = connection.execute('SELECT title FROM notes').fetchone()
        self.assertEqual(restored_note['title'], 'Restored through CLI')


class TOTPSecretTests(unittest.TestCase):
    def setUp(self):
        self.environment = unittest.mock.patch.dict(
            os.environ, {},
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def test_totp_secret_validation_rejects_malformed_values(self):
        valid = server.generate_totp_secret()
        self.assertEqual(server.validate_totp_secret(valid.lower()), valid)
        for invalid in ('short', 'A' * 15, 'A' * 129, 'INVALID-CHARACTERS!', '=' * 16, 123):
            with self.assertRaises(ValueError):
                server.validate_totp_secret(invalid)


class SnapshotValidationTests(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(server.NotkiHandler)
        self.handler.send_json = lambda data, status=200: None
        self.applied = []
        self.handler._apply_snapshot_data = lambda *args, **kwargs: self.applied.append(args)

    def test_valid_snapshot_is_prepared_before_mutation(self):
        snapshot = make_snapshot(notes=[make_note()])
        self.handler.restore_snapshot(snapshot, replace_existing=True)
        self.assertEqual(len(self.applied), 1)

    def test_unknown_fields_and_versions_are_rejected(self):
        snapshot = make_snapshot()
        snapshot['unexpected'] = True
        with self.assertRaises(server.APIError):
            self.handler.restore_snapshot(snapshot, replace_existing=True)

        for version in (0, 3, 2.0, True, '2', None):
            snapshot = make_snapshot()
            snapshot['version'] = version
            with self.assertRaises(server.APIError):
                self.handler.restore_snapshot(snapshot, replace_existing=True)

        self.assertEqual(self.applied, [])

    def test_orphan_note_and_duplicate_user_are_rejected_before_apply(self):
        snapshot = make_snapshot(notes=[make_note(user_id=999)])
        with self.assertRaises(server.APIError):
            self.handler.restore_snapshot(snapshot, replace_existing=True)

        snapshot = make_snapshot()
        snapshot['users'].append(dict(snapshot['users'][0]))
        with self.assertRaises(server.APIError):
            self.handler.restore_snapshot(snapshot, replace_existing=True)

        self.assertEqual(self.applied, [])

    def test_snapshot_requires_an_administrator(self):
        user = make_snapshot()['users'][0]
        user['role'] = 'user'
        with self.assertRaises(server.APIError):
            self.handler.restore_snapshot(make_snapshot(users=[user]), replace_existing=True)
        self.assertEqual(self.applied, [])

    def test_invalid_totp_secret_in_snapshot_is_rejected(self):
        snapshot = make_snapshot()
        snapshot['users'][0]['totpSecret'] = 'not-a-valid-secret!'
        with self.assertRaises(server.APIError):
            self.handler.restore_snapshot(snapshot, replace_existing=True)
        self.assertEqual(self.applied, [])

    def test_snapshot_size_limits_are_enforced(self):
        snapshot = make_snapshot(notes=[make_note() for _ in range(3)])
        with unittest.mock.patch.object(server, 'MAX_SNAPSHOT_BYTES', 100):
            with self.assertRaises(server.APIError):
                server.encrypt_backup(snapshot, PASSWORD)

    def test_apply_rolls_back_and_returns_a_safe_error(self):
        class FakeCursor:
            rowcount = 0

            def fetchone(self):
                return None

        class FakeConnection:
            def __init__(self):
                self.rolled_back = False

            def execute(self, sql, *args):
                if sql.startswith('SELECT 1 WHERE'):
                    return type('Row', (), {'fetchone': lambda self: None})()
                return FakeCursor()

            def executemany(self, sql, rows):
                if 'INSERT INTO notes' in sql:
                    raise sqlite3.IntegrityError('forced failure')

            def rollback(self):
                self.rolled_back = True

        fake = FakeConnection()

        @contextlib.contextmanager
        def fake_database():
            yield fake

        prepared_users = [(1, 'a@example.com', server.hash_password('password123456'), 'admin', iso_now(), None, '[]', None, None, None)]
        prepared_notes = [('n', 1, 't', 'b', 0, 'default', '[]', 0, 0, 0, iso_now(), iso_now(), 0.0, None)]

        prepared_data = {
            'users': prepared_users,
            'notes': prepared_notes,
            'invites': [],
            'shares': [],
            'passkeys': [],
            'settings': [],
        }

        with unittest.mock.patch.object(server, 'database', fake_database):
            with self.assertRaises(server.APIError) as context:
                server.NotkiHandler._apply_snapshot_data(
                    self.handler, prepared_data, True,
                )

        self.assertTrue(fake.rolled_back)
        self.assertEqual(context.exception.status, 500)
        self.assertIn('No data was changed', str(context.exception))


class BackupHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / 'test.sqlite3'
        server.initialize_database()
        with server.database() as connection:
            connection.execute(
                'INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)',
                ('admin@example.com', server.hash_password('secure-passphrase-1'), 'admin', server.iso_time()),
            )
        self.http_server = server.ThreadingHTTPServer(('127.0.0.1', 0), server.NotkiHandler)
        self.thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f'http://127.0.0.1:{self.http_server.server_port}'
        self.admin = self.new_client()
        status, _ = self.request(self.admin, 'POST', '/api/login', {
            'email': 'admin@example.com', 'password': 'secure-passphrase-1',
        })
        self.assertEqual(status, 200)

    def tearDown(self):
        self.http_server.shutdown()
        self.http_server.server_close()
        self.thread.join(timeout=2)
        server.DB_PATH = self.original_db_path
        server.FAILED_AUTH_ATTEMPTS.clear()
        server.FAILED_AUTH_ACCOUNTS.clear()
        server.TEMP_2FA_TOKENS.clear()
        self.temp_dir.cleanup()

    @staticmethod
    def new_client():
        return build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, client, method, path, payload=None, headers=None):
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            headers=with_same_origin(self.base_url, {'Content-Type': 'application/json', **(headers or {})}),
            method=method,
        )
        try:
            with client.open(request) as response:
                return response.status, json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            status = error.code
            body = json.loads(error.read().decode('utf-8'))
            error.close()
            return status, body

    def request_raw(self, client, method, path, body=None, content_type='application/octet-stream', headers=None):
        request = Request(
            self.base_url + path,
            data=body,
            headers=with_same_origin(self.base_url, {'Content-Type': content_type, **(headers or {})}),
            method=method,
        )
        try:
            with client.open(request) as response:
                return response.status, response.read()
        except HTTPError as error:
            status = error.code
            body = error.read()
            error.close()
            return status, body

    def register_user(self, email, password='user-passphrase-123'):
        _, invite = self.request(self.admin, 'POST', '/api/admin/invites', {})
        token = parse_qs(urlsplit(invite['url']).query)['invite'][0]
        client = self.new_client()
        status, _ = self.request(client, 'POST', '/api/register', {
            'email': email, 'password': password, 'invite': token,
        })
        self.assertEqual(status, 201)
        return client

    def create_backup(self, password=PASSWORD):
        status, backup = self.request(
            self.admin, 'POST', '/api/admin/backups', {}, {'X-Backup-Password': password},
        )
        self.assertEqual(status, 201)
        return backup

    @unittest.mock.patch('server.get_backup_password', return_value='secret-backup-pass')
    def test_create_backup_requires_password_and_returns_only_ciphertext(self, mock_pw):
        # The password is now handled server-side, so create_backup should just succeed when get_backup_password returns one
        backup = self.create_backup()
        self.assertTrue(backup['filename'].endswith('.enc'))
        self.assertTrue(backup['encrypted'])
        self.assertEqual(backup['formatVersion'], 2)

        backup_path = server.backup_directory() / backup['filename']
        raw = backup_path.read_bytes()
        document = decode_backup_document(raw)
        self.assertEqual(document['format'], server.BACKUP_FORMAT)
        self.assertNotIn('admin@example.com', raw.decode('utf-8'))
        self.assertNotIn(PASSWORD, raw.decode('utf-8'))
        self.assertNotIn('passwordHash', raw.decode('utf-8'))

        status, body = self.request_raw(self.admin, 'GET', f"/api/admin/backups/{backup['filename']}")
        self.assertEqual(status, 200)
        self.assertEqual(body, raw)

        status, listing = self.request(self.admin, 'GET', '/api/admin/backups')
        self.assertEqual(status, 200)
        self.assertEqual([item['filename'] for item in listing['backups']], [backup['filename']])

    @unittest.mock.patch('server.get_backup_password', return_value='secret-backup-pass')
    def test_wrong_or_missing_password_does_not_change_existing_data(self, mock_pw):
        self.request(self.admin, 'PUT', '/api/notes', {'notes': [make_note('before', title='Before')]})
        backup = self.create_backup()
        self.request(self.admin, 'PUT', '/api/notes', {'notes': [make_note('after', title='After')]})

        mock_pw.return_value = 'wrong password entirely'
        status, _ = self.request(
            self.admin, 'POST', f"/api/admin/backups/{backup['filename']}/restore", {},
        )
        self.assertEqual(status, 400)
        status, notes = self.request(self.admin, 'GET', '/api/notes')
        self.assertEqual(status, 200)
        self.assertEqual([note['id'] for note in notes['notes']], ['after'])

        status, _ = self.request(
            self.admin, 'POST', f"/api/admin/backups/{backup['filename']}/restore", {},
        )
        self.assertEqual(status, 400)
        status, notes = self.request(self.admin, 'GET', '/api/notes')
        self.assertEqual([note['id'] for note in notes['notes']], ['after'])

        mock_pw.return_value = 'secret-backup-pass'
        status, restored = self.request(
            self.admin, 'POST', f"/api/admin/backups/{backup['filename']}/restore", {},
        )
        self.assertEqual(status, 200)
        self.assertTrue(restored['restored'])

        status, session = self.request(self.admin, 'GET', '/api/session')
        self.assertEqual(status, 200)
        self.assertIsNone(session['user'])

        restored_admin = self.new_client()
        status, _ = self.request(restored_admin, 'POST', '/api/login', {
            'email': 'admin@example.com', 'password': 'secure-passphrase-1',
        })
        self.assertEqual(status, 200)
        status, notes = self.request(restored_admin, 'GET', '/api/notes')
        self.assertEqual([note['id'] for note in notes['notes']], ['before'])

    def test_restore_is_atomic_when_snapshot_validation_fails(self):
        self.request(self.admin, 'PUT', '/api/notes', {'notes': [make_note('keep', title='Keep me')]})
        invalid = server.encrypt_backup(
            make_snapshot(notes=[make_note('orphan', user_id=999)]), PASSWORD,
        )

        status, body = self.request_raw(
            self.admin, 'POST', '/api/admin/backups/upload-restore', invalid,
            headers={'X-Backup-Password': PASSWORD},
        )
        self.assertEqual(status, 400)
        self.assertNotIn(b'keep', body)

        status, notes = self.request(self.admin, 'GET', '/api/notes')
        self.assertEqual(status, 200)
        self.assertEqual([note['id'] for note in notes['notes']], ['keep'])

    @unittest.mock.patch('server.get_backup_password', return_value='secret-backup-pass')
    def test_non_admin_cannot_create_restore_or_list_backups(self, mock_pw):
        backup = self.create_backup()
        raw = (server.backup_directory() / backup['filename']).read_bytes()
        user = self.register_user('normal@example.com')

        status, _ = self.request(user, 'POST', '/api/admin/backups', {}, {'X-Backup-Password': PASSWORD})
        self.assertEqual(status, 403)
        status, _ = self.request(user, 'GET', '/api/admin/backups')
        self.assertEqual(status, 403)
        status, _ = self.request_raw(
            user, 'POST', '/api/admin/backups/upload-restore', raw,
            headers={'X-Backup-Password': PASSWORD},
        )
        self.assertEqual(status, 403)

    @unittest.mock.patch('server.get_backup_password', return_value='secret-backup-pass')
    def test_plaintext_and_legacy_plaintext_uploads_are_rejected(self, mock_pw):
        plaintext = json.dumps(make_snapshot()).encode('utf-8')
        status, body = self.request_raw(
            self.admin, 'POST', '/api/admin/backups/upload-restore', plaintext,
            headers={'X-Backup-Password': PASSWORD},
        )
        self.assertEqual(status, 400)
        self.assertIn(b'not a valid Notki backup', body)

        import gzip
        status, body = self.request_raw(
            self.admin, 'POST', '/api/admin/backups/upload-restore', gzip.compress(plaintext),
            headers={'X-Backup-Password': PASSWORD},
        )
        self.assertEqual(status, 400)

    @unittest.mock.patch('server.get_backup_password', return_value='secret-backup-pass')
    def test_legacy_encrypted_backup_upload_is_rejected(self, mock_pw):
        legacy = json.dumps({
            'format': 'notki-encrypted-snapshot',
            'version': 1,
            'createdAt': iso_now(),
            'salt': (b's' * 16).hex(),
            'nonce': (b'n' * 12).hex(),
            'ciphertext': base64.b64encode(b'x' * 32).decode('ascii'),
            'iterations': 100_000,
        }).encode('utf-8')

        status, body = self.request_raw(
            self.admin, 'POST', '/api/admin/backups/upload-restore', legacy,
            headers={'X-Backup-Password': PASSWORD},
        )
        self.assertEqual(status, 400)
        self.assertIn(b'not a valid Notki backup', body)

    @unittest.mock.patch('server.get_backup_password', return_value='secret-backup-pass')
    def test_totp_secret_survives_restore_and_replay_is_rejected(self, mock_pw):
        user = self.register_user('restored2fa@example.com')
        status, res = self.request(user, 'POST', '/api/account/totp', {})
        secret = res['secret']
        status, _ = self.request(user, 'POST', '/api/account/totp/verify', {
            'code': server.compute_totp_code(secret),
        })
        self.assertEqual(status, 200)

        backup = self.create_backup()
        status, _ = self.request(
            self.admin, 'POST', f"/api/admin/backups/{backup['filename']}/restore", {},
            {'X-Backup-Password': PASSWORD},
        )
        self.assertEqual(status, 200)

        client = self.new_client()
        status, res = self.request(client, 'POST', '/api/login', {
            'email': 'restored2fa@example.com', 'password': 'user-passphrase-123',
        })
        self.assertEqual(status, 200)
        self.assertTrue(res['requires2FA'])
        next_counter = int(server.time.time() // server.TOTP_PERIOD_SECONDS) + 1
        next_code = server.compute_totp_code(secret, counter=next_counter)
        with unittest.mock.patch('server.time.time', return_value=(next_counter * 30) + 5):
            status, login = self.request(client, 'POST', '/api/login/2fa', {
                'tempToken': res['tempToken'], 'totpCode': next_code,
            })
        self.assertEqual(status, 200)
        self.assertEqual(login['user']['email'], 'restored2fa@example.com')

        # The same time step must not be accepted a second time.
        status, res = self.request(self.new_client(), 'POST', '/api/login', {
            'email': 'restored2fa@example.com', 'password': 'user-passphrase-123',
        })
        self.assertEqual(status, 200)
        with unittest.mock.patch('server.time.time', return_value=(next_counter * 30) + 5):
            status, _ = self.request(client, 'POST', '/api/login/2fa', {
                'tempToken': res['tempToken'], 'totpCode': next_code,
            })
        self.assertEqual(status, 401)

        with server.database() as connection:
            stored = connection.execute(
                "SELECT totp_secret FROM users WHERE email = 'restored2fa@example.com'",
            ).fetchone()['totp_secret']
        self.assertEqual(secret, stored)

    def test_plaintext_json_and_symlinks_are_not_listed_or_served(self):
        backup_dir = server.backup_directory()
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / 'notki-old.json').write_text(json.dumps(make_snapshot()), encoding='utf-8')

        status, listing = self.request(self.admin, 'GET', '/api/admin/backups')
        self.assertEqual(status, 200)
        self.assertEqual(listing['backups'], [])

        status, _ = self.request(self.admin, 'GET', '/api/admin/backups/notki-old.json')
        self.assertEqual(status, 404)

        outside = Path(self.temp_dir.name) / 'outside.txt'
        outside.write_text('sensitive data', encoding='utf-8')
        link = backup_dir / 'notki-linked.enc'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            return
        status, _ = self.request(self.admin, 'GET', '/api/admin/backups/notki-linked.enc')
        self.assertEqual(status, 404)
        status, listing = self.request(self.admin, 'GET', '/api/admin/backups')
        self.assertEqual(listing['backups'], [])

    def test_oversized_upload_is_rejected(self):
        with unittest.mock.patch.object(server, 'MAX_BACKUP_FILE_BYTES', 64):
            status, body = self.request_raw(
                self.admin, 'POST', '/api/admin/backups/upload-restore', b'x' * 256,
                headers={'X-Backup-Password': PASSWORD},
            )
        self.assertEqual(status, 413)
        self.assertIn(b'too large', body.lower())

    @unittest.mock.patch('server.get_backup_password', return_value='secret-backup-pass')
    def test_secrets_do_not_appear_in_logs_or_error_responses(self, mock_pw):
        backup = self.create_backup()
        mock_pw.return_value = 'wrong password entirely'
        status, body = self.request(
            self.admin, 'POST', f"/api/admin/backups/{backup['filename']}/restore", {},
        )
        self.assertEqual(status, 400)
        self.assertNotIn(PASSWORD, body['error'])
        self.assertNotIn('wrong password entirely', body['error'])

        logs = '\n'.join(str(entry) for entry in server.LOG_BUFFER)
        self.assertNotIn(PASSWORD, logs)
        self.assertNotIn('wrong password entirely', logs)


if __name__ == '__main__':
    unittest.main()
