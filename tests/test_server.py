import base64
import hashlib
import os
import secrets
import http.cookiejar
import io
import json
import tarfile
import tempfile
import threading
from datetime import timedelta
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
import urllib.request
import urllib.error
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import server


BACKUP_PASSWORD = 'test-backup-password-123'


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


class ServerUnitTests(unittest.TestCase):
    def test_normalize_email_valid(self):
        self.assertEqual(server.normalize_email('user@example.com'), 'user@example.com')
        self.assertEqual(server.normalize_email('  user@example.com  '), 'user@example.com')
        self.assertEqual(server.normalize_email('USER@EXAMPLE.COM'), 'user@example.com')
        self.assertEqual(server.normalize_email('u.ser+tag@sub.example.co.uk'), 'u.ser+tag@sub.example.co.uk')

    def test_consume_temp_2fa_token(self):
        user_id = 123
        # Test normal consumption
        token = server.create_temp_2fa_token(user_id)
        self.assertIsNotNone(token)
        self.assertEqual(server.consume_temp_2fa_token(token), user_id)

        # Test token is one-time use
        self.assertIsNone(server.consume_temp_2fa_token(token))

        # Test with None or empty string
        self.assertIsNone(server.consume_temp_2fa_token(None))
        self.assertIsNone(server.consume_temp_2fa_token(''))

        # Test expiration
        token2 = server.create_temp_2fa_token(user_id)
        # Mock time to be 6 minutes in the future (expires in 5 minutes)
        future_time = server.utc_now() + timedelta(minutes=6)
        with unittest.mock.patch('server.utc_now', return_value=future_time):
            self.assertIsNone(server.consume_temp_2fa_token(token2))

    def test_utc_now(self):
        now = server.utc_now()
        self.assertEqual(now.tzinfo, timezone.utc)
        self.assertEqual(now.microsecond, 0)
        self.assertIsInstance(now, datetime)

        with unittest.mock.patch('server.datetime') as mock_datetime:
            mock_now = datetime(2023, 10, 21, 12, 0, 0, 123456, tzinfo=timezone.utc)
            class MockDatetimeNow:
                def replace(self, **kwargs):
                    return mock_now.replace(**kwargs)
            mock_datetime.now.return_value = MockDatetimeNow()

            result = server.utc_now()

            mock_datetime.now.assert_called_once_with(timezone.utc)
            self.assertEqual(result.microsecond, 0)

    def test_iso_time(self):
        fixed_time = datetime(2023, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(server.iso_time(fixed_time), '2023-10-21T12:00:00+00:00')

        with unittest.mock.patch('server.utc_now', return_value=fixed_time):
            self.assertEqual(server.iso_time(), '2023-10-21T12:00:00+00:00')

    def test_backup_directory(self):
        # Scenario 1: NOTKI_BACKUP_DIR is not set
        with unittest.mock.patch.dict('os.environ', {}, clear=True):
            expected_fallback = server.DB_PATH.parent / 'backups'
            self.assertEqual(server.backup_directory(), expected_fallback)

        # Scenario 2: NOTKI_BACKUP_DIR is set
        with unittest.mock.patch.dict('os.environ', {'NOTKI_BACKUP_DIR': '/custom/backup/dir'}, clear=True):
            self.assertEqual(server.backup_directory(), Path('/custom/backup/dir'))

    def test_account_key(self):
        self.assertEqual(server.account_key('USER@EXAMPLE.COM'), 'user@example.com')
        self.assertEqual(server.account_key('  User@Example.Com  '), 'user@example.com')
        self.assertEqual(server.account_key('user@example.com'), 'user@example.com')
        self.assertEqual(server.account_key(''), '')
        self.assertEqual(server.account_key(None), '')
        self.assertEqual(server.account_key('   '), '')
        self.assertEqual(server.account_key(123), '123')
        # Test casefolding vs lowercasing
        self.assertEqual(server.account_key('ß'), 'ss')

    def test_normalize_email_invalid(self):
        invalid_emails = [
            None,
            '',
            ' ',
            'userexample.com',
            'user@example@com',
            '@example.com',
            'user@',
            'user@example',
            'user @example.com',
            'user@ example.com',
            'a' * 245 + '@example.com',  # Length 245 + 12 = 257 > 254
        ]
        for email in invalid_emails:
            with self.subTest(email=email):
                with self.assertRaises(ValueError, msg=f'Expected ValueError for: {email}'):
                    server.normalize_email(email)


class TestAddLog(unittest.TestCase):
    def setUp(self):
        # Save original state
        self.original_log_buffer = server.LOG_BUFFER[:]
        self.original_max_entries = server.MAX_LOG_ENTRIES
        # Clear log buffer for testing
        server.LOG_BUFFER.clear()

    def tearDown(self):
        # Restore original state
        server.LOG_BUFFER[:] = self.original_log_buffer
        server.MAX_LOG_ENTRIES = self.original_max_entries

    def test_add_log_basic(self):
        server.add_log('INFO', 'Test message')
        self.assertEqual(len(server.LOG_BUFFER), 1)
        entry = server.LOG_BUFFER[0]
        self.assertEqual(entry['level'], 'INFO')
        self.assertEqual(entry['message'], 'Test message')
        self.assertIn('time', entry)

    def test_add_log_capacity(self):
        server.MAX_LOG_ENTRIES = 3
        server.add_log('INFO', 'Msg 1')
        server.add_log('INFO', 'Msg 2')
        server.add_log('INFO', 'Msg 3')
        server.add_log('INFO', 'Msg 4')

        self.assertEqual(len(server.LOG_BUFFER), 3)
        self.assertEqual(server.LOG_BUFFER[0]['message'], 'Msg 2')
        self.assertEqual(server.LOG_BUFFER[1]['message'], 'Msg 3')
        self.assertEqual(server.LOG_BUFFER[2]['message'], 'Msg 4')

    def test_add_log_concurrency(self):
        server.MAX_LOG_ENTRIES = 100

        def worker(worker_id):
            for i in range(10):
                server.add_log('INFO', f'Worker {worker_id} msg {i}')

        threads = [threading.Thread(target=worker, args=(w,)) for w in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(server.LOG_BUFFER), 50)


class ServerFlowTests(unittest.TestCase):
    avatar_data = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

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
        self.http_server = ThreadingHTTPServer(('127.0.0.1', 0), server.NotkiHandler)
        self.thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f'http://127.0.0.1:{self.http_server.server_port}'
        self.admin = self.new_client()
        self.request(self.admin, 'POST', '/api/login', {'email': 'admin@example.com', 'password': 'secure-passphrase-1'})

    def tearDown(self):
        self.http_server.shutdown()
        self.http_server.server_close()
        self.thread.join(timeout=2)
        server.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()
        server.FAILED_AUTH_ATTEMPTS.clear()
        server.TEMP_2FA_TOKENS.clear()

    @staticmethod
    def new_client():
        return build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request_raw_client(self, client, method, path, body, content_type='application/gzip', headers=None):
        request = Request(
            self.base_url + path,
            data=body,
            headers=with_same_origin(self.base_url, {'Content-Type': content_type, **(headers or {})}),
            method=method,
        )
        try:
            with client.open(request) as response:
                return response.status, json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            status = error.code
            payload = json.loads(error.read().decode('utf-8'))
            error.close()
            return status, payload

    def request_with_response_headers(self, client, method, path, payload=None, headers=None):
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            headers=with_same_origin(self.base_url, {'Content-Type': 'application/json', **(headers or {})}),
            method=method,
        )
        try:
            with client.open(request) as response:
                return response.status, json.loads(response.read().decode('utf-8')), response.headers
        except HTTPError as error:
            status = error.code
            payload = json.loads(error.read().decode('utf-8'))
            headers = error.headers
            error.close()
            return status, payload, headers

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
            payload = json.loads(error.read().decode('utf-8'))
            error.close()
            return status, payload

    def register_user(self, email, password='another-secure-password'):
        """Create an invited account and return a signed-in client for it."""
        _, invite = self.request(self.admin, 'POST', '/api/admin/invites', {})
        token = parse_qs(urlsplit(invite['url']).query)['invite'][0]
        client = self.new_client()
        status, _ = self.request(client, 'POST', '/api/register', {'email': email, 'password': password, 'invite': token})
        self.assertEqual(status, 201)
        return client

    def enable_admin_2fa(self):
        """Configure TOTP for the default admin so require2FA can be enabled safely."""
        status, res = self.request(
            self.admin, 'POST', '/api/account/totp',
            headers={'X-Step-Up-Password': 'secure-passphrase-1'},
        )
        self.assertEqual(status, 200)
        code = server.compute_totp_code(res['secret'])
        status, _ = self.request(
            self.admin, 'POST', '/api/account/totp/verify', {'code': code},
            headers={'X-Step-Up-Password': 'secure-passphrase-1'},
        )
        self.assertEqual(status, 200)

    @staticmethod
    def note_payload(note_id, title, body='Treść', due_date=None):
        payload = {
            'id': note_id, 'title': title, 'body': body, 'bodyFormat': 0, 'color': 'default', 'tags': [],
            'pinned': False, 'archived': False, 'deleted': False,
            'createdAt': server.iso_time(), 'updatedAt': server.iso_time(), 'order': 1,
        }
        if due_date is not None:
            payload['dueDate'] = due_date
        return payload

    def test_sharing_grants_read_and_write_access(self):
        owner = self.register_user('owner@example.com')
        reader = self.register_user('reader@example.com')
        writer = self.register_user('writer@example.com')

        self.request(owner, 'PUT', '/api/notes', {'notes': [self.note_payload('shared-1', 'Wspólna')]})

        status, result = self.request(owner, 'POST', '/api/notes/shared-1/shares', {'email': 'reader@example.com', 'permission': 'read'})
        self.assertEqual(status, 201)
        self.assertEqual([share['permission'] for share in result['shares']], ['read'])

        status, result = self.request(owner, 'POST', '/api/notes/shared-1/shares', {'email': 'writer@example.com', 'permission': 'write'})
        self.assertEqual(status, 201)
        self.assertEqual(len(result['shares']), 2)

        # The recipient sees the note with the owner and the granted permission attached.
        status, shared = self.request(reader, 'GET', '/api/shared')
        self.assertEqual(status, 200)
        self.assertEqual(len(shared['notes']), 1)
        self.assertEqual(shared['notes'][0]['id'], 'shared-1')
        self.assertEqual(shared['notes'][0]['ownerEmail'], 'owner@example.com')
        self.assertEqual(shared['notes'][0]['permission'], 'read')

        # A read-only recipient cannot change the note.
        status, error = self.request(reader, 'PUT', '/api/shared/shared-1', {'title': 'Podmienione', 'body': 'x'})
        self.assertEqual(status, 403)
        self.assertIn('permission', error['error'])

        # A recipient with write access can.
        status, _ = self.request(writer, 'PUT', '/api/shared/shared-1', {'title': 'Zaktualizowana', 'body': 'Nowa treść', 'bodyFormat': 0, 'color': 'mint', 'tags': ['praca']})
        self.assertEqual(status, 200)
        status, notes = self.request(owner, 'GET', '/api/notes')
        self.assertEqual(notes['notes'][0]['title'], 'Zaktualizowana')
        self.assertEqual(notes['notes'][0]['body'], 'Nowa treść')
        self.assertEqual(notes['notes'][0]['color'], 'mint')

        # The recipient's own note list stays untouched by the shared write.
        status, own = self.request(writer, 'GET', '/api/notes')
        self.assertEqual(own['notes'], [])

        # Revoking removes the note from the recipient's shared list.
        status, shares = self.request(owner, 'GET', '/api/notes/shared-1/shares')
        reader_id = next(share['userId'] for share in shares['shares'] if share['email'] == 'reader@example.com')
        status, result = self.request(owner, 'DELETE', f'/api/notes/shared-1/shares/{reader_id}', {})
        self.assertEqual(status, 200)
        self.assertEqual(len(result['shares']), 1)
        status, shared = self.request(reader, 'GET', '/api/shared')
        self.assertEqual(shared['notes'], [])

    def test_sharing_rejects_invalid_targets_and_foreign_notes(self):
        owner = self.register_user('owner2@example.com')
        other = self.register_user('other2@example.com')
        self.request(owner, 'PUT', '/api/notes', {'notes': [self.note_payload('mine-1', 'Moja')]})

        status, error = self.request(owner, 'POST', '/api/notes/mine-1/shares', {'email': 'owner2@example.com', 'permission': 'read'})
        self.assertEqual(status, 400)
        self.assertIn('yourself', error['error'])

        status, result = self.request(owner, 'POST', '/api/notes/mine-1/shares', {'email': 'nobody@example.com', 'permission': 'read'})
        self.assertEqual(status, 201)
        self.assertEqual(result['shares'], [])

        status, error = self.request(owner, 'POST', '/api/notes/mine-1/shares', {'email': 'other2@example.com', 'permission': 'admin'})
        self.assertEqual(status, 400)
        self.assertIn('permission', error['error'])

        # A non-owner cannot list, grant or revoke shares on someone else's note.
        status, _ = self.request(other, 'GET', '/api/notes/mine-1/shares')
        self.assertEqual(status, 404)
        status, _ = self.request(other, 'POST', '/api/notes/mine-1/shares', {'email': 'owner2@example.com', 'permission': 'read'})
        self.assertEqual(status, 404)
        status, _ = self.request(other, 'DELETE', '/api/notes/mine-1/shares/1', {})
        self.assertEqual(status, 404)

        # A note that was never shared is invisible to the other account.
        status, shared = self.request(other, 'GET', '/api/shared')
        self.assertEqual(shared['notes'], [])
        status, error = self.request(other, 'PUT', '/api/shared/mine-1', {'title': 'x', 'body': 'y'})
        self.assertEqual(status, 404)

    def test_save_notes_preserves_existing_shares(self):
        owner = self.register_user('owner_save@example.com')
        reader = self.register_user('reader_save@example.com')
        self.request(owner, 'PUT', '/api/notes', {'notes': [self.note_payload('note-share-1', 'Notes before save')]})
        self.request(owner, 'POST', '/api/notes/note-share-1/shares', {'email': 'reader_save@example.com', 'permission': 'write'})

        status, shared = self.request(reader, 'GET', '/api/shared')
        self.assertEqual(status, 200)
        self.assertEqual(len(shared['notes']), 1)

        # Owner saves notes again
        self.request(owner, 'PUT', '/api/notes', {'notes': [self.note_payload('note-share-1', 'Notes after save')]})

        # Verify reader still has access to the shared note
        status, shared = self.request(reader, 'GET', '/api/shared')
        self.assertEqual(status, 200)
        self.assertEqual(len(shared['notes']), 1)
        self.assertEqual(shared['notes'][0]['title'], 'Notes after save')

    def test_shares_survive_server_backup_restore(self):
        owner = self.register_user('owner3@example.com')
        reader = self.register_user('reader3@example.com')
        self.request(owner, 'PUT', '/api/notes', {'notes': [self.note_payload('backup-1', 'Kopia')]})
        self.request(owner, 'POST', '/api/notes/backup-1/shares', {'email': 'reader3@example.com', 'permission': 'write'})

        status, backup = self.request(self.admin, 'POST', '/api/admin/backups', {}, {'X-Backup-Password': BACKUP_PASSWORD})
        self.assertEqual(status, 201)

        status, backup_list = self.request(self.admin, 'GET', '/api/admin/backups')
        self.assertEqual(status, 200)
        matching_backup = next(b for b in backup_list['backups'] if b['filename'] == backup['filename'])

        status, result = self.request(
            self.admin, 'POST', f"/api/admin/backups/{backup['filename']}/restore", {},
            {'X-Backup-Password': BACKUP_PASSWORD},
        )
        self.assertEqual(status, 200)
        self.assertEqual(result['shares'], 1)

        # Restoring replaces every account, so the recipient has to sign in again.
        status, _ = self.request(reader, 'POST', '/api/login', {'email': 'reader3@example.com', 'password': 'another-secure-password'})
        self.assertEqual(status, 200)
        status, shared = self.request(reader, 'GET', '/api/shared')
        self.assertEqual(len(shared['notes']), 1)
        self.assertEqual(shared['notes'][0]['permission'], 'write')

    def test_invitation_registration_notes_and_admin_statistics(self):
        status, empty_summary = self.request(self.admin, 'GET', '/api/admin/summary')
        self.assertEqual(status, 200)
        self.assertEqual(empty_summary['stats']['notes'], 0)
        self.assertEqual(empty_summary['stats']['pendingInvites'], 0)

        status, invite = self.request(self.admin, 'POST', '/api/admin/invites', {})
        self.assertEqual(status, 201)
        invite_token = parse_qs(urlsplit(invite['url']).query)['invite'][0]

        user_client = self.new_client()
        status, result = self.request(user_client, 'POST', '/api/register', {
            'email': 'user@example.com',
            'password': 'another-secure-password',
            'invite': invite_token,
        })
        self.assertEqual(status, 201)
        self.assertFalse(result['user']['isAdmin'])

        note = {
            'id': 'note-1', 'title': 'Pierwsza', 'body': 'Treść', 'bodyFormat': 0,
            'color': 'mint', 'tags': ['praca'], 'pinned': False, 'archived': False,
            'deleted': False, 'createdAt': server.iso_time(), 'updatedAt': server.iso_time(), 'order': 1,
        }
        status, _ = self.request(user_client, 'PUT', '/api/notes', {'notes': [note]})
        self.assertEqual(status, 200)
        status, backup = self.request(self.admin, 'POST', '/api/admin/backups', {}, {'X-Backup-Password': BACKUP_PASSWORD})
        self.assertEqual(status, 201)
        self.assertRegex(backup['filename'], r'^notki-backup-\d{8}-\d{6}Z-[a-f0-9]{8}\.enc$')
        status, backups = self.request(self.admin, 'GET', '/api/admin/backups')
        self.assertEqual(status, 200)
        self.assertEqual(backups['backups'][0]['filename'], backup['filename'])
        request = Request(self.base_url + f"/api/admin/backups/{backup['filename']}")
        with self.admin.open(request) as response:
            archive = response.read()
            self.assertTrue('application/json' in response.headers.get_content_type())
        self.assertTrue(archive.startswith(b'{'))
        status, result = self.request(user_client, 'GET', '/api/notes')
        self.assertEqual(status, 200)
        self.assertEqual(result['notes'][0]['title'], 'Pierwsza')
        status, admin_notes = self.request(self.admin, 'GET', '/api/notes')
        self.assertEqual(status, 200)
        self.assertEqual(admin_notes['notes'], [])
        status, _ = self.request(user_client, 'GET', '/api/admin/backups')
        self.assertEqual(status, 403)
        status, _ = self.request(user_client, 'POST', '/api/admin/backups', {})
        self.assertEqual(status, 403)

        status, _ = self.request(user_client, 'GET', '/api/admin/summary')
        self.assertEqual(status, 403)
        status, summary = self.request(self.admin, 'GET', '/api/admin/summary')
        self.assertEqual(status, 200)
        self.assertEqual(summary['stats']['users'], 2)
        self.assertEqual(summary['stats']['notes'], 1)
        self.assertEqual(summary['stats']['active'], 1)
        self.assertEqual(len(summary['users']), 2)

        status, error = self.request(self.new_client(), 'POST', '/api/register', {
            'email': 'second@example.com',
            'password': 'another-secure-password',
            'invite': invite_token,
        })
        self.assertEqual(status, 403)
        self.assertIn('invitation', error['error'].lower())

    def test_save_notes_with_due_date_and_snapshot(self):
        owner = self.register_user('duedate_owner@example.com')
        payload = [
            self.note_payload('due-1', 'Plan Dnia Task', due_date='2026-10-20T10:00')
        ]
        status, _ = self.request(owner, 'PUT', '/api/notes', {'notes': payload})
        self.assertEqual(status, 200)

        status, notes_resp = self.request(owner, 'GET', '/api/notes')
        self.assertEqual(status, 200)
        self.assertEqual(len(notes_resp['notes']), 1)
        self.assertEqual(notes_resp['notes'][0]['dueDate'], '2026-10-20T10:00')

    def test_log_message_handles_missing_path_and_command(self):
        import socket
        # Send a malformed raw HTTP request to trigger server's parse_request error and log_message
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(('127.0.0.1', self.http_server.server_port))
        s.sendall(b'INVALID_REQUEST_LINE\r\n\r\n')
        s.recv(1024)
        s.close()

        # Also test log_message directly on a mock handler without path or command attributes
        class MockHandler(server.NotkiHandler):
            def __init__(self):
                self.client_address = ('127.0.0.1', 12345)

        handler = MockHandler()
        # Should not raise AttributeError when logging
        handler.log_message('%s', 'test error log')

    def test_login_user_enumeration_timing_mitigation(self):
        # Verify that non-existent user and wrong password return identical error responses
        status1, res1 = self.request(self.new_client(), 'POST', '/api/login', {
            'email': 'nonexistent@example.com', 'password': 'wrong-password-123'
        })
        status2, res2 = self.request(self.new_client(), 'POST', '/api/login', {
            'email': 'admin@example.com', 'password': 'wrong-password-123'
        })
        self.assertEqual(status1, 401)
        self.assertEqual(status2, 401)
        self.assertEqual(res1, res2)

    def test_delete_invitation_by_admin(self):
        status, invite = self.request(self.admin, 'POST', '/api/admin/invites', {})
        self.assertEqual(status, 201)

        status, summary = self.request(self.admin, 'GET', '/api/admin/summary')
        self.assertEqual(status, 200)
        self.assertTrue(len(summary['invites']) > 0)
        token_hash = summary['invites'][0]['tokenHash']
        self.assertTrue(bool(token_hash))

        status, result = self.request(self.admin, 'DELETE', f'/api/admin/invites/{token_hash}')
        self.assertEqual(status, 200)
        self.assertEqual(result['deleted'], token_hash)

        status, summary_after = self.request(self.admin, 'GET', '/api/admin/summary')
        self.assertEqual(status, 200)
        self.assertNotIn(token_hash, [inv['tokenHash'] for inv in summary_after['invites']])

        status, result = self.request(self.admin, 'DELETE', f'/api/admin/invites/{token_hash}')
        self.assertEqual(status, 404)

    def test_password_change_rate_limiting(self):
        for _ in range(15):
            status, _ = self.request(self.admin, 'POST', '/api/account/password', {
                'currentPassword': 'wrong-passphrase', 'newPassword': 'brand-new-passphrase-1',
            })
            self.assertEqual(status, 403)
        status, result = self.request(self.admin, 'POST', '/api/account/password', {
            'currentPassword': 'wrong-passphrase', 'newPassword': 'brand-new-passphrase-1',
        })
        self.assertEqual(status, 429)

    def test_verify_totp_rate_limiting(self):
        # Trigger TOTP setup so we have a secret to fail against
        status, _ = self.request(
            self.admin, 'POST', '/api/account/totp',
            headers={'X-Step-Up-Password': 'secure-passphrase-1'},
        )
        self.assertEqual(status, 200)

        # 15 failed attempts should return 400
        for _ in range(15):
            status, _ = self.request(
                self.admin, 'POST', '/api/account/totp/verify', {'code': '000000'},
                headers={'X-Step-Up-Password': 'secure-passphrase-1'},
            )
            self.assertEqual(status, 400)

        # The 16th attempt should be rate limited and return 429
        status, _ = self.request(
            self.admin, 'POST', '/api/account/totp/verify', {'code': '000000'},
            headers={'X-Step-Up-Password': 'secure-passphrase-1'},
        )
        self.assertEqual(status, 429)

    def test_password_change_requires_current_password_and_keeps_session(self):
        status, _ = self.request(self.admin, 'POST', '/api/account/password', {
            'currentPassword': 'wrong-passphrase', 'newPassword': 'brand-new-passphrase-1',
        })
        self.assertEqual(status, 403)

        status, _ = self.request(self.admin, 'POST', '/api/account/password', {
            'currentPassword': 'secure-passphrase-1', 'newPassword': 'short',
        })
        self.assertEqual(status, 400)

        status, result = self.request(self.admin, 'POST', '/api/account/password', {
            'currentPassword': 'secure-passphrase-1', 'newPassword': 'brand-new-passphrase-1',
        })
        self.assertEqual(status, 200)
        self.assertTrue(result['changed'])

        status, session = self.request(self.admin, 'GET', '/api/session')
        self.assertEqual(status, 200)
        self.assertEqual(session['user']['email'], 'admin@example.com')

        status, _ = self.request(self.new_client(), 'POST', '/api/login', {
            'email': 'admin@example.com', 'password': 'secure-passphrase-1',
        })
        self.assertEqual(status, 401)

        status, _ = self.request(self.new_client(), 'POST', '/api/login', {
            'email': 'admin@example.com', 'password': 'brand-new-passphrase-1',
        })
        self.assertEqual(status, 200)

    def test_password_change_requires_authentication(self):
        status, _ = self.request(self.new_client(), 'POST', '/api/account/password', {
            'currentPassword': 'secure-passphrase-1', 'newPassword': 'brand-new-passphrase-1',
        })
        self.assertEqual(status, 401)

    def test_avatar_upload_validation_and_removal(self):
        status, _ = self.request(self.new_client(), 'POST', '/api/account/avatar', {'avatar': self.avatar_data})
        self.assertEqual(status, 401)

        status, _ = self.request(self.admin, 'POST', '/api/account/avatar', {'avatar': 'https://example.com/avatar.png'})
        self.assertEqual(status, 400)

        status, _ = self.request(self.admin, 'POST', '/api/account/avatar', {'avatar': 'data:text/html;base64,PHNjcmlwdD4='})
        self.assertEqual(status, 400)

        status, _ = self.request(self.admin, 'POST', '/api/account/avatar', {'avatar': 'data:image/png;base64,' + 'A' * server.MAX_AVATAR_CHARS})
        self.assertEqual(status, 400)

        status, result = self.request(self.admin, 'POST', '/api/account/avatar', {'avatar': self.avatar_data})
        self.assertEqual(status, 200)
        self.assertEqual(result['avatar'], self.avatar_data)

        status, session = self.request(self.admin, 'GET', '/api/session')
        self.assertEqual(status, 200)
        self.assertEqual(session['user']['avatar'], self.avatar_data)

        status, result = self.request(self.admin, 'POST', '/api/account/avatar', {'avatar': None})
        self.assertEqual(status, 200)
        self.assertIsNone(result['avatar'])

        status, session = self.request(self.admin, 'GET', '/api/session')
        self.assertIsNone(session['user']['avatar'])

    def test_avatar_survives_server_backup_restore(self):
        status, _ = self.request(self.admin, 'POST', '/api/account/avatar', {'avatar': self.avatar_data})
        self.assertEqual(status, 200)

        status, backup = self.request(self.admin, 'POST', '/api/admin/backups', {}, {'X-Backup-Password': BACKUP_PASSWORD})
        self.assertEqual(status, 201)
        filename = backup['filename']

        status, _ = self.request(self.admin, 'POST', '/api/account/avatar', {'avatar': None})
        self.assertEqual(status, 200)

        status, _ = self.request(
            self.admin, 'POST', f'/api/admin/backups/{filename}/restore', {},
            {'X-Backup-Password': BACKUP_PASSWORD},
        )
        self.assertEqual(status, 200)

        restored = self.new_client()
        status, _ = self.request(restored, 'POST', '/api/login', {
            'email': 'admin@example.com', 'password': 'secure-passphrase-1',
        })
        self.assertEqual(status, 200)
        status, session = self.request(restored, 'GET', '/api/session')
        self.assertEqual(status, 200)
        self.assertEqual(session['user']['avatar'], self.avatar_data)

    def test_admin_route_serves_dashboard(self):
        with self.admin.open(self.base_url + '/admin') as response:
            html = response.read().decode('utf-8')
        self.assertIn('Admin panel', html)

    def test_shared_translation_module_is_served(self):
        with self.admin.open(self.base_url + '/i18n.js') as response:
            script = response.read().decode('utf-8')
            self.assertEqual(response.headers.get_content_type(), 'text/javascript')
        self.assertIn('window.i18n', script)
        self.assertIn('window.notkiTranslations', script)

    def test_translation_dictionaries_are_served_from_the_translations_folder(self):
        for language in ('pl', 'en', 'de', 'fr', 'ja', 'ko', 'it', 'es'):
            with self.admin.open(self.base_url + f'/translations/{language}.js') as response:
                script = response.read().decode('utf-8')
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), 'text/javascript')
            self.assertIn(f'window.notkiTranslations.{language} = {{', script)
            self.assertTrue(script.rstrip().endswith('};'), language)
            self.assertEqual(script.count('{'), script.count('}'), language)

    def test_pages_load_the_translation_dictionaries_before_the_i18n_module(self):
        for path in ('/setup.html', '/', '/admin'):
            with self.admin.open(self.base_url + path) as response:
                html = response.read().decode('utf-8')
            for script in ('translations/pl.js', 'translations/en.js', 'translations/de.js', 'translations/fr.js', 'translations/ja.js', 'translations/ko.js', 'translations/it.js', 'translations/es.js', 'i18n.js'):
                self.assertIn(script, html, path)
            self.assertLess(html.index('translations/en.js'), html.index('i18n.js'), path)

    def test_shared_theme_module_is_served_on_every_page(self):
        with self.admin.open(self.base_url + '/theme.js') as response:
            script = response.read().decode('utf-8')
            self.assertEqual(response.headers.get_content_type(), 'text/javascript')
        self.assertIn('window.notkiTheme', script)

        for path in ('/setup.html', '/', '/admin'):
            with self.admin.open(self.base_url + path) as response:
                html = response.read().decode('utf-8')
            self.assertIn('theme.js', html, path)
            self.assertIn('data-theme-select', html, path)

    def test_serve_static_icons(self):
        for filename, expected_mime in [
            ('apple-touch-icon.png', 'image/png'),
            ('icon-192.png', 'image/png'),
            ('icon-512.png', 'image/png'),
            ('icon.svg', 'image/svg+xml'),
            ('manifest.json', 'application/json'),
        ]:
            with self.admin.open(f'{self.base_url}/{filename}') as response:
                self.assertEqual(response.status, 200)
                self.assertIn(expected_mime, response.headers.get_content_type())
                data = response.read()
                self.assertGreater(len(data), 0)

    def test_no_external_fonts_or_cdn(self):
        req_index = Request(f'{self.base_url}/index.html')
        with urlopen(req_index) as response:
            body = response.read().decode('utf-8')
            self.assertNotIn('https://cdnjs.cloudflare.com', body)
            self.assertNotIn('fonts.googleapis.com', body)

        req_setup = Request(f'{self.base_url}/setup.html')
        with urlopen(req_setup) as response:
            body = response.read().decode('utf-8')
            self.assertNotIn('https://cdnjs.cloudflare.com', body)
            self.assertNotIn('fonts.googleapis.com', body)

    def test_security_headers(self):
        req = Request(f'{self.base_url}/')
        with urlopen(req) as response:
            self.assertEqual(response.headers.get('X-Frame-Options'), 'DENY')
            self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')
            self.assertEqual(response.headers.get('Referrer-Policy'), 'strict-origin-when-cross-origin')
            csp = response.headers.get('Content-Security-Policy', '')
            self.assertIn("frame-ancestors 'none'", csp)
            self.assertIn("script-src 'self';", csp)
            self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)
            self.assertIn("object-src 'none'", csp)
            self.assertIn("base-uri 'none'", csp)
            self.assertIsNone(response.headers.get('Strict-Transport-Security'))
            self.assertEqual(response.headers.get('Permissions-Policy'), 'camera=(), microphone=(), geolocation=()')
            self.assertEqual(response.headers.get('Cross-Origin-Opener-Policy'), 'same-origin')
            self.assertEqual(response.headers.get('Cross-Origin-Resource-Policy'), 'same-origin')
            self.assertEqual(response.headers.get('Cache-Control'), 'no-store')
            server_header = response.headers.get('Server', '')
            self.assertNotIn('Python', server_header)

        req_https = Request(f'{self.base_url}/', headers={'X-Forwarded-Proto': 'https'})
        with urlopen(req_https) as response:
            self.assertEqual(response.headers.get('Strict-Transport-Security'), 'max-age=31536000; includeSubDomains')
            self.assertNotIn('0.1.5.94', server_header)

    def test_vendored_dompurify_is_served(self):
        req = Request(f'{self.base_url}/vendor/dompurify.min.js')
        with urlopen(req) as response:
            self.assertEqual(response.status, 200)
            self.assertIn('javascript', response.headers.get('Content-Type'))
            body = response.read().decode('utf-8')
            self.assertIn('DOMPurify', body)

    def test_user_directory_is_not_exposed(self):
        self.register_user('target@example.com')
        for path in ('/api/users', '/api/users?email=target@example.com'):
            status, res = self.request(self.admin, 'GET', path)
            self.assertEqual(status, 404)
            self.assertNotIn('users', res)

    def test_enabling_require2fa_without_admin_2fa_is_rejected(self):
        status, error = self.request(self.admin, 'POST', '/api/admin/settings', {'require2FA': True})
        self.assertEqual(status, 400)
        self.assertIn('two-factor', error['error'].lower())

    def test_admin_without_2fa_is_blocked_when_require2fa_enabled(self):
        # Simulate a legacy instance where require2FA is already on while the admin
        # has no second factor configured.
        with server.database() as connection:
            connection.execute("INSERT INTO settings (key, value) VALUES ('require2FA', 'true') ON CONFLICT(key) DO UPDATE SET value = 'true'")

        status, _ = self.request(self.admin, 'GET', '/api/admin/summary')
        self.assertEqual(status, 403)
        status, _ = self.request(self.admin, 'GET', '/api/notes')
        self.assertEqual(status, 403)

        # The account endpoints needed to configure 2FA stay reachable.
        status, _ = self.request(self.admin, 'POST', '/api/account/totp')
        self.assertEqual(status, 200)

    def test_public_host_takes_precedence_over_forwarded_host(self):
        with unittest.mock.patch.object(server, 'PUBLIC_HOST', 'notes.example.com'):
            status, invite = self.request(
                self.admin, 'POST', '/api/admin/invites', {},
                headers={'Origin': 'https://notes.example.com', 'X-Forwarded-Host': 'evil.attacker.example', 'X-Forwarded-Proto': 'https'},
            )
        self.assertEqual(status, 201)
        self.assertTrue(invite['url'].startswith('https://notes.example.com/?invite='))

    def test_api_errors_follow_accept_language(self):
        status, error = self.request(
            self.new_client(), 'GET', '/api/notes', headers={'Accept-Language': 'en-US,en;q=0.9'},
        )
        self.assertEqual(status, 401)
        self.assertEqual(error['error'], 'Sign in to continue.')

        status, error = self.request(
            self.new_client(), 'GET', '/api/notes', headers={'Accept-Language': 'pl-PL,pl;q=0.9'},
        )
        self.assertEqual(status, 401)
        self.assertEqual(error['error'], 'Zaloguj się, aby kontynuować.')

        status, error = self.request(self.new_client(), 'GET', '/api/notes')
        self.assertEqual(status, 401)
        self.assertEqual(error['error'], 'Sign in to continue.')

        status, error = self.request(
            self.new_client(), 'GET', '/api/notes', headers={'Accept-Language': 'de-DE,fr;q=0.8'},
        )
        self.assertEqual(status, 401)
        self.assertEqual(error['error'], 'Sign in to continue.')

        status, error = self.request(
            self.new_client(), 'GET', '/api/notes', headers={'Accept-Language': 'pl;q=0.2, en;q=0.9'},
        )
        self.assertEqual(status, 401)
        self.assertEqual(error['error'], 'Sign in to continue.')
class FirstRunSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / 'fresh.sqlite3'
        server.initialize_database()
        self.original_setup_token = server.GENERATED_SETUP_TOKEN
        server.GENERATED_SETUP_TOKEN = 'test-setup-token'
        self.http_server = ThreadingHTTPServer(('127.0.0.1', 0), server.NotkiHandler)
        self.thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f'http://127.0.0.1:{self.http_server.server_port}'
        self.client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def tearDown(self):
        self.http_server.shutdown()
        self.http_server.server_close()
        self.thread.join(timeout=2)
        server.DB_PATH = self.original_db_path
        server.GENERATED_SETUP_TOKEN = self.original_setup_token
        self.temp_dir.cleanup()

    def request(self, method, path, payload=None, headers=None):
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            headers=with_same_origin(self.base_url, {'Content-Type': 'application/json', **(headers or {})}),
            method=method,
        )
        try:
            with self.client.open(request) as response:
                return response.status, json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            status = error.code
            payload = json.loads(error.read().decode('utf-8'))
            error.close()
            return status, payload

    def request_raw(self, method, path, body, content_type='application/gzip', headers=None):
        request = Request(
            self.base_url + path,
            data=body,
            headers=with_same_origin(self.base_url, {'Content-Type': content_type, **(headers or {})}),
            method=method,
        )
        try:
            with self.client.open(request) as response:
                return response.status, json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            status = error.code
            payload = json.loads(error.read().decode('utf-8'))
            error.close()
            return status, payload

    def test_first_admin_setup_is_local_and_one_time(self):
        with self.client.open(self.base_url + '/') as response:
            self.assertTrue(response.geturl().endswith('/setup'))
            self.assertIn('Create administrator', response.read().decode('utf-8'))
        status, result = self.request('GET', '/api/setup/status')
        self.assertEqual(status, 200)
        self.assertTrue(result['needsSetup'])

        status, result = self.request('POST', '/api/setup/admin', {
            'email': 'admin@example.com', 'password': 'short',
        })
        self.assertEqual(status, 400)
        self.assertEqual(result['error'], 'The password must be at least 12 characters long.')

        status, result = self.request('POST', '/api/setup/admin', {
            'email': 'admin@example.com', 'password': 'short',
        }, {'Accept-Language': 'pl-PL'})
        self.assertEqual(status, 400)
        self.assertEqual(result['error'], 'Hasło musi mieć co najmniej 12 znaków.')

        status, result = self.request('POST', '/api/setup/admin', {
            'email': 'admin@example.com', 'password': 'secure-first-admin-password',
        })
        self.assertEqual(status, 201, result)
        self.assertTrue(result['user']['isAdmin'])
        status, result = self.request('GET', '/api/setup/status')
        self.assertFalse(result['needsSetup'])
        status, result = self.request('POST', '/api/setup/admin', {
            'email': 'second-admin@example.com', 'password': 'secure-second-admin-password',
        })
        self.assertEqual(status, 409)

    def test_setup_requires_token_and_ignores_forwarded_headers(self):
        payload = {'email': 'proxy-admin@example.com', 'password': 'proxy-admin-password'}
        for headers, label in (
            ({'Host': 'localhost', 'X-Forwarded-For': '203.0.113.5'}, 'X-Forwarded-For'),
            ({'Host': 'localhost', 'X-Real-IP': '203.0.113.6'}, 'X-Real-IP'),
            ({'Host': 'localhost', 'X-Forwarded-Host': 'notki.example.com'}, 'X-Forwarded-Host'),
            ({'Host': 'localhost', 'Forwarded': 'for=203.0.113.7;proto=http'}, 'Forwarded for'),
            ({'Host': 'localhost', 'Forwarded': 'host=notki.example.com;proto=http'}, 'Forwarded host'),
        ):
            with self.subTest(header=label):
                status, _ = self.request(
                    'POST', '/api/setup/admin', payload,
                    dict(headers, **{'X-Setup-Token': ''}),
                )
                self.assertEqual(status, 403)

        status, _ = self.request(
            'POST', '/api/setup/admin', payload,
            {'Host': 'localhost', 'X-Setup-Token': 'wrong-token'},
        )
        self.assertEqual(status, 403)

        status, result = self.request(
            'POST', '/api/setup/admin', payload,
            {'Host': 'localhost', 'Origin': 'http://localhost', 'X-Setup-Token': 'test-setup-token'},
        )
        self.assertEqual(status, 201)
        self.assertTrue(result['user']['isAdmin'])

    def test_encrypted_backup_import_restores_accounts_notes_and_invites(self):
        created_at = server.iso_time()
        invite_token = 'invitation-token-from-snapshot'
        snapshot = {
            'format': 'notki-server-snapshot',
            'version': 2,
            'createdAt': created_at,
            'users': [{
                'id': 7, 'email': 'restored-admin@example.com',
                'passwordHash': server.hash_password('restored-admin-password'),
                'role': 'admin', 'createdAt': created_at,
            }],
            'notes': [{
                'id': 'restored-note', 'userId': 7, 'title': 'Przywrócona notatka',
                'body': 'Cały serwer', 'bodyFormat': 0, 'color': 'sky', 'tags': ['backup'],
                'pinned': True, 'archived': False, 'deleted': False,
                'createdAt': created_at, 'updatedAt': created_at, 'order': 1,
            }],
            'invites': [{
                'tokenHash': server.token_hash(invite_token), 'createdBy': 7,
                'createdAt': created_at, 'expiresAt': server.iso_time(server.utc_now() + server.timedelta(days=3)),
                'usedAt': None,
            }],
        }
        backup_bytes = server.encrypt_backup(snapshot, BACKUP_PASSWORD)

        # The setup token is required even for the encrypted import endpoint.
        status, _ = self.request_raw(
            'POST', '/api/setup/import-backup', backup_bytes,
            content_type='application/octet-stream',
            headers={'Host': 'external.example', 'X-Setup-Token': ''},
        )
        self.assertEqual(status, 403)

        status, result = self.request_raw(
            'POST', '/api/setup/import-backup', backup_bytes,
            content_type='application/octet-stream',
            headers={'X-Backup-Password': BACKUP_PASSWORD},
        )
        self.assertEqual(status, 201)
        self.assertEqual(result, {'imported': True, 'users': 1, 'notes': 1, 'invites': 1, 'shares': 0})

        status, login = self.request('POST', '/api/login', {
            'email': 'restored-admin@example.com', 'password': 'restored-admin-password',
        })
        self.assertEqual(status, 200)
        self.assertTrue(login['user']['isAdmin'])
        status, result = self.request('GET', '/api/notes')
        self.assertEqual(status, 200)
        self.assertEqual(result['notes'][0]['title'], 'Przywrócona notatka')
        status, result = self.request('POST', '/api/register', {
            'email': 'restored-user@example.com', 'password': 'restored-user-password', 'invite': invite_token,
        })
        self.assertEqual(status, 201)

        # A second import into a non-empty database is rejected.
        status, _ = self.request_raw(
            'POST', '/api/setup/import-backup', backup_bytes,
            content_type='application/octet-stream',
            headers={'X-Backup-Password': BACKUP_PASSWORD},
        )
        self.assertEqual(status, 409)

    def test_invalid_backup_archive_returns_bad_request(self):
        status, error = self.request_raw('POST', '/api/setup/import-backup', b'not a valid snapshot json')
        self.assertEqual(status, 400)
        self.assertIn('error', error)



class ParseVersionTests(unittest.TestCase):
    def test_standard_version(self):
        self.assertEqual(server.parse_version('1.2.3'), (1, 2, 3))

    def test_prefix_version(self):
        self.assertEqual(server.parse_version('v1.2.3'), (1, 2, 3))

    def test_stripped_input(self):
        self.assertEqual(server.parse_version('  v2.0.1  '), (2, 0, 1))

    def test_incomplete_version(self):
        self.assertEqual(server.parse_version('1.2'), (1, 2))

    def test_malformed_string(self):
        self.assertEqual(server.parse_version('invalid'), (0, 0, 0))

    def test_empty_string(self):
        self.assertEqual(server.parse_version(''), (0, 0, 0))

    def test_none_input(self):
        with self.assertRaises(AttributeError):
            server.parse_version(None)


class ParseLanguageTests(unittest.TestCase):
    def test_split_by_comma_and_strip(self):
        self.assertEqual(server.parse_language('pl , es'), 'pl')
        self.assertEqual(server.parse_language('pl,es'), 'pl')
        self.assertEqual(server.parse_language('  pl  ,  es  '), 'pl')

    def test_skips_empty_parts(self):
        self.assertEqual(server.parse_language('pl,,es'), 'pl')
        self.assertEqual(server.parse_language(', pl ,'), 'pl')
        self.assertEqual(server.parse_language('  ,  pl  ,  '), 'pl')

    def test_empty_or_none(self):
        self.assertEqual(server.parse_language(None), server.DEFAULT_LANGUAGE)
        self.assertEqual(server.parse_language(''), server.DEFAULT_LANGUAGE)
        self.assertEqual(server.parse_language('   '), server.DEFAULT_LANGUAGE)

    def test_single_supported_language(self):
        self.assertEqual(server.parse_language('pl'), 'pl')
        self.assertEqual(server.parse_language('es'), 'es')

    def test_strips_region_from_language(self):
        self.assertEqual(server.parse_language('en-US'), 'en')
        self.assertEqual(server.parse_language('fr-CA'), 'fr')

    def test_unsupported_language_returns_default(self):
        self.assertEqual(server.parse_language('xx'), server.DEFAULT_LANGUAGE)
        self.assertEqual(server.parse_language('xx-YY'), server.DEFAULT_LANGUAGE)

    def test_respects_quality_values(self):
        self.assertEqual(server.parse_language('en-US;q=0.5,en;q=0.8,pl;q=0.9'), 'pl')
        self.assertEqual(server.parse_language('fr;q=0.7, de;q=0.8, es;q=0.9'), 'es')

    def test_respects_quality_values_more(self):
        self.assertEqual(server.parse_language('es;q=0.8, pl;q=0.9, en;q=0.1'), 'pl')
        self.assertEqual(server.parse_language('de;q=0.9, fr;q=0.8, it;q=0.7'), 'de')
        self.assertEqual(server.parse_language('ja;q=0.5, ko;q=0.6, pl;q=0.4'), 'ko')
        self.assertEqual(server.parse_language('pl;q=0.9, en-US;q=1.0'), 'en')

    def test_skips_asterisk_and_unsupported(self):
        self.assertEqual(server.parse_language('*'), server.DEFAULT_LANGUAGE)
        self.assertEqual(server.parse_language('xx, *;q=0.9'), server.DEFAULT_LANGUAGE)
        self.assertEqual(server.parse_language('*, pl'), 'pl')

    def test_handles_malformed_quality(self):
        # Malformed q is treated as 0.0 and skipped
        self.assertEqual(server.parse_language('pl;q=invalid, en'), 'en')

    def test_handles_zero_quality(self):
        self.assertEqual(server.parse_language('pl;q=0.0, en'), 'en')
        self.assertEqual(server.parse_language('pl;q=-0.1, en'), 'en')

    def test_ignores_extra_parameters(self):
        self.assertEqual(server.parse_language('es;foo=bar;q=0.9, en;q=0.8'), 'es')
        self.assertEqual(server.parse_language('ja; q=0.9 ; foo=bar, en;q=0.8'), 'ja')

    def test_whitespace_handling(self):
        self.assertEqual(server.parse_language('  fr  ;  q=0.9  ,  de ; q=0.8 '), 'fr')



class VerifyTOTPCodeTests(unittest.TestCase):
    def setUp(self):
        self.secret = server.generate_totp_secret()
        self.time_step = 30
        self.base_time = 1600000000.0  # arbitrary timestamp
        self.base_counter = int(self.base_time // self.time_step)

    @unittest.mock.patch('time.time')
    def test_valid_code_exact_match(self, mock_time):
        mock_time.return_value = self.base_time
        code = server.compute_totp_code(self.secret, self.time_step, self.base_counter)
        self.assertTrue(server.verify_totp_code(self.secret, code, self.time_step))

    @unittest.mock.patch('time.time')
    def test_valid_code_previous_window(self, mock_time):
        mock_time.return_value = self.base_time
        code = server.compute_totp_code(self.secret, self.time_step, self.base_counter - 1)
        self.assertTrue(server.verify_totp_code(self.secret, code, self.time_step, window=1))

    @unittest.mock.patch('time.time')
    def test_valid_code_next_window(self, mock_time):
        mock_time.return_value = self.base_time
        code = server.compute_totp_code(self.secret, self.time_step, self.base_counter + 1)
        self.assertTrue(server.verify_totp_code(self.secret, code, self.time_step, window=1))

    @unittest.mock.patch('time.time')
    def test_invalid_code_outside_window(self, mock_time):
        mock_time.return_value = self.base_time
        code = server.compute_totp_code(self.secret, self.time_step, self.base_counter - 2)
        self.assertFalse(server.verify_totp_code(self.secret, code, self.time_step, window=1))

        code = server.compute_totp_code(self.secret, self.time_step, self.base_counter + 2)
        self.assertFalse(server.verify_totp_code(self.secret, code, self.time_step, window=1))

    def test_invalid_code_formats(self):
        self.assertFalse(server.verify_totp_code(self.secret, None))
        self.assertFalse(server.verify_totp_code(self.secret, ""))
        self.assertFalse(server.verify_totp_code(self.secret, "   "))
        self.assertFalse(server.verify_totp_code(self.secret, "12345"))  # length 5
        self.assertFalse(server.verify_totp_code(self.secret, "1234567"))  # length 7
        self.assertFalse(server.verify_totp_code(self.secret, "123a56"))   # non-digit
        self.assertFalse(server.verify_totp_code(self.secret, 12345))      # int with wrong digits length

    @unittest.mock.patch('time.time')
    def test_invalid_secret_exception_handling(self, mock_time):
        mock_time.return_value = self.base_time
        # Secret with invalid base32 chars will throw inside compute_totp_code -> base64.b32decode
        # Verify that it's caught and handled gracefully (returning False)
        invalid_secret = "12345678"  # Base32 shouldn't have '1' or '8' unless padded
        code = "123456"
        self.assertFalse(server.verify_totp_code(invalid_secret, code, self.time_step, window=1))

    @unittest.mock.patch('time.time')
    def test_hmac_exception_handling(self, mock_time):
        # Force current_counter to be negative so that struct.pack('>Q', counter) throws struct.error
        # This will trigger the exception block inside the inner loop of verify_totp_counter.
        mock_time.return_value = -31.0
        code = "123456"
        self.assertFalse(server.verify_totp_code(self.secret, code, self.time_step, window=1))


class ParseMultipartDataTests(unittest.TestCase):
    def test_happy_path(self):
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        body = (
            b"------WebKitFormBoundary7MA4YWxkTrZu0gW\r\n"
            b"Content-Disposition: form-data; name=\"username\"\r\n"
            b"\r\n"
            b"testuser\r\n"
            b"------WebKitFormBoundary7MA4YWxkTrZu0gW\r\n"
            b"Content-Disposition: form-data; name=\"password\"\r\n"
            b"\r\n"
            b"testpass\r\n"
            b"------WebKitFormBoundary7MA4YWxkTrZu0gW--\r\n"
        )
        rfile = io.BytesIO(body)
        fields = server.parse_multipart_data(rfile, boundary, len(body))
        self.assertEqual(fields, {
            'username': [b'testuser'],
            'password': [b'testpass']
        })

    def test_boundary_types(self):
        body = (
            b"--boundary\r\n"
            b"Content-Disposition: form-data; name=\"key\"\r\n"
            b"\r\n"
            b"value\r\n"
            b"--boundary--\r\n"
        )
        # Test string boundary
        rfile = io.BytesIO(body)
        fields1 = server.parse_multipart_data(rfile, "boundary", len(body))
        self.assertEqual(fields1, {'key': [b'value']})

        # Test bytes boundary
        rfile = io.BytesIO(body)
        fields2 = server.parse_multipart_data(rfile, b"boundary", len(body))
        self.assertEqual(fields2, {'key': [b'value']})

    def test_array_fields(self):
        body = (
            b"--boundary\r\n"
            b"Content-Disposition: form-data; name=\"tags\"\r\n"
            b"\r\n"
            b"tag1\r\n"
            b"--boundary\r\n"
            b"Content-Disposition: form-data; name=\"tags\"\r\n"
            b"\r\n"
            b"tag2\r\n"
            b"--boundary--\r\n"
        )
        rfile = io.BytesIO(body)
        fields = server.parse_multipart_data(rfile, "boundary", len(body))
        self.assertEqual(fields, {'tags': [b'tag1', b'tag2']})

    def test_binary_data(self):
        binary_payload = b'\x00\x01\x02\r\n\x03\x04'
        body = (
            b"--boundary\r\n"
            b"Content-Disposition: form-data; name=\"file\"; filename=\"test.bin\"\r\n"
            b"Content-Type: application/octet-stream\r\n"
            b"\r\n" +
            binary_payload + b"\r\n"
            b"--boundary--\r\n"
        )
        rfile = io.BytesIO(body)
        fields = server.parse_multipart_data(rfile, "boundary", len(body))
        self.assertEqual(fields, {'file': [binary_payload]})

    def test_malformed_inputs(self):
        # Missing \r\n\r\n
        body1 = (
            b"--boundary\r\n"
            b"Content-Disposition: form-data; name=\"key\"\r\n"
            b"value\r\n"
            b"--boundary--\r\n"
        )
        rfile1 = io.BytesIO(body1)
        fields1 = server.parse_multipart_data(rfile1, "boundary", len(body1))
        self.assertEqual(fields1, {})

        # Missing Content-Disposition
        body2 = (
            b"--boundary\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"value\r\n"
            b"--boundary--\r\n"
        )
        rfile2 = io.BytesIO(body2)
        fields2 = server.parse_multipart_data(rfile2, "boundary", len(body2))
        self.assertEqual(fields2, {})

    def test_read_archive_from_request_oversized_multipart(self):
        class DummyHandler(server.NotkiHandler):
            def __init__(self, headers, rfile):
                self.headers = headers
                self.rfile = rfile

        headers = {
            'Content-Type': 'multipart/form-data; boundary=boundary',
            'Content-Length': str(server.MAX_BACKUP_FILE_BYTES + 1)
        }
        rfile = io.BytesIO(b'')
        handler = DummyHandler(headers, rfile)
        with self.assertRaises(server.APIError) as cm:
            handler.read_archive_from_request()
        self.assertEqual(cm.exception.status, 413)
        self.assertEqual(str(cm.exception), 'The backup file exceeds the size limit.')



class GetForwardedProtoTests(unittest.TestCase):
    def setUp(self):
        class DummyHandler(server.NotkiHandler):
            def __init__(self):
                pass
        self.handler = DummyHandler()
        self.handler.client_address = ('127.0.0.1', 12345)
        self.handler.headers = {}

    def test_x_forwarded_proto_single(self):
        self.handler.headers = {'X-Forwarded-Proto': 'https'}
        self.assertEqual(self.handler.get_forwarded_proto(), 'https')

    def test_x_forwarded_proto_multiple(self):
        self.handler.headers = {'X-Forwarded-Proto': 'https, http'}
        self.assertEqual(self.handler.get_forwarded_proto(), 'https')

        self.handler.headers = {'X-Forwarded-Proto': 'http, https'}
        self.assertEqual(self.handler.get_forwarded_proto(), 'http')

    def test_x_forwarded_proto_invalid(self):
        self.handler.headers = {'X-Forwarded-Proto': 'invalid', 'Host': 'example.com'}
        self.assertEqual(self.handler.get_forwarded_proto(), 'http')

        self.handler.headers = {'X-Forwarded-Proto': 'invalid'}
        self.assertEqual(self.handler.get_forwarded_proto(), '')

    def test_x_forwarded_scheme(self):
        self.handler.headers = {'X-Forwarded-Scheme': 'https'}
        self.assertEqual(self.handler.get_forwarded_proto(), 'https')

    def test_x_url_scheme(self):
        self.handler.headers = {'X-Url-Scheme': 'https'}
        self.assertEqual(self.handler.get_forwarded_proto(), 'https')

    def test_front_end_https(self):
        for val in ('on', '1', 'true', 'ON', 'True'):
            with self.subTest(val=val):
                self.handler.headers = {'Front-End-Https': val}
                self.assertEqual(self.handler.get_forwarded_proto(), 'https')

    def test_front_end_https_off(self):
        self.handler.headers = {'Front-End-Https': 'off', 'Host': 'example.com'}
        self.assertEqual(self.handler.get_forwarded_proto(), 'http')

    def test_x_forwarded_ssl(self):
        self.handler.headers = {'X-Forwarded-Ssl': 'on'}
        self.assertEqual(self.handler.get_forwarded_proto(), 'https')

    def test_no_headers_with_host(self):
        self.handler.headers = {'Host': 'example.com'}
        self.assertEqual(self.handler.get_forwarded_proto(), 'http')

    def test_no_headers_no_host(self):
        self.handler.headers = {}
        self.assertEqual(self.handler.get_forwarded_proto(), '')




class TranslateMessageTests(unittest.TestCase):
    def test_translate_message_polish(self):
        # Known message in POLISH_MESSAGES
        self.assertEqual(server.translate_message('Enter a valid e-mail address.', 'pl'), 'Podaj poprawny adres e-mail.')

        # Unknown message, should return the original
        self.assertEqual(server.translate_message('Some unknown message', 'pl'), 'Some unknown message')

    def test_translate_message_other_languages(self):
        # Even if the message exists in POLISH_MESSAGES, shouldn't translate to Polish if language is not 'pl'
        self.assertEqual(server.translate_message('Enter a valid e-mail address.', 'en'), 'Enter a valid e-mail address.')
        self.assertEqual(server.translate_message('Enter a valid e-mail address.', 'de'), 'Enter a valid e-mail address.')
        self.assertEqual(server.translate_message('Enter a valid e-mail address.', 'es'), 'Enter a valid e-mail address.')

    def test_translate_message_none_language(self):
        self.assertEqual(server.translate_message('Enter a valid e-mail address.', None), 'Enter a valid e-mail address.')

    def test_translate_message_invalid_message(self):
        self.assertEqual(server.translate_message(None, 'pl'), None)
        self.assertEqual(server.translate_message('', 'pl'), '')


class RecordFailedAuthTests(unittest.TestCase):
    def setUp(self):
        server.FAILED_AUTH_ATTEMPTS.clear()
        server.FAILED_AUTH_ACCOUNTS.clear()
        server.ACCOUNT_FAILURES.clear()

    def tearDown(self):
        server.FAILED_AUTH_ATTEMPTS.clear()
        server.FAILED_AUTH_ACCOUNTS.clear()
        server.ACCOUNT_FAILURES.clear()

    @unittest.mock.patch('server.time.time')
    def test_record_failed_auth_new_ip(self, mock_time):
        mock_time.return_value = 1000.0
        server.record_failed_auth('192.168.1.1', 'victim@example.com')

        self.assertEqual(server.FAILED_AUTH_ATTEMPTS['192.168.1.1'], [1000.0])
        self.assertEqual(server.FAILED_AUTH_ACCOUNTS[('192.168.1.1', 'victim@example.com')], [1000.0])
        self.assertEqual(server.ACCOUNT_FAILURES['victim@example.com'], [1000.0])

    @unittest.mock.patch('server.time.time')
    def test_record_failed_auth_existing_ip(self, mock_time):
        mock_time.return_value = 1000.0
        server.record_failed_auth('192.168.1.2', 'victim@example.com')

        mock_time.return_value = 1010.0
        server.record_failed_auth('192.168.1.2', 'victim@example.com')

        self.assertEqual(server.FAILED_AUTH_ATTEMPTS['192.168.1.2'], [1000.0, 1010.0])
        self.assertEqual(server.ACCOUNT_FAILURES['victim@example.com'], [1000.0, 1010.0])

    @unittest.mock.patch('server.time.time')
    def test_record_failed_auth_removes_old_attempts(self, mock_time):
        server.FAILED_AUTH_ATTEMPTS['192.168.1.3'] = [900.0]

        # Entries older than one hour are dropped (1000 - 900 = 1000 ... still kept,
        # so use a timestamp beyond the 3600 second retention window).
        mock_time.return_value = 1000.0
        server.record_failed_auth('192.168.1.3')
        self.assertEqual(server.FAILED_AUTH_ATTEMPTS['192.168.1.3'], [900.0, 1000.0])

        mock_time.return_value = 5000.0
        server.record_failed_auth('192.168.1.3')
        self.assertEqual(server.FAILED_AUTH_ATTEMPTS['192.168.1.3'], [5000.0])

    @unittest.mock.patch('server.time.time')
    def test_record_failed_auth_bounds_per_key_growth(self, mock_time):
        mock_time.return_value = 1000.0
        for _ in range(server.MAX_ATTEMPTS_PER_KEY + 25):
            server.record_failed_auth('192.168.1.4', 'victim@example.com')
        self.assertEqual(len(server.FAILED_AUTH_ATTEMPTS['192.168.1.4']), server.MAX_ATTEMPTS_PER_KEY)
        self.assertEqual(len(server.ACCOUNT_FAILURES['victim@example.com']), server.MAX_ATTEMPTS_PER_KEY)

    @unittest.mock.patch('server.database')
    @unittest.mock.patch('server._prune_fail2ban_database')
    @unittest.mock.patch('server.time.time')
    def test_record_failed_auth_database_insertion(self, mock_time, mock_prune, mock_database):
        mock_time.return_value = 1000.0
        server.UNFLUSHED_FAIL2BAN_ATTEMPTS.clear()

        server.record_failed_auth('192.168.1.5', 'user@example.com')

        self.assertEqual(server.UNFLUSHED_FAIL2BAN_ATTEMPTS, [('192.168.1.5', 'user@example.com', 1000.0)])
        mock_prune.assert_called_once_with(1000.0)

    @unittest.mock.patch('server.database')
    @unittest.mock.patch('server._prune_fail2ban_database')
    @unittest.mock.patch('server.time.time')
    def test_record_failed_auth_database_exception_suppressed(self, mock_time, mock_prune, mock_database):
        mock_time.return_value = 1000.0
        mock_database.side_effect = Exception('Database error')

        # Should not raise an exception
        server.record_failed_auth('192.168.1.6', 'user2@example.com')

        mock_prune.assert_called_once_with(1000.0)

    @unittest.mock.patch('server._prune_fail2ban_database')
    @unittest.mock.patch('server._flush_fail2ban_buffer')
    @unittest.mock.patch('server.time.time')
    def test_record_failed_auth_flushes_buffer(self, mock_time, mock_flush, mock_prune):
        mock_time.return_value = 1000.0
        server.UNFLUSHED_FAIL2BAN_ATTEMPTS.clear()

        # Pre-fill buffer just below the limit
        for i in range(server.MAX_AUTH_TRACKED_IPS - 1):
            server.UNFLUSHED_FAIL2BAN_ATTEMPTS.append((f'10.0.0.{i}', None, 900.0))

        mock_flush.assert_not_called()

        # This insertion should trigger the flush
        server.record_failed_auth('192.168.1.7', 'user3@example.com')

        mock_flush.assert_called_once()
        mock_prune.assert_called_once_with(1000.0)


class IsRateLimitedTests(unittest.TestCase):
    def setUp(self):
        server.FAILED_AUTH_ATTEMPTS.clear()

    def tearDown(self):
        server.FAILED_AUTH_ATTEMPTS.clear()
        server.FAILED_AUTH_ACCOUNTS.clear()
        server.ACCOUNT_FAILURES.clear()
        server.UNFLUSHED_FAIL2BAN_ATTEMPTS.clear()

    def test_is_rate_limited_empty_ip(self):
        self.assertFalse(server.is_rate_limited('192.168.1.100'))

    @unittest.mock.patch('server.time.time')
    def test_is_rate_limited_under_threshold(self, mock_time):
        mock_time.return_value = 1000.0
        server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0] * 14
        self.assertFalse(server.is_rate_limited('192.168.1.100'))

    @unittest.mock.patch('server.time.time')
    def test_is_rate_limited_at_threshold(self, mock_time):
        mock_time.return_value = 1000.0
        server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0] * 15
        self.assertTrue(server.is_rate_limited('192.168.1.100'))

    @unittest.mock.patch('server.time.time')
    def test_is_rate_limited_above_threshold(self, mock_time):
        mock_time.return_value = 1000.0
        server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0] * 16
        self.assertTrue(server.is_rate_limited('192.168.1.100'))

    @unittest.mock.patch('server.time.time')
    def test_is_rate_limited_window_expiration(self, mock_time):
        # 15 attempts recorded at t=1000.0
        server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0] * 15

        # At t=1059.0 (59 seconds later, within 60s window), still rate limited
        mock_time.return_value = 1059.0
        self.assertTrue(server.is_rate_limited('192.168.1.100'))

        # At exactly the cutoff t=1060.0 (t > cutoff becomes 1000.0 > 1000.0 which is False), attempts expire
        mock_time.return_value = 1060.0
        self.assertFalse(server.is_rate_limited('192.168.1.100'))
        self.assertEqual(server.FAILED_AUTH_ATTEMPTS['192.168.1.100'], [])

    @unittest.mock.patch('server.time.time')
    def test_is_rate_limited_custom_params(self, mock_time):
        mock_time.return_value = 1000.0
        server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [995.0, 998.0, 1000.0]

        # With default max_failed=15, 3 attempts is False
        self.assertFalse(server.is_rate_limited('192.168.1.100'))

        # With custom max_failed=3, 3 attempts is True
        self.assertTrue(server.is_rate_limited('192.168.1.100', max_failed=3))

        # With custom window_seconds=3 (attempts at 995.0 are now 1000.0 - 995.0 = 5 >= 3),
        # only 998.0 and 1000.0 remain (2 attempts)
        self.assertFalse(server.is_rate_limited('192.168.1.100', max_failed=3, window_seconds=3))

    @unittest.mock.patch('server.time.time')
    def test_is_rate_limited_ip_isolation(self, mock_time):
        mock_time.return_value = 1000.0
        server.FAILED_AUTH_ATTEMPTS['192.168.1.1'] = [1000.0] * 15
        server.FAILED_AUTH_ATTEMPTS['192.168.1.2'] = [1000.0] * 5

        self.assertTrue(server.is_rate_limited('192.168.1.1'))
        self.assertFalse(server.is_rate_limited('192.168.1.2'))

    @unittest.mock.patch('server.get_fail2ban_config')
    def test_is_rate_limited_disabled(self, mock_config):
        mock_config.return_value = {'enabled': False, 'max_attempts': 15, 'ban_time': 60}
        self.assertFalse(server.is_rate_limited('192.168.1.100'))

    @unittest.mock.patch('server.time.time')
    @unittest.mock.patch('server.get_fail2ban_config')
    def test_is_rate_limited_disabled_with_custom_params(self, mock_config, mock_time):
        mock_time.return_value = 1000.0
        mock_config.return_value = {'enabled': False, 'max_attempts': 15, 'ban_time': 60}
        server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0] * 10
        self.assertTrue(server.is_rate_limited('192.168.1.100', max_failed=10, window_seconds=30))
        self.assertFalse(server.is_rate_limited('192.168.1.100', max_failed=11, window_seconds=30))

    @unittest.mock.patch('server.time.time')
    @unittest.mock.patch('server.get_fail2ban_config')
    def test_is_rate_limited_disabled_with_none_params(self, mock_config, mock_time):
        mock_time.return_value = 1000.0
        mock_config.return_value = {'enabled': False, 'max_attempts': 15, 'ban_time': 60}
        server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0] * 15
        self.assertFalse(server.is_rate_limited('192.168.1.100', max_failed=None, window_seconds=None))

    @unittest.mock.patch('server.database')
    def test_is_rate_limited_database_lookup(self, mock_db):
        mock_conn = unittest.mock.MagicMock()
        mock_db.return_value.__enter__.return_value = mock_conn
        mock_cursor = unittest.mock.MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = [15]

        self.assertTrue(server.is_rate_limited('192.168.1.100'))

    @unittest.mock.patch('server.database')
    def test_is_rate_limited_database_lookup_under_threshold(self, mock_db):
        mock_conn = unittest.mock.MagicMock()
        mock_db.return_value.__enter__.return_value = mock_conn
        mock_cursor = unittest.mock.MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = [14]

        self.assertFalse(server.is_rate_limited('192.168.1.100'))

    @unittest.mock.patch('server.database')
    def test_is_rate_limited_database_exception(self, mock_db):
        mock_conn = unittest.mock.MagicMock()
        mock_db.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = Exception("Database error")

        self.assertFalse(server.is_rate_limited('192.168.1.100'))

    def test_unban_ip_empty(self):
        self.assertFalse(server.unban_ip(None))
        self.assertFalse(server.unban_ip('   '))

    def test_unban_ip_clears_failed_auth_accounts(self):
        server.FAILED_AUTH_ACCOUNTS[('192.168.1.100', 'test@example.com')] = [1000.0]
        server.unban_ip('192.168.1.100')
        self.assertNotIn(('192.168.1.100', 'test@example.com'), server.FAILED_AUTH_ACCOUNTS)

    @unittest.mock.patch('server.database')
    def test_unban_ip_database_exception(self, mock_db):
        mock_conn = unittest.mock.MagicMock()
        mock_db.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = Exception("Database error")
        # Should not raise exception
        self.assertFalse(server.unban_ip('192.168.1.100'))


class AddLogTests(unittest.TestCase):
    def setUp(self):
        server.LOG_BUFFER.clear()

    def tearDown(self):
        server.LOG_BUFFER.clear()

    @unittest.mock.patch('server.datetime')
    def test_add_log_appends_entry(self, mock_datetime):
        mock_now = mock_datetime.now.return_value
        mock_now.strftime.return_value = '2023-10-25 12:00:00'

        server.add_log('INFO', 'Test message')

        self.assertEqual(len(server.LOG_BUFFER), 1)
        entry = server.LOG_BUFFER[0]
        self.assertEqual(entry['level'], 'INFO')
        self.assertEqual(entry['message'], 'Test message')
        self.assertEqual(entry['time'], '2023-10-25 12:00:00')

    def test_add_log_caps_entries(self):
        old_max = server.MAX_LOG_ENTRIES
        server.MAX_LOG_ENTRIES = 3
        try:
            for i in range(5):
                server.add_log('INFO', f'Message {i}')

            self.assertEqual(len(server.LOG_BUFFER), 3)
            self.assertEqual(server.LOG_BUFFER[0]['message'], 'Message 2')
            self.assertEqual(server.LOG_BUFFER[1]['message'], 'Message 3')
            self.assertEqual(server.LOG_BUFFER[2]['message'], 'Message 4')
        finally:
            server.MAX_LOG_ENTRIES = old_max


class TestParseVersion(unittest.TestCase):
    def test_parse_version(self):
        cases = [
            ("basic semantic version", "1.0.0", (1, 0, 0)),
            ("with v prefix", "v1.2.3", (1, 2, 3)),
            ("missing patch version", "v1.0", (1, 0)),
            ("major version only", "v1", (1,)),
            ("with pre-release suffix", "v1.0.0-beta", (1, 0, 0)),
            ("leading and trailing whitespace", "  v2.0.1  ", (2, 0, 1)),
            ("multiple digits", "10.20.300", (10, 20, 300)),
            ("invalid format", "invalid", (0, 0, 0)),
            ("empty string", "", (0, 0, 0)),
        ]
        for name, input_str, expected in cases:
            with self.subTest(name=name):
                result = server.parse_version(input_str)
                self.assertEqual(result, expected)


class TestParseForwardedElements(unittest.TestCase):
    def test_parse_forwarded_elements(self):
        cases = [
            ("empty string", "", []),
            ("none", None, []),
            ("single key-value", "for=192.0.2.60", [{"for": "192.0.2.60"}]),
            ("multiple key-value", "for=192.0.2.60;proto=http;by=203.0.113.43", [{"for": "192.0.2.60", "proto": "http", "by": "203.0.113.43"}]),
            ("multiple elements", "for=192.0.2.60, for=198.51.100.17", [{"for": "192.0.2.60"}, {"for": "198.51.100.17"}]),
            ("mixed elements and attributes", "for=192.0.2.60;proto=http, for=198.51.100.17", [{"for": "192.0.2.60", "proto": "http"}, {"for": "198.51.100.17"}]),
            ("quoted values", 'for="192.0.2.60"', [{"for": "192.0.2.60"}]),
            ("whitespace trimming", "  for  =  192.0.2.60  ", [{"for": "192.0.2.60"}]),
            ("case-insensitive keys", "For=192.0.2.60; PROTO=https", [{"for": "192.0.2.60", "proto": "https"}]),
            ("malformed pair without equals", "for=192.0.2.60;proto", [{"for": "192.0.2.60"}]),
            ("only malformed pair", "proto", []),
            ("empty element", ",for=192.0.2.60", [{"for": "192.0.2.60"}]),
        ]

        for name, input_val, expected in cases:
            with self.subTest(msg=name):
                self.assertEqual(server.parse_forwarded_elements(input_val), expected)


class TestParseForwardedHost(unittest.TestCase):
    def test_parse_forwarded_host(self):
        cases = [
            ("empty string", "", None),
            ("none", None, None),
            ("no host", "for=192.0.2.60;proto=http", None),
            ("empty host", "host=", None),
            ("empty quoted host", 'host=""', None),
            ("single host", "host=example.com", "example.com"),
            ("capitalized key", "Host=example.com", "example.com"),
            ("quoted host", 'host="example.com"', "example.com"),
            ("host with spaces", " host = example.com ", "example.com"),
            ("multiple params", "for=192.0.2.60;host=example.com;proto=http", "example.com"),
            ("multiple hosts (returns first)", "host=example.com, host=test.com", "example.com"),
            ("second element has host", "for=192.0.2.60, host=example.com", "example.com"),
            ("multiple hosts (ignores invalid first)", "host=, host=example.com", "example.com"),
        ]

        for name, input_val, expected in cases:
            with self.subTest(msg=name):
                self.assertEqual(server.parse_forwarded_host(input_val), expected)


class TestParseForwardedFor(unittest.TestCase):
    def test_parse_forwarded_for(self):
        cases = [
            ("empty", "", []),
            ("none", None, []),
            ("no for", "proto=http;by=203.0.113.43", []),
            ("empty for", "for=", []),
            ("empty quoted for", 'for=""', []),
            ("single ipv4", "for=192.0.2.60", ["192.0.2.60"]),
            ("single ipv4 port", "for=192.0.2.60:8080", ["192.0.2.60"]),
            ("quoted single ipv4", 'for="192.0.2.60"', ["192.0.2.60"]),
            ("quoted single ipv4 port", 'for="192.0.2.60:8080"', ["192.0.2.60"]),
            ("single ipv6", 'for="[2001:db8:cafe::17]"', ["2001:db8:cafe::17"]),
            ("single ipv6 port", 'for="[2001:db8:cafe::17]:4711"', ["2001:db8:cafe::17"]),
            ("ipv4 with spaces", " for = 192.0.2.60 ", ["192.0.2.60"]),
            ("multiple params", "for=192.0.2.60;proto=http;by=203.0.113.43", ["192.0.2.60"]),
            ("multiple IPs", "for=192.0.2.60, for=198.51.100.17", ["192.0.2.60", "198.51.100.17"]),
            ("multiple IPs with params", "for=192.0.2.60;proto=http;by=203.0.113.43, for=198.51.100.17", ["192.0.2.60", "198.51.100.17"]),
            ("mixed validity", "for=192.0.2.60, proto=http, for=198.51.100.17, for=", ["192.0.2.60", "198.51.100.17"]),
            ("capitalized keys", "For=192.0.2.60", ["192.0.2.60"]),
            ("ipv6 missing closing bracket", 'for="[2001:db8:cafe::17"', ["2001:db8:cafe::17"]),
            ("ipv4 simple port", "for=192.0.2.60:80", ["192.0.2.60"]),
            ("unknown key", "unknown=192.0.2.60", []),
            ("malformed header", "for;192.0.2.60", []),
            ("malformed element", "for=192.0.2.60;proto", ["192.0.2.60"]),
        ]

        for name, input_val, expected in cases:
            with self.subTest(msg=name):
                self.assertEqual(server.parse_forwarded_for(input_val), expected)


class TestParseHeaders(unittest.TestCase):
    def test_parse_headers_normal(self):
        header_str = "Content-Type: application/json\r\nAccept: text/html\r\n"
        expected = {"content-type": "application/json", "accept": "text/html"}
        self.assertEqual(server.parse_headers(header_str), expected)

    def test_parse_headers_empty(self):
        self.assertEqual(server.parse_headers(""), {})
        self.assertEqual(server.parse_headers("\r\n"), {})

    def test_parse_headers_no_colon(self):
        # A line without a colon is ignored
        header_str = "Content-Type: application/json\r\nInvalid-Header\r\nAccept: text/html\r\n"
        expected = {"content-type": "application/json", "accept": "text/html"}
        self.assertEqual(server.parse_headers(header_str), expected)

    def test_parse_headers_value_with_colon(self):
        # Value contains colon
        header_str = "Host: example.com:8080\r\n"
        expected = {"host": "example.com:8080"}
        self.assertEqual(server.parse_headers(header_str), expected)

    def test_parse_headers_trailing_newlines(self):
        # No trailing newline
        header_str1 = "Content-Type: application/json"
        expected1 = {"content-type": "application/json"}
        self.assertEqual(server.parse_headers(header_str1), expected1)

        # Multiple newlines
        header_str2 = "Content-Type: application/json\r\n\r\n\r\nAccept: text/html"
        expected2 = {"content-type": "application/json", "accept": "text/html"}
        self.assertEqual(server.parse_headers(header_str2), expected2)


class TestParseHeaderParams(unittest.TestCase):
    def test_parse_header_params(self):
        cases = [
            ("empty header", "", ("", {})),
            ("None header", None, ("", {})),
            ("simple content-type", "application/json", ("application/json", {})),
            ("simple content-type uppercase", "APPLICATION/JSON", ("application/json", {})),
            ("content-type with charset", "text/html; charset=utf-8", ("text/html", {"charset": "utf-8"})),
            ("content-type with quotes", 'text/html; charset="utf-8"', ("text/html", {"charset": "utf-8"})),
            ("content-type with single quotes", "text/html; charset='utf-8'", ("text/html", {"charset": "utf-8"})),
            ("multiple parameters", 'form-data; name="field"; filename="file.txt"', ("form-data", {"name": "field", "filename": "file.txt"})),
            ("uppercase param keys", 'TEXT/HTML; CHARSET=UTF-8; BOUNDARY="xyz"', ("text/html", {"charset": "UTF-8", "boundary": "xyz"})),
            ("whitespace formatting", '  text/html ;  charset =  utf-8  ', ("text/html", {"charset": "utf-8"})),
            ("value with equals sign", 'text/plain; boundary=key=value', ("text/plain", {"boundary": "key=value"})),
            ("malformed param missing equals", 'text/html; charset', ("text/html", {})),
            ("mixed valid and malformed params", 'text/html; invalid; charset=utf-8', ("text/html", {"charset": "utf-8"})),
        ]
        for name, input_str, expected in cases:
            with self.subTest(name=name):
                result = server.parse_header_params(input_str)
                self.assertEqual(result, expected)


class TestHashPassword(unittest.TestCase):
    def test_hash_format(self):
        password = "secret_password_123"
        hashed = server.hash_password(password)
        parts = hashed.split('$')

        self.assertEqual(len(parts), 6)
        self.assertEqual(parts[0], 'scrypt')
        self.assertEqual(int(parts[1]), server.SCRYPT_N)
        self.assertEqual(int(parts[2]), server.SCRYPT_R)
        self.assertEqual(int(parts[3]), server.SCRYPT_P)
        self.assertEqual(len(parts[4]), 32) # 16 bytes in hex is 32 chars
        self.assertTrue(len(parts[5]) >= 32) # length depends on scrypt config

    def test_salting_randomness(self):
        password = "secret_password_123"
        hashed1 = server.hash_password(password)
        hashed2 = server.hash_password(password)

        self.assertNotEqual(hashed1, hashed2)

        # Verify that the salts are different
        salt1 = hashed1.split('$')[4]
        salt2 = hashed2.split('$')[4]
        self.assertNotEqual(salt1, salt2)

    def test_empty_password(self):
        hashed = server.hash_password("")
        self.assertTrue(hashed.startswith(f'scrypt${server.SCRYPT_N}${server.SCRYPT_R}${server.SCRYPT_P}$'))
        self.assertEqual(len(hashed.split('$')), 6)

    def test_unicode_password(self):
        password = "🔒secret_password_日本語"
        hashed = server.hash_password(password)
        self.assertTrue(hashed.startswith(f'scrypt${server.SCRYPT_N}${server.SCRYPT_R}${server.SCRYPT_P}$'))
        self.assertEqual(len(hashed.split('$')), 6)

    @unittest.mock.patch('secrets.token_bytes')
    def test_deterministic_hash(self, mock_token_bytes):
        # Provide a known fixed salt (must be 16 bytes)
        mock_token_bytes.return_value = b'1234567890123456'
        password = "known_password"

        hashed = server.hash_password(password)

        # This exact hash output is generated deterministically given the fixed salt above
        expected_hash = (
            f"scrypt${server.SCRYPT_N}${server.SCRYPT_R}${server.SCRYPT_P}$"
            f"31323334353637383930313233343536$"
            f"ee72049a0f3bf77f0a0f07464eee4100249a418f983e3034275bb815fc8eb616"
            f"cfb4128519253968989d517b0a3a7763e1282b82c93d340d0fdfb1cc65b46cbf"
        )
        self.assertEqual(hashed, expected_hash)
        mock_token_bytes.assert_called_once_with(16)



class TestGenerateBackupCodes(unittest.TestCase):
    def test_generate_default_count(self):
        codes = server.generate_backup_codes()
        self.assertEqual(len(codes), 8)

    def test_generate_custom_count(self):
        codes = server.generate_backup_codes(count=5)
        self.assertEqual(len(codes), 5)

        codes_zero = server.generate_backup_codes(count=0)
        self.assertEqual(len(codes_zero), 0)

    def test_generate_backup_codes_format(self):
        import re
        codes = server.generate_backup_codes(count=10)
        pattern = re.compile(r'^[0-9A-F]{4}(-[0-9A-F]{4}){5}$')
        for code in codes:
            self.assertEqual(len(code), 29)
            self.assertTrue(pattern.match(code))

    def test_generate_backup_codes_unique(self):
        codes = server.generate_backup_codes(count=100)
        self.assertEqual(len(codes), len(set(codes)))

class TestNormalizeBackupCode(unittest.TestCase):
    def test_normalize_backup_code_normal(self):
        self.assertEqual(server.normalize_backup_code("1234ABCD"), "1234ABCD")

    def test_normalize_backup_code_lowercase(self):
        self.assertEqual(server.normalize_backup_code("1234abcd"), "1234ABCD")

    def test_normalize_backup_code_with_formatting(self):
        self.assertEqual(server.normalize_backup_code("1234-abcd 5678"), "1234ABCD5678")
        self.assertEqual(server.normalize_backup_code("!@#$%^&*()1234"), "1234")

    def test_normalize_backup_code_empty_and_none(self):
        self.assertEqual(server.normalize_backup_code(""), "")
        self.assertEqual(server.normalize_backup_code(None), "")

    def test_normalize_backup_code_non_string(self):
        self.assertEqual(server.normalize_backup_code(12345), "12345")


class TestHashBackupCode(unittest.TestCase):
    def test_hash_backup_code_normal(self):
        code = "1234ABCD"
        expected_hash = hashlib.sha256(code.encode('utf-8')).hexdigest()
        self.assertEqual(server.hash_backup_code(code), f"sha256${expected_hash}")

    def test_hash_backup_code_lowercase(self):
        code = "1234abcd"
        expected_hash = hashlib.sha256("1234ABCD".encode('utf-8')).hexdigest()
        self.assertEqual(server.hash_backup_code(code), f"sha256${expected_hash}")

    def test_hash_backup_code_with_formatting(self):
        code = "1234-abcd 5678"
        expected_hash = hashlib.sha256("1234ABCD5678".encode('utf-8')).hexdigest()
        self.assertEqual(server.hash_backup_code(code), f"sha256${expected_hash}")

    def test_hash_backup_code_empty_and_none(self):
        expected_hash = hashlib.sha256(b"").hexdigest()
        self.assertEqual(server.hash_backup_code(""), f"sha256${expected_hash}")
        self.assertEqual(server.hash_backup_code(None), f"sha256${expected_hash}")

    def test_hash_backup_code_non_string(self):
        expected_hash = hashlib.sha256(b"12345").hexdigest()
        self.assertEqual(server.hash_backup_code(12345), f"sha256${expected_hash}")


class TestVerifyPassword(unittest.TestCase):
    def test_verify_password_valid(self):
        password = "secret_password_123"
        encoded = server.hash_password(password)
        self.assertTrue(server.verify_password(password, encoded))

    def test_verify_password_invalid_password(self):
        password = "secret_password_123"
        encoded = server.hash_password(password)
        self.assertFalse(server.verify_password("wrong_password", encoded))

    def test_verify_password_invalid_formats_and_algorithms(self):
        valid_encoded = server.hash_password("secret_password_123")
        parts = valid_encoded.split('$')
        alg, iters, salt_hex, digest_hex = parts[0], parts[1], parts[2], parts[3]

        cases = [
            ("unsupported algorithm", f"pbkdf2_sha512${iters}${salt_hex}${digest_hex}", False),
            ("argon2 algorithm", f"argon2${iters}${salt_hex}${digest_hex}", False),
            ("too few segments", f"{alg}${iters}${salt_hex}", False),
            ("too many segments", f"{alg}${iters}${salt_hex}${digest_hex}$extra", False),
            ("non-integer iterations", f"{alg}$invalid_iters${salt_hex}${digest_hex}", False),
            ("non-hex salt", f"{alg}${iters}$not_hex_salt_string!${digest_hex}", False),
            ("empty string encoded", "", False),
            ("None encoded value", None, False),
            ("integer encoded value", 12345, False),
        ]

        for name, encoded_str, expected in cases:
            with self.subTest(name=name):
                self.assertIs(server.verify_password("secret_password_123", encoded_str), expected)


class TestSafeB64Decode(unittest.TestCase):
    def test_safe_b64decode_empty_or_none(self):
        self.assertEqual(server.safe_b64decode(''), b'')
        self.assertEqual(server.safe_b64decode(None), b'')

    def test_safe_b64decode_standard_padding(self):
        self.assertEqual(server.safe_b64decode('SGVsbG8gV29ybGQ='), b'Hello World')
        self.assertEqual(server.safe_b64decode('YW55IGNhcm5hbCBwbGVhcw=='), b'any carnal pleas')

    def test_safe_b64decode_standard_missing_padding(self):
        self.assertEqual(server.safe_b64decode('SGVsbG8gV29ybGQ'), b'Hello World')
        self.assertEqual(server.safe_b64decode('YW55IGNhcm5hbCBwbGVhcw'), b'any carnal pleas')

    def test_safe_b64decode_url_safe(self):
        self.assertEqual(server.safe_b64decode('-_8='), b'\xfb\xff')
        self.assertEqual(server.safe_b64decode('-_8'), b'\xfb\xff')

    def test_safe_b64decode_invalid_chars(self):
        import binascii
        with self.assertRaises(binascii.Error):
            server.safe_b64decode('invalid base64!!!')


class TestGenerateTOTPSecret(unittest.TestCase):
    @unittest.mock.patch('secrets.choice')
    def test_generate_totp_secret_properties(self, mock_choice):
        mock_choice.return_value = 'A'
        secret = server.generate_totp_secret()
        self.assertIsInstance(secret, str)
        self.assertEqual(len(secret), 16)
        valid_alphabet = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567')
        self.assertTrue(set(secret).issubset(valid_alphabet))
        self.assertEqual(secret, 'A'*16)
        self.assertEqual(mock_choice.call_count, 16)
        mock_choice.assert_called_with('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567')

    def test_generate_totp_secret_length(self):
        secret = server.generate_totp_secret()
        self.assertEqual(len(secret), 16)

    def test_generate_totp_secret_uniqueness(self):
        secrets_set = {server.generate_totp_secret() for _ in range(100)}
        self.assertEqual(len(secrets_set), 100)

    def test_generate_totp_secret_alphabet(self):
        secret = server.generate_totp_secret()
        valid_alphabet = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567')
        self.assertTrue(set(secret).issubset(valid_alphabet))


class TestComputeTOTPCode(unittest.TestCase):
    def test_compute_totp_code_known_values(self):
        secret = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
        self.assertEqual(server.compute_totp_code(secret, counter=1), '247374')
        self.assertEqual(server.compute_totp_code(secret, counter=59), '465435')
        self.assertEqual(server.compute_totp_code(secret, counter=37037036), '756375')

    def test_compute_totp_code_padding(self):
        secret_padded = 'NBSWY3DPO5XXE3DEEE======'
        secret_unpadded = 'NBSWY3DPO5XXE3DEEE'
        self.assertEqual(
            server.compute_totp_code(secret_padded, counter=1),
            server.compute_totp_code(secret_unpadded, counter=1)
        )

    def test_compute_totp_code_formatting(self):
        secret = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
        secret_lower = secret.lower()
        secret_spaces = f"  {secret}  "
        code1 = server.compute_totp_code(secret, counter=1)
        code2 = server.compute_totp_code(secret_lower, counter=1)
        code3 = server.compute_totp_code(secret_spaces, counter=1)
        self.assertEqual(code1, code2)
        self.assertEqual(code1, code3)

    @unittest.mock.patch('time.time')
    def test_compute_totp_code_default_counter(self, mock_time):
        # mock_time.return_value // 30 will be 37037036
        mock_time.return_value = 37037036 * 30 + 15
        secret = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
        code = server.compute_totp_code(secret)
        self.assertEqual(code, '756375')


class TestCreateServerBackupTemporaryFile(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.backup_dir = Path(self.temp_dir.name) / 'backups'
        self.data_dir = Path(self.temp_dir.name) / 'data'
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_file = self.data_dir / 'notki.db'

        self.backup_dir_patch = unittest.mock.patch('server.backup_directory', return_value=self.backup_dir)
        self.db_path_patch = unittest.mock.patch('server.DB_PATH', self.db_file)
        self.backup_dir_patch.start()
        self.db_path_patch.start()

        server.initialize_database()

    def tearDown(self):
        self.backup_dir_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_create_server_backup_uses_secure_temporary_file(self):
        class DummyHandler(server.NotkiHandler):
            def __init__(self):
                self.user = {'id': 1, 'role': 'admin', 'isAdmin': True}
                self.headers = {'X-Backup-Password': BACKUP_PASSWORD}
                self.response_body = None
                self.response_status = None

            def current_user(self):
                return self.user

            def send_json(self, data, status=200):
                self.response_body = data
                self.response_status = status

        handler = DummyHandler()
        handler.require_step_up = lambda user: None
        handler.create_server_backup()

        self.assertEqual(handler.response_status, 201)
        self.assertTrue(handler.response_body['encrypted'])
        self.assertEqual(handler.response_body['formatVersion'], 2)
        created_backup = self.backup_dir / handler.response_body['filename']
        self.assertTrue(created_backup.exists())
        leftovers = [path.name for path in self.backup_dir.iterdir() if path.name.startswith('.tmp-')]
        self.assertEqual(leftovers, [])
        if os.name != 'nt':
            self.assertEqual(created_backup.stat().st_mode & 0o777, 0o600)


class TestClientIPAndProxyTrust(unittest.TestCase):
    def setUp(self):
        self.original_env = os.environ.get('NOTKI_TRUST_PROXY')

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop('NOTKI_TRUST_PROXY', None)
        else:
            os.environ['NOTKI_TRUST_PROXY'] = self.original_env

    def _make_handler(self, client_ip, forwarded_for=None):
        class DummyHandler(server.NotkiHandler):
            def __init__(self, ip, fwd):
                self.client_address = (ip, 12345)
                self.headers = {}
                if fwd is not None:
                    self.headers['X-Forwarded-For'] = fwd
        return DummyHandler(client_ip, forwarded_for)

    def test_default_ignores_x_forwarded_for(self):
        os.environ.pop('NOTKI_TRUST_PROXY', None)
        handler = self._make_handler('192.168.1.50', '203.0.113.195')
        self.assertEqual(handler.get_client_ip(), '192.168.1.50')

    def test_trust_proxy_boolean_enabled(self):
        for val in ('1', 'true', 'yes', 'all', '*'):
            with self.subTest(val=val):
                os.environ['NOTKI_TRUST_PROXY'] = val
                handler = self._make_handler('127.0.0.1', '203.0.113.195, 10.0.0.1')
                self.assertEqual(handler.get_client_ip(), '203.0.113.195')

    def test_trust_proxy_boolean_disabled(self):
        for val in ('0', 'false', 'no'):
            with self.subTest(val=val):
                os.environ['NOTKI_TRUST_PROXY'] = val
                handler = self._make_handler('127.0.0.1', '203.0.113.195')
                self.assertEqual(handler.get_client_ip(), '127.0.0.1')

    def test_trust_proxy_ip_and_cidr_filtering(self):
        os.environ['NOTKI_TRUST_PROXY'] = '10.0.0.1, 192.168.1.0/24'

        # From trusted single IP
        h1 = self._make_handler('10.0.0.1', '203.0.113.10')
        self.assertEqual(h1.get_client_ip(), '203.0.113.10')

        # From trusted CIDR range
        h2 = self._make_handler('192.168.1.50', '203.0.113.20')
        self.assertEqual(h2.get_client_ip(), '203.0.113.20')

        # From untrusted IP address
        h3 = self._make_handler('172.16.0.1', '203.0.113.30')
        self.assertEqual(h3.get_client_ip(), '172.16.0.1')

    def test_trusted_proxy_chain_is_walked_from_the_right(self):
        os.environ['NOTKI_TRUST_PROXY'] = '127.0.0.1/32, 10.0.0.0/8'
        handler = self._make_handler(
            '127.0.0.1',
            '198.51.100.99, 203.0.113.195, 10.0.0.5',
        )
        # The leftmost value is attacker-controlled; the rightmost untrusted hop
        # is the only address a trusted proxy could not have supplied itself.
        self.assertEqual(handler.get_client_ip(), '203.0.113.195')


class Fail2banUnitTests(unittest.TestCase):
    def setUp(self):
        server.initialize_database()
        server.unban_all()

    def tearDown(self):
        server.unban_all()

    @unittest.mock.patch('server.database')
    def test_get_fail2ban_config(self, mock_db_manager):
        mock_connection = unittest.mock.MagicMock()
        mock_db_manager.return_value.__enter__.return_value = mock_connection

        # Test 1: Default configuration when database returns empty
        server._FAIL2BAN_CONFIG_CACHE = None
        mock_connection.execute.return_value.fetchall.return_value = []
        config = server.get_fail2ban_config()
        self.assertEqual(config, {'enabled': True, 'max_attempts': 15, 'ban_time': 60})

        # Test 2: Custom configuration when database returns values
        mock_connection.execute.return_value.fetchall.return_value = [
            {'key': 'fail2banEnabled', 'value': 'false'},
            {'key': 'fail2banMaxAttempts', 'value': '5'},
            {'key': 'fail2banBanTime', 'value': '120'}
        ]
        server._FAIL2BAN_CONFIG_CACHE = None
        config = server.get_fail2ban_config()
        self.assertEqual(config, {'enabled': False, 'max_attempts': 5, 'ban_time': 120})

        # Test 3: Exception during database operation falls back to default configuration
        mock_connection.execute.side_effect = Exception("DB error")
        server._FAIL2BAN_CONFIG_CACHE = None
        config = server.get_fail2ban_config()
        self.assertEqual(config, {'enabled': True, 'max_attempts': 15, 'ban_time': 60})

    def test_record_failed_auth_and_get_banned_ips(self):
        ip = '10.20.30.40'
        for _ in range(5):
            server.record_failed_auth(ip)
        banned = server.get_banned_ips()
        self.assertTrue(any(item['ip'] == ip for item in banned))

    def test_clear_failed_auth_only_clears_matching_account(self):
        ip = '10.20.30.41'
        for _ in range(5):
            server.record_failed_auth(ip, 'victim@example.com')
        for _ in range(5):
            server.record_failed_auth(ip, 'attacker@example.com')

        # A successful login for the attacker's own account must not erase the
        # per-IP budget nor the failures recorded against the victim account.
        server.clear_failed_auth(ip, 'attacker@example.com')
        self.assertEqual(len(server.FAILED_AUTH_ATTEMPTS.get(ip, [])), 10)
        self.assertNotIn('attacker@example.com', server.ACCOUNT_FAILURES)
        self.assertIn('victim@example.com', server.ACCOUNT_FAILURES)

        server.clear_failed_auth(ip, 'victim@example.com')
        self.assertEqual(len(server.FAILED_AUTH_ATTEMPTS.get(ip, [])), 10)
        self.assertNotIn('victim@example.com', server.ACCOUNT_FAILURES)

        # Clearing without an account (unban tooling) resets the whole IP budget.
        server.clear_failed_auth(ip)
        self.assertEqual(server.FAILED_AUTH_ATTEMPTS.get(ip, []), [])
        self.assertFalse(server.is_rate_limited(ip))

    def test_unban_single_and_all(self):
        ip1 = '10.0.0.1'
        ip2 = '10.0.0.2'
        server.record_failed_auth(ip1)
        server.record_failed_auth(ip2)

        self.assertTrue(server.unban_ip(ip1))
        banned = [item['ip'] for item in server.get_banned_ips()]
        self.assertNotIn(ip1, banned)
        self.assertIn(ip2, banned)

        server.unban_all()
        self.assertEqual(len(server.get_banned_ips()), 0)

    def test_unban_cli_english_output(self):
        ip = '192.168.1.88'
        server.record_failed_auth(ip)

        buf = io.StringIO()
        with unittest.mock.patch('sys.stdout', buf):
            server.unban_ip_cli(ip)
        self.assertIn(f'Unbanned IP {ip}.', buf.getvalue())

        buf_all = io.StringIO()
        with unittest.mock.patch('sys.stdout', buf_all):
            server.unban_all_cli()
        self.assertIn('Unbanned all IPs', buf_all.getvalue())

    def test_is_account_rate_limited(self):
        # Empty account key
        self.assertFalse(server.is_account_rate_limited(''))

        account = 'test_limit@example.com'
        server.ACCOUNT_FAILURES.clear()
        import time

        with unittest.mock.patch('server.get_fail2ban_config', return_value={'max_attempts': 3}):
            # Default max_failed is max(50, 3 * 5) = 50

            # Use max_failed=5 directly for testing
            now = time.time()
            server.ACCOUNT_FAILURES[server.account_key(account)] = [now, now, now]
            self.assertFalse(server.is_account_rate_limited(account, max_failed=5))

            server.ACCOUNT_FAILURES[server.account_key(account)] = [now, now, now, now, now]
            self.assertTrue(server.is_account_rate_limited(account, max_failed=5))

            # Test window expiry
            old = now - 4000
            server.ACCOUNT_FAILURES[server.account_key(account)] = [old, old, old, old, old, now]
            self.assertFalse(server.is_account_rate_limited(account, max_failed=5, window_seconds=3600))


class Fail2banAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.db_file = Path(cls.tmp_dir.name) / 'test_notki.sqlite3'
        os.environ['NOTKI_DB_PATH'] = str(cls.db_file)
        server.DB_PATH = cls.db_file

        server.initialize_database()

        cls.server = server.ThreadingHTTPServer(('127.0.0.1', 0), server.NotkiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp_dir.cleanup()

    def setUp(self):
        server.unban_all()
        with server.database() as conn:
            conn.execute('DELETE FROM sessions')
            conn.execute('DELETE FROM users')
            conn.execute('DELETE FROM settings')
        self.admin = self.register_user('admin_f2b@example.com', 'admin-passphrase-123', role='admin')
        self.user = self.register_user('user_f2b@example.com', 'user-passphrase-123', role='user')

    def register_user(self, email, password, role='user'):
        now = server.iso_time()
        with server.database() as conn:
            cursor = conn.execute(
                'INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)',
                (email, server.hash_password(password), role, now)
            )
            user_id = cursor.lastrowid

        token = secrets.token_urlsafe(32)
        with server.database() as conn:
            conn.execute(
                'INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)',
                (server.token_hash(token), user_id, server.iso_time(server.utc_now() + timedelta(days=1)))
            )
        return f'{server.SESSION_COOKIE}={token}'

    def request(self, cookie, method, path, body=None):
        url = f'http://127.0.0.1:{self.port}{path}'
        headers = {'Cookie': cookie} if cookie else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'

        req = urllib.request.Request(url, data=data, headers=with_same_origin(url, headers), method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
                return resp.status, payload
        except urllib.error.HTTPError as e:
            payload = json.loads(e.read().decode('utf-8'))
            return e.code, payload

    def test_fail2ban_api_workflow(self):
        server.record_failed_auth('192.168.100.1')
        server.record_failed_auth('192.168.100.2')

        # Non-admin forbidden
        status, _ = self.request(self.user, 'GET', '/api/admin/fail2ban')
        self.assertEqual(status, 403)

        # Admin GET
        status, res = self.request(self.admin, 'GET', '/api/admin/fail2ban')
        self.assertEqual(status, 200)
        self.assertIn('bannedIps', res)
        ips = [item['ip'] for item in res['bannedIps']]
        self.assertIn('192.168.100.1', ips)
        self.assertIn('192.168.100.2', ips)

        # Admin DELETE single IP
        status, res = self.request(self.admin, 'DELETE', '/api/admin/fail2ban/192.168.100.1')
        self.assertEqual(status, 200)
        self.assertEqual(res['unbannedIp'], '192.168.100.1')

        status, res = self.request(self.admin, 'GET', '/api/admin/fail2ban')
        ips = [item['ip'] for item in res['bannedIps']]
        self.assertNotIn('192.168.100.1', ips)
        self.assertIn('192.168.100.2', ips)

        # Admin DELETE all
        status, res = self.request(self.admin, 'DELETE', '/api/admin/fail2ban/all')
        self.assertEqual(status, 200)
        self.assertTrue(res['unbannedAll'])

        status, res = self.request(self.admin, 'GET', '/api/admin/fail2ban')
        self.assertEqual(len(res['bannedIps']), 0)

    def test_save_fail2ban_settings_api(self):
        status, res = self.request(self.admin, 'POST', '/api/admin/settings', {
            'fail2banEnabled': False,
            'fail2banMaxAttempts': 10,
            'fail2banBanTime': 300
        })
        self.assertEqual(status, 200)
        self.assertFalse(res['fail2banEnabled'])
        self.assertEqual(res['fail2banMaxAttempts'], 10)
        self.assertEqual(res['fail2banBanTime'], 300)

        status, settings = self.request(self.admin, 'GET', '/api/admin/settings')
        self.assertEqual(status, 200)
        self.assertFalse(settings['fail2banEnabled'])
        self.assertEqual(settings['fail2banMaxAttempts'], 10)
        self.assertEqual(settings['fail2banBanTime'], 300)

    def test_save_fail2ban_limit_settings_effect(self):
        status, res = self.request(self.admin, 'POST', '/api/admin/settings', {
            'fail2banEnabled': True,
            'fail2banMaxAttempts': 3,
            'fail2banBanTime': 60
        })
        self.assertEqual(status, 200)
        self.assertTrue(res['fail2banEnabled'])
        self.assertEqual(res['fail2banMaxAttempts'], 3)
        self.assertEqual(res['fail2banBanTime'], 60)

        test_ip = '192.168.200.5'
        server.unban_ip(test_ip)

        self.assertFalse(server.is_rate_limited(test_ip))
        server.record_failed_auth(test_ip)
        server.record_failed_auth(test_ip)
        self.assertFalse(server.is_rate_limited(test_ip))
        server.record_failed_auth(test_ip)
        self.assertTrue(server.is_rate_limited(test_ip))

        server.unban_ip(test_ip)


class TestSecurityAndBackupFixes(ServerFlowTests):
    def test_backup_code_hashing_and_encrypted_backup(self):
        # Create user with 2FA
        status, invite = self.request(self.admin, 'POST', '/api/admin/invites', {})
        invite_token = parse_qs(urlsplit(invite['url']).query)['invite'][0]
        user_client = self.new_client()
        status, _ = self.request(user_client, 'POST', '/api/register', {
            'email': 'encbackupuser@example.com', 'password': 'user-passphrase-123', 'invite': invite_token
        })
        self.assertEqual(status, 201)

        # Enable TOTP and verify backup codes are hashed in DB
        status, res = self.request(user_client, 'POST', '/api/account/totp', {})
        secret = res['secret']
        totp_code = server.compute_totp_code(secret)
        status, res = self.request(user_client, 'POST', '/api/account/totp/verify', {'code': totp_code})
        backup_codes = res.get('backupCodes', [])
        self.assertTrue(len(backup_codes) > 0)

        with server.database() as conn:
            row = conn.execute("SELECT backup_codes_json FROM users WHERE email = 'encbackupuser@example.com'").fetchone()
            stored = json.loads(row['backup_codes_json'])
            # Verify stored backup codes are hashed (start with sha256$)
            self.assertTrue(stored[0].startswith('sha256$'))

        # Create encrypted server backup
        status, backup = self.request(self.admin, 'POST', '/api/admin/backups', {'encryptionPassword': 'secret-backup-pass'})
        self.assertEqual(status, 201)
        self.assertTrue(backup['filename'].endswith('.enc'))

        # Restoring encrypted backup with wrong password should fail with 400
        status, err = self.request(self.admin, 'POST', f"/api/admin/backups/{backup['filename']}/restore", {'encryptionPassword': 'wrong-password'})
        self.assertEqual(status, 400)

        # Restoring encrypted backup with correct password should succeed
        status, restored = self.request(self.admin, 'POST', f"/api/admin/backups/{backup['filename']}/restore", {'encryptionPassword': 'secret-backup-pass'})
        self.assertEqual(status, 200)

    def test_passkey_and_announcement_limits(self):
        # Passkey key_id too long (> 512 chars)
        long_key_id = 'a' * 513
        status, res = self.request(self.admin, 'POST', '/api/account/passkey', {'id': long_key_id, 'publicKey': 'abc'})
        self.assertEqual(status, 400)

        # Passkey key_id invalid type
        status, res = self.request(self.admin, 'POST', '/api/account/passkey', {'id': 12345, 'publicKey': 'abc'})
        self.assertEqual(status, 400)

        # Announcement over 2000 chars should fail
        long_ann = 'x' * 2001
        status, res = self.request(self.admin, 'POST', '/api/admin/settings', {'announcement': long_ann})
        self.assertEqual(status, 400)

        # Valid announcement under 2000 chars
        valid_ann = 'x' * 2000
        status, res = self.request(self.admin, 'POST', '/api/admin/settings', {'announcement': valid_ann})
        self.assertEqual(status, 200)

    def test_remote_setup_requires_token(self):
        with unittest.mock.patch.dict('os.environ', {'NOTKI_ALLOW_REMOTE_SETUP': '1'}, clear=False):
            class DummyHandler(server.NotkiHandler):
                def __init__(self):
                    self.client_address = ('192.168.1.100', 12345)
                    self.headers = {'Host': 'example.com'}
            handler = DummyHandler()
            self.assertFalse(handler.check_setup_permission())

    def test_setup_status_does_not_expose_accounts(self):
        self.register_user('hidden@example.com')
        status, res = self.request(self.new_client(), 'GET', '/api/setup/status')
        self.assertEqual(status, 200)
        self.assertEqual(res, {'needsSetup': False})

    def test_totp_step_up_requirements(self):
        user = self.register_user('totpstepup@example.com', 'user-passphrase-123')
        with server.database() as connection:
            user_id = connection.execute(
                "SELECT id FROM users WHERE email = 'totpstepup@example.com'"
            ).fetchone()['id']
            connection.execute(
                'UPDATE sessions SET authenticated_at = ? WHERE user_id = ?',
                (server.iso_time(server.utc_now() - timedelta(minutes=30)), user_id),
            )

        status, _ = self.request(user, 'POST', '/api/account/totp')
        self.assertEqual(status, 403)

        status, _ = self.request(user, 'POST', '/api/account/totp/verify', {'code': '000000'})
        self.assertEqual(status, 403)

        status, res = self.request(
            user, 'POST', '/api/account/totp',
            headers={'X-Step-Up-Password': 'user-passphrase-123'},
        )
        self.assertEqual(status, 200)
        self.assertIn('secret', res)

        secret = res['secret']
        code = server.compute_totp_code(secret)

        status, verify_res = self.request(
            user, 'POST', '/api/account/totp/verify',
            {'code': code},
            headers={'X-Step-Up-Password': 'user-passphrase-123'},
        )
        self.assertEqual(status, 200)
        self.assertIn('backupCodes', verify_res)

    def test_step_up_requires_recent_authentication(self):
        user = self.register_user('stepup@example.com', 'user-passphrase-123')
        with server.database() as connection:
            user_id = connection.execute(
                "SELECT id FROM users WHERE email = 'stepup@example.com'"
            ).fetchone()['id']
            connection.execute(
                'UPDATE sessions SET authenticated_at = ? WHERE user_id = ?',
                (server.iso_time(server.utc_now() - timedelta(minutes=30)), user_id),
            )

        status, _ = self.request(user, 'DELETE', '/api/account/totp')
        self.assertEqual(status, 403)

        status, _ = self.request(
            user, 'DELETE', '/api/account/totp',
            headers={'X-Step-Up-Password': 'user-passphrase-123'},
        )
        self.assertEqual(status, 200)

    def test_public_host_invite_link(self):
        with unittest.mock.patch('server.PUBLIC_HOST', 'https://notki.example.com'):
            status, res = self.request(
                self.admin, 'POST', '/api/admin/invites', {},
                headers={'Origin': 'https://notki.example.com'},
            )
            self.assertEqual(status, 201)
            self.assertTrue(res['url'].startswith('https://notki.example.com/?invite='))
if __name__ == '__main__':
    unittest.main()
