import base64
import hashlib
import os
import secrets
import http.cookiejar
import io
import json
import subprocess
import tarfile
import tempfile
import threading
import unittest
import unittest.mock
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
import urllib.request
import urllib.error
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import server


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

    def request_raw_client(self, client, method, path, body, content_type='application/gzip'):
        request = Request(
            self.base_url + path,
            data=body,
            headers=with_same_origin(self.base_url, {'Content-Type': content_type}),
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

        status, backup = self.request(self.admin, 'POST', '/api/admin/backups', {})
        self.assertEqual(status, 201)

        status, backup_list = self.request(self.admin, 'GET', '/api/admin/backups')
        self.assertEqual(status, 200)
        matching_backup = next(b for b in backup_list['backups'] if b['filename'] == backup['filename'])

        status, result = self.request(self.admin, 'POST', f"/api/admin/backups/{backup['filename']}/restore", {})
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
        status, backup = self.request(self.admin, 'POST', '/api/admin/backups', {})
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

        status, backup = self.request(self.admin, 'POST', '/api/admin/backups', {})
        self.assertEqual(status, 201)
        filename = backup['filename']

        status, _ = self.request(self.admin, 'POST', '/api/account/avatar', {'avatar': None})
        self.assertEqual(status, 200)

        status, _ = self.request(self.admin, 'POST', f'/api/admin/backups/{filename}/restore', {})
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

    def test_update_check_and_perform_version_comparison(self):
        # Test check update with newer tag
        tags_response = json.dumps([{'name': '0.1.6.2', 'tarball_url': 'https://api.github.com/repos/shirou93/Notki/tarball/v0.1.6.2'}]).encode('utf-8')
        with unittest.mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_cm = unittest.mock.MagicMock()
            mock_cm.__enter__.return_value.read.return_value = tags_response
            mock_urlopen.return_value = mock_cm

            status, res = self.request(self.admin, 'GET', '/api/admin/update/check')
            self.assertEqual(status, 200)
            self.assertTrue(res.get('updateAvailable', False))
            self.assertEqual(res.get('latestVersion'), '0.1.6.2')

        # Test check update with same tag
        tags_response_same = json.dumps([{'name': '0.1.6.1', 'tarball_url': 'https://api.github.com/repos/shirou93/Notki/tarball/v0.1.6.1'}]).encode('utf-8')
        with unittest.mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_cm = unittest.mock.MagicMock()
            mock_cm.__enter__.return_value.read.return_value = tags_response_same
            mock_urlopen.return_value = mock_cm

            status, res = self.request(self.admin, 'GET', '/api/admin/update/check')
            self.assertEqual(status, 200)
            self.assertFalse(res.get('updateAvailable', True))

        # Test perform update fails when tarball contains same version
        tarball_buf = io.BytesIO()
        server_code = f"VERSION = '{server.VERSION}'\n".encode('utf-8')
        with tarfile.open(fileobj=tarball_buf, mode='w:gz') as archive:
            member = tarfile.TarInfo('repo-tag/server.py')
            member.size = len(server_code)
            archive.addfile(member, io.BytesIO(server_code))

        with unittest.mock.patch('server.urllib.request.build_opener') as mock_build_opener:
            mock_opener = unittest.mock.MagicMock()
            mock_cm = unittest.mock.MagicMock()
            mock_cm.__enter__.return_value.read.return_value = tarball_buf.getvalue()
            mock_opener.open.return_value = mock_cm
            mock_build_opener.return_value = mock_opener

            with unittest.mock.patch.dict(os.environ, {'NOTKI_ALLOW_UNVERIFIED_UPDATES': '1'}):
                status, res = self.request(self.admin, 'POST', '/api/admin/update/perform', {
                    'tarballUrl': 'https://api.github.com/repos/shirou93/Notki/tarball/v0.1.5.94'
                })
            self.assertEqual(status, 400)
            self.assertEqual(res['error'], 'No newer version available.')

    def test_update_check_and_perform_beta(self):
        # Test check update with beta query parameter
        status, res = self.request(self.admin, 'GET', '/api/admin/update/check?beta=1')
        self.assertEqual(status, 200)
        self.assertTrue(res.get('updateAvailable', False))
        self.assertEqual(res.get('latestVersion'), 'main (beta)')
        self.assertEqual(res.get('tarballUrl'), 'https://api.github.com/repos/shirou93/Notki/tarball/main')
        self.assertTrue(res.get('isBeta', False))

        # Test perform beta update succeeds even when tarball contains same version
        tarball_buf = io.BytesIO()
        server_code = f"VERSION = '{server.VERSION}'\n".encode('utf-8')
        with tarfile.open(fileobj=tarball_buf, mode='w:gz') as archive:
            member = tarfile.TarInfo('repo-main/server.py')
            member.size = len(server_code)
            archive.addfile(member, io.BytesIO(server_code))

        with unittest.mock.patch('server.urllib.request.build_opener') as mock_build_opener, \
             unittest.mock.patch('server.NotkiHandler._extract_update_archive') as mock_extract, \
             unittest.mock.patch('threading.Timer') as mock_timer:
            mock_opener = unittest.mock.MagicMock()
            mock_cm = unittest.mock.MagicMock()
            mock_cm.__enter__.return_value.read.return_value = tarball_buf.getvalue()
            mock_opener.open.return_value = mock_cm
            mock_build_opener.return_value = mock_opener

            with unittest.mock.patch.dict(os.environ, {'NOTKI_ALLOW_BETA_UPDATES': '1', 'NOTKI_ALLOW_UNVERIFIED_UPDATES': '1'}):
                status, res = self.request(self.admin, 'POST', '/api/admin/update/perform', {
                    'tarballUrl': 'https://api.github.com/repos/shirou93/Notki/tarball/main',
                    'isBeta': True
                })
            self.assertEqual(status, 200)
            self.assertTrue(res.get('success', False))
            self.assertTrue(mock_extract.called)

    def test_finalize_update_index_html(self):
        handler = server.NotkiHandler
        dummy_handler = unittest.mock.MagicMock(spec=server.NotkiHandler)

        # Test beta update replaces ALPHA or empty badge with BETA
        with unittest.mock.patch('pathlib.Path.exists', return_value=True), \
             unittest.mock.patch('pathlib.Path.read_text', return_value='<span class="sidebar-version">NOTKI · ALPHA 0.1.5.94</span>'), \
             unittest.mock.patch('pathlib.Path.write_text') as mock_write:
            server.NotkiHandler._finalize_update_index_html(dummy_handler, is_beta=True)
            mock_write.assert_called_once_with('<span class="sidebar-version">NOTKI · BETA 0.1.5.94</span>', encoding='utf-8')

        # Test standard update removes ALPHA/BETA badge and keeps only digits
        with unittest.mock.patch('pathlib.Path.exists', return_value=True), \
             unittest.mock.patch('pathlib.Path.read_text', return_value='<span class="sidebar-version">NOTKI · ALPHA 0.1.6.0</span>'), \
             unittest.mock.patch('pathlib.Path.write_text') as mock_write:
            server.NotkiHandler._finalize_update_index_html(dummy_handler, is_beta=False)
            mock_write.assert_called_once_with('<span class="sidebar-version">NOTKI · 0.1.6.0</span>', encoding='utf-8')

        # Test standard update removes BETA badge if previously updated from beta
        with unittest.mock.patch('pathlib.Path.exists', return_value=True), \
             unittest.mock.patch('pathlib.Path.read_text', return_value='<span class="sidebar-version">NOTKI · BETA 0.1.6.0</span>'), \
             unittest.mock.patch('pathlib.Path.write_text') as mock_write:
            server.NotkiHandler._finalize_update_index_html(dummy_handler, is_beta=False)
            mock_write.assert_called_once_with('<span class="sidebar-version">NOTKI · 0.1.6.0</span>', encoding='utf-8')

    def test_admin_settings_and_logs(self):
        # Non-admin / unauthenticated cannot access settings or logs
        user = self.new_client()
        status, _ = self.request(user, 'GET', '/api/admin/settings')
        self.assertEqual(status, 401)
        status, _ = self.request(user, 'GET', '/api/admin/logs')
        self.assertEqual(status, 401)

        # Admin GET settings default
        status, settings = self.request(self.admin, 'GET', '/api/admin/settings')
        self.assertEqual(status, 200)
        self.assertFalse(settings['require2FA'])
        self.assertEqual(settings['logLevel'], 'INFO')
        self.assertEqual(settings['announcement'], '')

        # Admin POST settings (2FA must be configured before it can be required)
        self.enable_admin_2fa()
        status, updated = self.request(self.admin, 'POST', '/api/admin/settings', {
            'require2FA': True, 'logLevel': 'DEBUG', 'announcement': 'Patching in progress...'
        })
        self.assertEqual(status, 200)
        self.assertTrue(updated['require2FA'])
        self.assertEqual(updated['logLevel'], 'DEBUG')
        self.assertEqual(updated['announcement'], 'Patching in progress...')

        # User session & notes include announcement
        user_client = self.new_client()
        status, session_info = self.request(self.admin, 'GET', '/api/session')
        self.assertEqual(status, 200)
        self.assertEqual(session_info.get('announcement'), 'Patching in progress...')

        status, notes_info = self.request(self.admin, 'GET', '/api/notes')
        self.assertEqual(status, 200)

        # Admin POST settings invalid log level
        status, err = self.request(self.admin, 'POST', '/api/admin/settings', {
            'logLevel': 'INVALID'
        })
        self.assertEqual(status, 400)
        self.assertEqual(err['error'], 'Invalid log level.')

        # Verify GET settings updated
        status, settings = self.request(self.admin, 'GET', '/api/admin/settings')
        self.assertEqual(status, 200)
        self.assertTrue(settings['require2FA'])
        self.assertEqual(settings['logLevel'], 'DEBUG')

        # Reset require2FA so it doesn't break subsequent tests that use this session
        self.request(self.admin, 'POST', '/api/admin/settings', {'require2FA': False, 'logLevel': 'INFO', 'announcement': ''})

        # Admin GET logs
        status, logs_resp = self.request(self.admin, 'GET', '/api/admin/logs')
        self.assertEqual(status, 200)
        self.assertIn('logs', logs_resp)
        self.assertIsInstance(logs_resp['logs'], list)

    def test_upload_restore_server_backup(self):
        created_at = server.iso_time()
        snapshot = {
            'format': 'notki-server-snapshot', 'version': 1, 'createdAt': created_at,
            'users': [{
                'id': 1, 'email': 'uploaded-admin@example.com',
                'passwordHash': server.hash_password('uploaded-admin-password'),
                'role': 'admin', 'createdAt': created_at,
            }],
            'notes': [{
                'id': 'uploaded-note', 'userId': 1, 'title': 'Uploaded Note',
                'body': 'Uploaded Body', 'bodyFormat': 0, 'color': 'mint', 'tags': ['uploaded'],
                'pinned': False, 'archived': False, 'deleted': False,
                'createdAt': created_at, 'updatedAt': created_at, 'order': 1,
            }], 'invites': [], 'shares': [],
        }
        snapshot_bytes = json.dumps(snapshot).encode('utf-8')

        # Admin restores from uploaded file
        status, result = self.request_raw_client(self.admin, 'POST', '/api/admin/backups/upload-restore', snapshot_bytes)
        self.assertEqual(status, 200)
        self.assertTrue(result['restored'])

        # Sign in with restored credentials
        client = self.new_client()
        status, login = self.request(client, 'POST', '/api/login', {
            'email': 'uploaded-admin@example.com', 'password': 'uploaded-admin-password',
        })
        self.assertEqual(status, 200)
        status, notes = self.request(client, 'GET', '/api/notes')
        self.assertEqual(status, 200)
        self.assertEqual(notes['notes'][0]['title'], 'Uploaded Note')

    def test_backup_restore_replaces_server_and_delete_removes_archive(self):
        original_note = {
            'id': 'original-note', 'title': 'Stan z backupu', 'body': 'Odtworzona treść',
            'bodyFormat': 0, 'color': 'default', 'tags': [], 'pinned': False,
            'archived': False, 'deleted': False, 'createdAt': server.iso_time(),
            'updatedAt': server.iso_time(), 'order': 1,
        }
        status, _ = self.request(self.admin, 'PUT', '/api/notes', {'notes': [original_note]})
        self.assertEqual(status, 200)
        status, backup = self.request(self.admin, 'POST', '/api/admin/backups', {})
        self.assertEqual(status, 201)

        changed_note = {**original_note, 'id': 'later-note', 'title': 'Nowszy stan'}
        status, _ = self.request(self.admin, 'PUT', '/api/notes', {'notes': [changed_note]})
        self.assertEqual(status, 200)
        status, restored = self.request(
            self.admin, 'POST', f"/api/admin/backups/{backup['filename']}/restore", {},
        )
        self.assertEqual(status, 200)
        self.assertTrue(restored['restored'])
        self.assertEqual(restored['notes'], 1)

        status, session = self.request(self.admin, 'GET', '/api/session')
        self.assertEqual(status, 200)
        self.assertIsNone(session['user'])
        status, _ = self.request(self.admin, 'GET', '/api/admin/summary')
        self.assertEqual(status, 401)

        restored_admin = self.new_client()
        status, _ = self.request(restored_admin, 'POST', '/api/login', {
            'email': 'admin@example.com', 'password': 'secure-passphrase-1',
        })
        self.assertEqual(status, 200)
        status, notes = self.request(restored_admin, 'GET', '/api/notes')
        self.assertEqual(status, 200)
        self.assertEqual(notes['notes'][0]['title'], 'Stan z backupu')

        status, deleted = self.request(
            restored_admin, 'DELETE', f"/api/admin/backups/{backup['filename']}", {},
        )
        self.assertEqual(status, 200)
        self.assertEqual(deleted['deleted'], backup['filename'])
        status, backups = self.request(restored_admin, 'GET', '/api/admin/backups')
        self.assertEqual(status, 200)
        self.assertEqual(backups['backups'], [])

    def test_backup_path_traversal_rejected(self):
        traversal_filenames = [
            'notki-../test.json',
            'notki-../../etc/passwd.json',
            'notki-sub/dir.json',
        ]
        for filename in traversal_filenames:
            status, _ = self.request(self.admin, 'GET', f'/api/admin/backups/{filename}')
            self.assertEqual(status, 404)
            status, _ = self.request(self.admin, 'POST', f'/api/admin/backups/{filename}/restore', {})
            self.assertEqual(status, 404)
            status, _ = self.request(self.admin, 'DELETE', f'/api/admin/backups/{filename}')
            self.assertEqual(status, 404)

    def test_login_passkey_challenge_endpoint(self):
        client = self.new_client()
        status, res = self.request(client, 'GET', '/api/login/passkey/challenge')
        self.assertEqual(status, 200)
        self.assertIn('challengeId', res)
        self.assertIn('challengeBase64', res)
        self.assertIsInstance(res['allowCredentials'], list)

    @unittest.mock.patch('server.webauthn.verify_authentication_response')
    def test_passkey_sign_count_regression(self, mock_verify):
        mock_verify.side_effect = Exception("Sign count regression")

        user_client = self.register_user('signcountuser@example.com', 'user-passphrase-123')
        # Insert passkey directly
        with server.database() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = 'signcountuser@example.com'").fetchone()
            user_id = user_row['id']
            conn.execute('INSERT INTO passkeys (id, user_id, name, public_key_pem, created_at, sign_count) VALUES (?, ?, ?, ?, ?, ?)', ('pk-signcount', user_id, 'My Key', 'pem', '2026-01-01T00:00:00Z', 10))

        status, chal_res = self.request(self.new_client(), 'GET', '/api/login/passkey/challenge')
        self.assertEqual(status, 200)

        payload = {
            'id': 'pk-signcount',
            'authenticatorData': 'YXV0aERhdGE=',
            'clientDataJSON': 'Y2xpZW50RGF0YQ==',
            'signature': 'c2lnbmF0dXJl',
            'challengeId': chal_res['challengeId']
        }
        status, res = self.request(self.new_client(), 'POST', '/api/login/passkey', payload)
        self.assertEqual(status, 401)
        self.assertEqual(res['error'], 'Invalid passkey signature.')

    @unittest.mock.patch('server.webauthn.verify_registration_response')
    def test_add_passkey_account_takeover(self, mock_verify):
        mock_verify.return_value = unittest.mock.Mock(
            credential_public_key=b'dummy_pub_key',
            sign_count=0
        )

        userA = self.register_user('userA@example.com', 'passphrase-A-123')
        userB = self.register_user('userB@example.com', 'passphrase-B-123')

        passkey_id = 'test-passkey-id-at'

        status, chal_res = self.request(userA, 'GET', '/api/login/passkey/challenge')

        # userA registers a passkey
        status, res = self.request(userA, 'POST', '/api/account/passkey', {
            'id': passkey_id, 'name': 'Laptop A', 'publicKey': 'ZHVtbXk=',
            'authenticatorData': 'YXV0aERhdGE=',
            'clientDataJSON': 'Y2xpZW50RGF0YQ==',
            'attestationObject': 'YXR0ZXN0YXRpb24=',
            'challengeId': chal_res['challengeId']
        })
        self.assertEqual(status, 201)

        status, chal_res2 = self.request(userB, 'GET', '/api/login/passkey/challenge')

        # userB tries to register a passkey with the same ID
        status, res = self.request(userB, 'POST', '/api/account/passkey', {
            'id': passkey_id, 'name': 'Laptop B', 'publicKey': 'ZHVtbXk=',
            'authenticatorData': 'YXV0aERhdGE=',
            'clientDataJSON': 'Y2xpZW50RGF0YQ==',
            'attestationObject': 'YXR0ZXN0YXRpb24=',
            'challengeId': chal_res2['challengeId']
        })
        self.assertEqual(status, 409)

        # Verify userA's passkey hasn't changed
        status, res = self.request(userA, 'GET', '/api/account/2fa')
        self.assertEqual(status, 200)
        self.assertEqual(len(res['passkeys']), 1)
        self.assertEqual(res['passkeys'][0]['id'], passkey_id)
        self.assertEqual(res['passkeys'][0]['name'], 'Laptop A')

    def test_require_2fa_enforcement(self):
        # Create a user and get a session (while require2FA is false)
        client = self.register_user('enforce2fa@example.com', 'password1234')

        # Admin enables require2FA
        self.enable_admin_2fa()
        status, _ = self.request(self.admin, 'POST', '/api/admin/settings', {'require2FA': True, 'logLevel': 'INFO'})
        self.assertEqual(status, 200)

        # Existing session now gets 403 on normal endpoints
        status, _ = self.request(client, 'GET', '/api/notes')
        self.assertEqual(status, 403)

        # But can still access setup endpoints
        status, totp_res = self.request(client, 'POST', '/api/account/totp', {})
        self.assertEqual(status, 200)

        secret = totp_res['secret']
        code = server.compute_totp_code(secret)
        status, verify_res = self.request(client, 'POST', '/api/account/totp/verify', {'code': code})
        self.assertEqual(status, 200)

        # After setup, should be able to access normal endpoints again
        status, _ = self.request(client, 'GET', '/api/notes')
        self.assertEqual(status, 200)

        # Reset for subsequent tests
        self.request(self.admin, 'POST', '/api/admin/settings', {'require2FA': False, 'logLevel': 'INFO'})

    def test_totp_and_passkey_2fa_flow(self):
        user_client = self.register_user('user2fa@example.com', 'user-passphrase-123')

        # 1. Get 2FA status
        status, res = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertEqual(status, 200)
        self.assertFalse(res['hasTotp'])
        self.assertEqual(res['passkeys'], [])

        # 2. Setup TOTP
        status, res = self.request(user_client, 'POST', '/api/account/totp', {})
        self.assertEqual(status, 200)
        secret = res['secret']
        self.assertTrue(len(secret) >= 16)
        self.assertIn('<svg', res['qrSvg'])

        # Verify invalid TOTP code
        status, error = self.request(user_client, 'POST', '/api/account/totp/verify', {'code': '000000'})
        self.assertEqual(status, 400)

        # Verify valid TOTP code
        code = server.compute_totp_code(secret)
        status, res = self.request(user_client, 'POST', '/api/account/totp/verify', {'code': code})
        self.assertEqual(status, 200)
        self.assertTrue(res['verified'])
        self.assertIn('backupCodes', res)
        self.assertEqual(len(res['backupCodes']), 8)
        backup_code = res['backupCodes'][0]

        # 2FA status should now be active
        status, res = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertTrue(res['hasTotp'])

        # Test required 2FA when user does not have 2FA configured
        self.register_user('no2fa@example.com', 'user-passphrase-123')
        self.enable_admin_2fa()
        self.request(self.admin, 'POST', '/api/admin/settings', {'require2FA': True, 'logLevel': 'INFO'})
        unauth_no2fa = self.new_client()
        status, login_res = self.request(unauth_no2fa, 'POST', '/api/login', {'email': 'no2fa@example.com', 'password': 'user-passphrase-123'})
        self.assertEqual(status, 403)
        self.request(self.admin, 'POST', '/api/admin/settings', {'require2FA': False, 'logLevel': 'INFO'})

        # 3. Test 2FA login with TOTP
        unauth_client = self.new_client()
        status, res = self.request(unauth_client, 'POST', '/api/login', {'email': 'user2fa@example.com', 'password': 'user-passphrase-123'})
        self.assertEqual(status, 200)
        self.assertTrue(res['requires2FA'])
        self.assertTrue(res['hasTotp'])
        temp_token = res['tempToken']

        # Login 2FA with invalid code
        status, error = self.request(unauth_client, 'POST', '/api/login/2fa', {'tempToken': temp_token, 'totpCode': '000000'})
        self.assertEqual(status, 401)

        # Re-login to get fresh tempToken for emergency backup code login
        status, res = self.request(unauth_client, 'POST', '/api/login', {'email': 'user2fa@example.com', 'password': 'user-passphrase-123'})
        self.assertEqual(status, 200)
        temp_token = res['tempToken']

        # Login 2FA with emergency backup code
        status, res = self.request(unauth_client, 'POST', '/api/login/2fa', {'tempToken': temp_token, 'totpCode': backup_code})
        self.assertEqual(status, 200)
        self.assertEqual(res['user']['email'], 'user2fa@example.com')

        # Attempt to reuse the consumed emergency backup code
        status, res = self.request(unauth_client, 'POST', '/api/login', {'email': 'user2fa@example.com', 'password': 'user-passphrase-123'})
        temp_token = res['tempToken']
        status, error = self.request(unauth_client, 'POST', '/api/login/2fa', {'tempToken': temp_token, 'totpCode': backup_code})
        self.assertEqual(status, 401)

        # Login 2FA with valid TOTP code
        status, res = self.request(unauth_client, 'POST', '/api/login', {'email': 'user2fa@example.com', 'password': 'user-passphrase-123'})
        temp_token = res['tempToken']
        valid_code = server.compute_totp_code(secret, counter=int(server.time.time() // 30) + 1)
        status, res = self.request(unauth_client, 'POST', '/api/login/2fa', {'tempToken': temp_token, 'totpCode': valid_code})
        self.assertEqual(status, 200)
        self.assertEqual(res['user']['email'], 'user2fa@example.com')

        # 4. Passkey Registration and Login Flow
        # Test missing public key
        passkey_id = 'test-passkey-id-123'

        status, chal_res = self.request(user_client, 'GET', '/api/login/passkey/challenge')

        status, res = self.request(user_client, 'POST', '/api/account/passkey', {
            'id': passkey_id, 'name': 'My Laptop', 'publicKey': '',
            'authenticatorData': 'YXV0aERhdGE=',
            'clientDataJSON': 'Y2xpZW50RGF0YQ==',
            'attestationObject': 'YXR0ZXN0YXRpb24=',
            'challengeId': chal_res['challengeId']
        })
        self.assertEqual(status, 400)

        status, chal_res2 = self.request(user_client, 'GET', '/api/login/passkey/challenge')

        # Register valid passkey
        with unittest.mock.patch('server.webauthn.verify_registration_response') as mock_reg_verify:
            mock_reg_verify.return_value = unittest.mock.Mock(
                credential_public_key=b'dummy_pub_key',
                sign_count=0
            )
            status, res = self.request(user_client, 'POST', '/api/account/passkey', {
                'id': passkey_id, 'name': 'My Laptop', 'publicKey': 'ZHVtbXk=',
                'authenticatorData': 'YXV0aERhdGE=',
                'clientDataJSON': 'Y2xpZW50RGF0YQ==',
                'attestationObject': 'YXR0ZXN0YXRpb24=',
                'challengeId': chal_res2['challengeId']
            })
            self.assertIn(status, (200, 201))
            self.assertTrue(res.get('added'))

        # Check status
        status, res = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertEqual(status, 200)
        self.assertEqual(len(res['passkeys']), 1)
        self.assertEqual(res['passkeys'][0]['id'], passkey_id)
        self.assertEqual(res['passkeys'][0]['name'], 'My Laptop')

        # Test login via passkey with tempToken (2FA flow)
        status, res = self.request(unauth_client, 'POST', '/api/login', {'email': 'user2fa@example.com', 'password': 'user-passphrase-123'})
        self.assertEqual(status, 200)
        self.assertTrue(res['hasPasskey'])
        temp_token = res['tempToken']

        status, chal_res3 = self.request(unauth_client, 'GET', '/api/login/passkey/challenge')

        with unittest.mock.patch('server.webauthn.verify_authentication_response') as mock_auth_verify:
            mock_auth_verify.return_value = unittest.mock.Mock(new_sign_count=1)
            status, login_res = self.request(unauth_client, 'POST', '/api/login/passkey', {
                'id': passkey_id,
                'authenticatorData': 'YXV0aERhdGE=',
                'clientDataJSON': 'Y2xpZW50RGF0YQ==',
                'signature': 'c2lnbmF0dXJl',
                'challengeId': chal_res3['challengeId'],
                'tempToken': temp_token
            })
            self.assertEqual(status, 200)
            self.assertEqual(login_res['user']['email'], 'user2fa@example.com')

        # Test passwordless login via passkey without tempToken
        passwordless_client = self.new_client()
        status, chal_res4 = self.request(passwordless_client, 'GET', '/api/login/passkey/challenge')

        with unittest.mock.patch('server.webauthn.verify_authentication_response') as mock_auth_verify:
            mock_auth_verify.return_value = unittest.mock.Mock(new_sign_count=2)
            status, login_res = self.request(passwordless_client, 'POST', '/api/login/passkey', {
                'id': passkey_id,
                'authenticatorData': 'YXV0aERhdGE=',
                'clientDataJSON': 'Y2xpZW50RGF0YQ==',
                'signature': 'c2lnbmF0dXJl',
                'challengeId': chal_res4['challengeId']
            })
            self.assertEqual(status, 200)
            self.assertEqual(login_res['user']['email'], 'user2fa@example.com')

        # Delete passkey
        status, res = self.request(user_client, 'DELETE', f'/api/account/passkey/{passkey_id}')
        self.assertEqual(status, 200)

        status, res = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertEqual(res['passkeys'], [])

        # Need to temporarily disable require2FA to allow admin endpoints to work without 2FA
        self.request(self.admin, 'POST', '/api/admin/settings', {'require2FA': False, 'logLevel': 'INFO'})

        # 6. Verify Admin Summary and Admin Reset 2FA
        status, summary = self.request(self.admin, 'GET', '/api/admin/summary')
        self.assertEqual(status, 200)
        target_user = next(u for u in summary['users'] if u['email'] == 'user2fa@example.com')
        self.assertTrue(target_user['has2FA'])

        status, res = self.request(self.admin, 'DELETE', f"/api/admin/users/{target_user['id']}/2fa")
        self.assertEqual(status, 200)
        self.assertEqual(res['reset'], target_user['id'])

        status, summary = self.request(self.admin, 'GET', '/api/admin/summary')
        target_user = next(u for u in summary['users'] if u['email'] == 'user2fa@example.com')
        self.assertFalse(target_user['has2FA'])

        status, _ = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertEqual(status, 401)  # sessions are revoked when 2FA is reset

        # Reset require2FA so it doesn't break subsequent tests that use this admin session
        self.request(self.admin, 'POST', '/api/admin/settings', {'require2FA': False, 'logLevel': 'INFO'})

        # The test expects 200 on password login after all passkeys and TOTP are removed
        unauth_client = self.new_client()
        status, res = self.request(unauth_client, 'POST', '/api/login', {'email': 'user2fa@example.com', 'password': 'user-passphrase-123'})
        self.assertEqual(status, 200)

    @unittest.mock.patch('server.webauthn.verify_registration_response')
    def test_totp_passkey_settings_survive_backup_restore(self, mock_verify):
        mock_verify.return_value = unittest.mock.Mock(
            credential_public_key=b'dummy_pub_key',
            sign_count=0
        )

        user_client = self.register_user('user2fa2@example.com', 'user-passphrase-123')

        # Setup TOTP
        status, res = self.request(user_client, 'POST', '/api/account/totp', {})
        secret = res['secret']
        code = server.compute_totp_code(secret)
        self.request(user_client, 'POST', '/api/account/totp/verify', {'code': code})

        # Register Passkey
        passkey_id = 'test-backup-passkey-id'

        status, chal_res = self.request(user_client, 'GET', '/api/login/passkey/challenge')

        status, res = self.request(user_client, 'POST', '/api/account/passkey', {
            'id': passkey_id, 'name': 'My Laptop', 'publicKey': 'ZHVtbXk=',
            'authenticatorData': 'YXV0aERhdGE=',
            'clientDataJSON': 'Y2xpZW50RGF0YQ==',
            'attestationObject': 'YXR0ZXN0YXRpb24=',
            'challengeId': chal_res['challengeId']
        })
        self.assertTrue(res.get('added'))

        # Change admin settings
        self.request(self.admin, 'POST', '/api/admin/settings', {'require2FA': False, 'logLevel': 'DEBUG'})

        # Create backup
        status, backup = self.request(self.admin, 'POST', '/api/admin/backups', {})
        self.assertEqual(status, 201)

        # Restore backup
        status, restored = self.request(self.admin, 'POST', f"/api/admin/backups/{backup['filename']}/restore", {})
        self.assertEqual(status, 200)
        self.assertEqual(restored.get('passkeys'), 1)
        self.assertEqual(restored.get('settings'), 4)

        # Verify settings restored
        admin_client = self.new_client()
        status, _ = self.request(admin_client, 'POST', '/api/login', {'email': 'admin@example.com', 'password': 'secure-passphrase-1'})
        self.assertEqual(status, 200)
        status, settings = self.request(admin_client, 'GET', '/api/admin/settings')
        self.assertEqual(status, 200)
        self.assertEqual(settings['logLevel'], 'DEBUG')

        # Verify user passkeys and TOTP survived backup/restore
        status, res = self.request(user_client, 'POST', '/api/login', {'email': 'user2fa2@example.com', 'password': 'user-passphrase-123'})
        self.assertEqual(status, 200)
        temp_token = res['tempToken']
        totp_code = server.compute_totp_code(secret)
        status, res = self.request(user_client, 'POST', '/api/login/2fa', {'tempToken': temp_token, 'totpCode': totp_code})
        self.assertEqual(status, 200)

        status, twofa_info = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertEqual(status, 200)
        self.assertTrue(twofa_info['hasTotp'])
        self.assertEqual(len(twofa_info['passkeys']), 1)
        self.assertEqual(twofa_info['passkeys'][0]['id'], passkey_id)
        self.assertEqual(twofa_info['passkeys'][0]['name'], 'My Laptop')

    def test_session_days_and_formatted_backup_code(self):
        # Admin sets custom session days
        status, settings = self.request(self.admin, 'POST', '/api/admin/settings', {'sessionDays': 14})
        self.assertEqual(status, 200)
        self.assertEqual(settings['sessionDays'], 14)

        # Create user with 2FA
        status, invite = self.request(self.admin, 'POST', '/api/admin/invites', {})
        invite_token = parse_qs(urlsplit(invite['url']).query)['invite'][0]
        user_client = self.new_client()
        status, _ = self.request(user_client, 'POST', '/api/register', {
            'email': 'backupcodeuser@example.com', 'password': 'user-passphrase-123', 'invite': invite_token
        })
        self.assertEqual(status, 201)

        # Enable TOTP and get backup codes
        status, res = self.request(user_client, 'POST', '/api/account/totp', {})
        totp_code = server.compute_totp_code(res['secret'])
        status, res = self.request(user_client, 'POST', '/api/account/totp/verify', {'code': totp_code})
        backup_codes = res.get('backupCodes', [])
        self.assertTrue(len(backup_codes) > 0)
        formatted_code = backup_codes[0] # e.g. "2B6E-E77F"

        # Login with formatted backup code containing hyphen
        login_client = self.new_client()
        status, res = self.request(login_client, 'POST', '/api/login', {'email': 'backupcodeuser@example.com', 'password': 'user-passphrase-123'})
        self.assertTrue(res.get('requires2FA'))
        temp_token = res['tempToken']

        status, res = self.request(login_client, 'POST', '/api/login/2fa', {'tempToken': temp_token, 'totpCode': formatted_code.lower()})
        self.assertEqual(status, 200)
        self.assertEqual(res['user']['email'], 'backupcodeuser@example.com')


    def test_archived_or_deleted_notes_cannot_be_pinned(self):
        user = self.register_user('pin-test@example.com')
        note_archived_pinned = self.note_payload('note-1', 'Archived & Pinned')
        note_archived_pinned['pinned'] = True
        note_archived_pinned['archived'] = True

        note_deleted_pinned = self.note_payload('note-2', 'Deleted & Pinned')
        note_deleted_pinned['pinned'] = True
        note_deleted_pinned['deleted'] = True

        note_active_pinned = self.note_payload('note-3', 'Active & Pinned')
        note_active_pinned['pinned'] = True

        status, _ = self.request(user, 'PUT', '/api/notes', {
            'notes': [note_archived_pinned, note_deleted_pinned, note_active_pinned]
        })
        self.assertEqual(status, 200)

        status, result = self.request(user, 'GET', '/api/notes')
        self.assertEqual(status, 200)

        notes_by_id = {n['id']: n for n in result['notes']}
        self.assertFalse(notes_by_id['note-1']['pinned'])
        self.assertTrue(notes_by_id['note-1']['archived'])
        self.assertFalse(notes_by_id['note-2']['pinned'])
        self.assertTrue(notes_by_id['note-2']['deleted'])
        self.assertTrue(notes_by_id['note-3']['pinned'])

    def test_reverse_proxy_and_https_headers(self):
        # Test check_origin accepts matching X-Forwarded-Host
        status, _ = self.request(
            self.admin, 'POST', '/api/admin/invites', {},
            headers={'Origin': 'https://notes.example.com', 'X-Forwarded-Host': 'notes.example.com', 'X-Forwarded-Proto': 'https'}
        )
        self.assertEqual(status, 201)

        # Test check_origin rejects mismatched Origin vs X-Forwarded-Host
        status, error = self.request(
            self.admin, 'POST', '/api/admin/invites', {},
            headers={'Origin': 'https://evil.example.com', 'X-Forwarded-Host': 'notes.example.com'}
        )
        self.assertEqual(status, 403)
        self.assertIn('blocked', error['error'].lower())

        # Test invite URL generation with X-Forwarded-Host and X-Forwarded-Proto
        status, invite = self.request(
            self.admin, 'POST', '/api/admin/invites', {},
            headers={'Origin': 'https://notki.cloudflare.net', 'X-Forwarded-Host': 'notki.cloudflare.net', 'X-Forwarded-Proto': 'https'}
        )
        self.assertEqual(status, 201)
        self.assertTrue(invite['url'].startswith('https://notki.cloudflare.net/?invite='))

        # Test session cookie sets Secure when X-Forwarded-Proto is https
        client = self.new_client()
        req_data = json.dumps({'email': 'admin@example.com', 'password': 'secure-passphrase-1'}).encode('utf-8')
        request = Request(
            self.base_url + '/api/login',
            data=req_data,
            headers=with_same_origin(self.base_url, {'Content-Type': 'application/json', 'X-Forwarded-Proto': 'https'}),
            method='POST'
        )
        with client.open(request) as response:
            set_cookie = response.headers.get('Set-Cookie', '')
            self.assertIn('Secure', set_cookie)
            self.assertIn('SameSite=Strict', set_cookie)

        # Test alternative HTTPS proxy headers (X-Forwarded-Ssl, multi-proxy X-Forwarded-Proto)
        status, invite = self.request(
            self.admin, 'POST', '/api/admin/invites', {},
            headers={'X-Forwarded-Host': 'notki.local', 'X-Forwarded-Ssl': 'on'}
        )
        self.assertEqual(status, 201)
        self.assertTrue(invite['url'].startswith('https://notki.local/?invite='))

        status, invite = self.request(
            self.admin, 'POST', '/api/admin/invites', {},
            headers={'X-Forwarded-Host': 'notki.multi.proxy', 'X-Forwarded-Proto': 'https, http'}
        )
        self.assertEqual(status, 201)
        self.assertTrue(invite['url'].startswith('https://notki.multi.proxy/?invite='))

    def test_session_cookie_flags(self):
        # Test session cookie under plain HTTP without NOTKI_COOKIE_SECURE
        client = self.new_client()
        req_data = json.dumps({'email': 'admin@example.com', 'password': 'secure-passphrase-1'}).encode('utf-8')
        request = Request(
            self.base_url + '/api/login',
            data=req_data,
            headers=with_same_origin(self.base_url, {'Content-Type': 'application/json'}),
            method='POST'
        )
        with client.open(request) as response:
            set_cookie = response.headers.get('Set-Cookie', '')
            self.assertIn('HttpOnly', set_cookie)
            self.assertIn('SameSite=Strict', set_cookie)
            self.assertNotIn('Secure', set_cookie)

        # Test session cookie with NOTKI_COOKIE_SECURE=1 env var override
        try:
            os.environ['NOTKI_COOKIE_SECURE'] = '1'
            client = self.new_client()
            request = Request(
                self.base_url + '/api/login',
                data=req_data,
                headers=with_same_origin(self.base_url, {'Content-Type': 'application/json'}),
                method='POST'
            )
            with client.open(request) as response:
                set_cookie = response.headers.get('Set-Cookie', '')
                self.assertIn('Secure', set_cookie)
                self.assertIn('HttpOnly', set_cookie)
                self.assertIn('SameSite=Strict', set_cookie)
        finally:
            os.environ.pop('NOTKI_COOKIE_SECURE', None)

    def test_disable_user_2fa_cli(self):
        user_client = self.register_user('cli2fa@example.com', 'user-passphrase-123')
        # Setup 2FA (TOTP and Passkey) for user
        status, res = self.request(user_client, 'POST', '/api/account/totp')
        secret = res['secret']
        code = server.compute_totp_code(secret)
        self.request(user_client, 'POST', '/api/account/totp/verify', {'code': code})

        # Insert dummy passkey directly into DB
        with server.database() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = 'cli2fa@example.com'").fetchone()
            user_id = user_row['id']
            conn.execute('INSERT INTO passkeys (id, user_id, name, public_key_pem, created_at, sign_count) VALUES (?, ?, ?, ?, ?, ?)', ('pk-123', user_id, 'My Key', 'pem', '2026-01-01T00:00:00Z', 0))

        status, twofa_info = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertTrue(twofa_info['hasTotp'])
        self.assertEqual(len(twofa_info['passkeys']), 1)

        # Disable 2FA via CLI using email
        server.disable_user_2fa_cli('cli2fa@example.com')

        status, twofa_info = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertFalse(twofa_info['hasTotp'])
        self.assertEqual(len(twofa_info['passkeys']), 0)

        # Re-enable TOTP
        status, res = self.request(user_client, 'POST', '/api/account/totp')
        secret = res['secret']
        code = server.compute_totp_code(secret)
        self.request(user_client, 'POST', '/api/account/totp/verify', {'code': code})

        status, twofa_info = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertTrue(twofa_info['hasTotp'])

        # Get user ID
        with server.database() as conn:
            user_row = conn.execute("SELECT id FROM users WHERE email = 'cli2fa@example.com'").fetchone()
            user_id = user_row['id']

        # Disable 2FA via CLI using user ID
        server.disable_user_2fa_cli(str(user_id))

        status, twofa_info = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertFalse(twofa_info['hasTotp'])

        # Test empty input handling
        with self.assertRaises(SystemExit):
            server.disable_user_2fa_cli('   ')

        # Test non-existent user handling
        with self.assertRaises(SystemExit):
            server.disable_user_2fa_cli('nonexistent@example.com')

    def test_disable_all_2fa_cli(self):
        user1 = self.register_user('u1@example.com', 'passphrase-123-abc')
        user2 = self.register_user('u2@example.com', 'passphrase-123-xyz')

        # Enable TOTP for user 1
        status, res = self.request(user1, 'POST', '/api/account/totp')
        code1 = server.compute_totp_code(res['secret'])
        self.request(user1, 'POST', '/api/account/totp/verify', {'code': code1})

        # Enable TOTP for user 2
        status, res = self.request(user2, 'POST', '/api/account/totp')
        code2 = server.compute_totp_code(res['secret'])
        self.request(user2, 'POST', '/api/account/totp/verify', {'code': code2})

        # Insert dummy passkeys and set require2FA in DB
        with server.database() as conn:
            u1_row = conn.execute("SELECT id FROM users WHERE email = 'u1@example.com'").fetchone()
            u2_row = conn.execute("SELECT id FROM users WHERE email = 'u2@example.com'").fetchone()
            conn.execute('INSERT INTO passkeys (id, user_id, name, public_key_pem, created_at, sign_count) VALUES (?, ?, ?, ?, ?, ?)', ('pk-u1', u1_row['id'], 'Key 1', 'pem', '2026-01-01T00:00:00Z', 0))
            conn.execute('INSERT INTO passkeys (id, user_id, name, public_key_pem, created_at, sign_count) VALUES (?, ?, ?, ?, ?, ?)', ('pk-u2', u2_row['id'], 'Key 2', 'pem', '2026-01-01T00:00:00Z', 0))
            conn.execute("INSERT INTO settings (key, value) VALUES ('require2FA', 'true') ON CONFLICT(key) DO UPDATE SET value = 'true'")

        # Create a temp token
        server.create_temp_2fa_token(u1_row['id'])
        self.assertGreater(len(server.TEMP_2FA_TOKENS), 0)

        # Call disable_all_2fa_cli
        server.disable_all_2fa_cli()

        # Check user 1
        status, info1 = self.request(user1, 'GET', '/api/account/2fa')
        self.assertFalse(info1['hasTotp'])
        self.assertEqual(len(info1['passkeys']), 0)

        # Check user 2
        status, info2 = self.request(user2, 'GET', '/api/account/2fa')
        self.assertFalse(info2['hasTotp'])
        self.assertEqual(len(info2['passkeys']), 0)

        # Check require2FA setting in DB
        with server.database() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = 'require2FA'").fetchone()
            self.assertEqual(row['value'], 'false')

        # Check temp tokens cleared
        self.assertEqual(len(server.TEMP_2FA_TOKENS), 0)

        # Test CLI invocation via main()
        with unittest.mock.patch('sys.argv', ['server.py', '--disable-all-2fa']):
            server.main()

    def test_passkey_challenges_are_bounded(self):
        original_limit = server.MAX_PASSKEY_CHALLENGES
        server.MAX_PASSKEY_CHALLENGES = 3
        try:
            with server.PASSKEY_CHALLENGES_LOCK:
                server.PASSKEY_CHALLENGES.clear()
            challenge_ids = []
            for _ in range(10):
                challenge_ids.append(server.generate_passkey_challenge()['challengeId'])
            with server.PASSKEY_CHALLENGES_LOCK:
                self.assertLessEqual(len(server.PASSKEY_CHALLENGES), 3)
                self.assertIn(challenge_ids[-1], server.PASSKEY_CHALLENGES)
                self.assertNotIn(challenge_ids[0], server.PASSKEY_CHALLENGES)
        finally:
            server.MAX_PASSKEY_CHALLENGES = original_limit
            with server.PASSKEY_CHALLENGES_LOCK:
                server.PASSKEY_CHALLENGES.clear()

    def test_temp_2fa_tokens_are_bounded(self):
        original_limit = server.MAX_TEMP_2FA_TOKENS
        server.MAX_TEMP_2FA_TOKENS = 3
        try:
            with server.TEMP_2FA_LOCK:
                server.TEMP_2FA_TOKENS.clear()
            tokens = [server.create_temp_2fa_token(1) for _ in range(10)]
            with server.TEMP_2FA_LOCK:
                self.assertLessEqual(len(server.TEMP_2FA_TOKENS), 3)
                self.assertIn(tokens[-1], server.TEMP_2FA_TOKENS)
                self.assertNotIn(tokens[0], server.TEMP_2FA_TOKENS)
        finally:
            server.MAX_TEMP_2FA_TOKENS = original_limit
            with server.TEMP_2FA_LOCK:
                server.TEMP_2FA_TOKENS.clear()

    def test_clear_failed_auth_resets_counter(self):
        ip = '203.0.113.77'
        server.unban_ip(ip)
        for _ in range(15):
            server.record_failed_auth(ip)
        self.assertTrue(server.is_rate_limited(ip))
        server.clear_failed_auth(ip)
        self.assertFalse(server.is_rate_limited(ip))
        self.assertEqual([item for item in server.get_banned_ips() if item['ip'] == ip], [])

    def test_successful_login_clears_failed_attempts(self):
        ip = '127.0.0.1'
        client = self.new_client()
        for _ in range(2):
            status, _ = self.request(client, 'POST', '/api/login', {
                'email': 'admin@example.com', 'password': 'wrong-password',
            })
            self.assertEqual(status, 401)
        self.assertEqual(len(server.FAILED_AUTH_ATTEMPTS.get(ip, [])), 2)

        status, _ = self.request(client, 'POST', '/api/login', {
            'email': 'admin@example.com', 'password': 'secure-passphrase-1',
        })
        self.assertEqual(status, 200)
        self.assertFalse(server.is_rate_limited(ip))
        # A successful login clears the account-specific failures but deliberately
        # keeps the per-IP budget so an attacker cannot reset it with another login.
        self.assertNotIn(('127.0.0.1', 'admin@example.com'), server.FAILED_AUTH_ACCOUNTS)
        self.assertFalse(server.is_account_rate_limited('admin@example.com'))
        self.assertEqual(len(server.FAILED_AUTH_ATTEMPTS.get(ip, [])), 2)
        self.assertFalse(next(item for item in server.get_banned_ips() if item['ip'] == ip)['isBanned'])

    def test_invite_validity_days_are_bounded(self):
        from datetime import datetime

        status, invite = self.request(self.admin, 'POST', '/api/admin/invites', {'days': 10 ** 9})
        self.assertEqual(status, 201)
        expires = datetime.fromisoformat(invite['expiresAt'])
        self.assertLessEqual((expires - server.utc_now()).days, 3650)

        for value in ('abc', None, -5):
            status, invite = self.request(self.admin, 'POST', '/api/admin/invites', {'days': value})
            self.assertEqual(status, 201)
            self.assertIn('url', invite)


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

    def request_raw(self, method, path, body, content_type='application/gzip'):
        request = Request(
            self.base_url + path,
            data=body,
            headers=with_same_origin(self.base_url, {'Content-Type': content_type}),
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

    def test_server_snapshot_import_restores_accounts_notes_and_invites(self):
        created_at = server.iso_time()
        invite_token = 'invitation-token-from-snapshot'
        snapshot = {
            'format': 'notki-server-snapshot',
            'version': 1,
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
        status, _ = self.request('POST', '/api/setup/import', {'snapshot': snapshot}, {'Host': 'external.example'})
        self.assertEqual(status, 403)

        status, result = self.request('POST', '/api/setup/import', {'snapshot': snapshot})
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

        status, _ = self.request('POST', '/api/setup/import', {'snapshot': snapshot})
        self.assertEqual(status, 409)

    def test_tgz_backup_import_is_available_on_fresh_server(self):
        created_at = server.iso_time()
        snapshot = {
            'format': 'notki-server-snapshot', 'version': 1, 'createdAt': created_at,
            'users': [{
                'id': 1, 'email': 'archive-admin@example.com',
                'passwordHash': server.hash_password('archive-admin-password'),
                'role': 'admin', 'createdAt': created_at,
            }],
            'notes': [], 'invites': [],
        }
        snapshot_bytes = json.dumps(snapshot).encode('utf-8')
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode='w:gz') as archive:
            member = tarfile.TarInfo('snapshot.json')
            member.size = len(snapshot_bytes)
            archive.addfile(member, io.BytesIO(snapshot_bytes))

        status, result = self.request_raw('POST', '/api/setup/import-backup', archive_bytes.getvalue())
        self.assertEqual(status, 201)
        self.assertTrue(result['imported'])
        status, login = self.request('POST', '/api/login', {
            'email': 'archive-admin@example.com', 'password': 'archive-admin-password',
        })
        self.assertEqual(status, 200)
        self.assertTrue(login['user']['isAdmin'])

    def test_snapshot_import_with_subpath_or_mac_metadata(self):
        created_at = server.iso_time()
        snapshot = {
            'format': 'notki-server-snapshot', 'version': 1, 'createdAt': created_at,
            'users': [{
                'id': 1, 'email': 'mac-admin@example.com',
                'passwordHash': server.hash_password('mac-admin-password'),
                'role': 'admin', 'createdAt': created_at,
            }],
            'notes': [], 'invites': [],
        }
        snapshot_bytes = json.dumps(snapshot).encode('utf-8')
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode='w:gz') as archive:
            # Add macOS hidden file
            mac_meta = tarfile.TarInfo('._snapshot.json')
            mac_meta.size = 10
            archive.addfile(mac_meta, io.BytesIO(b'apple-meta'))
            # Add snapshot file with leading ./
            member = tarfile.TarInfo('./snapshot.json')
            member.size = len(snapshot_bytes)
            archive.addfile(member, io.BytesIO(snapshot_bytes))

        status, result = self.request_raw('POST', '/api/setup/import-backup', archive_bytes.getvalue())
        self.assertEqual(status, 201)
        self.assertTrue(result['imported'])

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
            'Content-Length': str(server.MAX_SNAPSHOT_BYTES + 1)
        }
        rfile = io.BytesIO(b'')
        handler = DummyHandler(headers, rfile)
        with self.assertRaises(server.APIError) as cm:
            handler.read_archive_from_request()
        self.assertEqual(cm.exception.status, 413)
        self.assertEqual(str(cm.exception), 'The backup file exceeds the size limit.')


class PerformUpdateHelperTests(unittest.TestCase):
    def setUp(self):
        # Create a mock connection and request to avoid AttributeError in socketserver setup
        mock_request = unittest.mock.MagicMock()
        mock_client_address = ('127.0.0.1', 12345)
        mock_server = unittest.mock.MagicMock()

        # We subclass to bypass the __init__ of BaseHTTPRequestHandler which calls setup()
        class DummyHandler(server.NotkiHandler):
            def __init__(self):
                pass

        self.handler = DummyHandler()

    @unittest.mock.patch('server.urllib.request.build_opener')
    def test_download_update_archive_success(self, mock_build_opener):
        mock_opener = unittest.mock.MagicMock()
        mock_response = unittest.mock.MagicMock()
        mock_response.read.return_value = b'archive_data'
        mock_opener.open.return_value.__enter__.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        result = self.handler._download_update_archive('http://example.com/tarball')
        self.assertEqual(result, b'archive_data')

    @unittest.mock.patch('server.urllib.request.build_opener')
    def test_download_update_archive_error(self, mock_build_opener):
        mock_opener = unittest.mock.MagicMock()
        mock_opener.open.side_effect = Exception("Network error")
        mock_build_opener.return_value = mock_opener

        with self.assertRaises(server.APIError) as cm:
            self.handler._download_update_archive('http://example.com/tarball')
        self.assertEqual(cm.exception.status, 500)
        self.assertEqual(cm.exception.args[0], 'An error occurred while downloading the archive.')

    def test_download_update_archive_invalid_redirect(self):
        # We need to capture the redirect handler created in the method
        # and verify it raises URLError on invalid redirect URLs.
        import urllib.error

        captured_handler = None
        original_build_opener = server.urllib.request.build_opener

        def mock_build_opener(handler):
            nonlocal captured_handler
            captured_handler = handler
            # Return a dummy opener that will just raise an exception to exit early
            dummy_opener = unittest.mock.MagicMock()
            dummy_opener.open.side_effect = Exception("Stop execution")
            return dummy_opener

        with unittest.mock.patch('server.urllib.request.build_opener', side_effect=mock_build_opener):
            try:
                self.handler._download_update_archive('http://example.com/tarball')
            except server.APIError:
                pass

        self.assertIsNotNone(captured_handler)

        # Test valid redirect
        valid_url = 'https://codeload.github.com/shirou93/Notki/zip'
        # The base class method is called, but we mock it for the test
        with unittest.mock.patch('urllib.request.HTTPRedirectHandler.redirect_request', return_value='success'):
            self.assertEqual(captured_handler.redirect_request(None, None, None, None, None, valid_url), 'success')

        # Test invalid redirect
        invalid_url = 'https://malicious.com/zip'
        with self.assertRaises(urllib.error.URLError) as cm:
            captured_handler.redirect_request(None, None, None, None, None, invalid_url)
        self.assertEqual(str(cm.exception), '<urlopen error Invalid redirect URL.>')

    def test_verify_update_version_success(self):
        mock_archive = unittest.mock.MagicMock()
        mock_member = unittest.mock.MagicMock()
        mock_member.name = 'Notki-master/server.py'

        mock_extracted_file = unittest.mock.MagicMock()
        # Set a version higher than current VERSION to pass validation
        future_version = '99.99.99'
        mock_extracted_file.read.return_value = f"VERSION = '{future_version}'".encode('utf-8')
        mock_archive.extractfile.return_value = mock_extracted_file

        # Should not raise
        self.handler._verify_update_version(mock_archive, [mock_member])

    def test_verify_update_version_no_newer_version(self):
        mock_archive = unittest.mock.MagicMock()
        mock_member = unittest.mock.MagicMock()
        mock_member.name = 'Notki-master/server.py'

        mock_extracted_file = unittest.mock.MagicMock()
        # Set a version equal or lower than current VERSION to trigger error
        mock_extracted_file.read.return_value = f"VERSION = '{server.VERSION}'".encode('utf-8')
        mock_archive.extractfile.return_value = mock_extracted_file

        with self.assertRaises(server.APIError) as cm:
            self.handler._verify_update_version(mock_archive, [mock_member])
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(cm.exception.args[0], 'No newer version available.')

    @unittest.mock.patch('server.ROOT')
    @unittest.mock.patch('server.tarfile')
    def test_extract_update_archive(self, mock_tarfile, mock_root):
        mock_archive = unittest.mock.MagicMock()

        mock_member1 = unittest.mock.MagicMock()
        mock_member1.name = 'Notki-master/file1.py'
        mock_member1.isreg.return_value = True
        mock_member1.isdir.return_value = False

        mock_member2 = unittest.mock.MagicMock()
        mock_member2.name = 'Notki-master/'
        mock_member2.isreg.return_value = False
        mock_member2.isdir.return_value = True

        # Test path traversal prevention
        mock_member3 = unittest.mock.MagicMock()
        mock_member3.name = 'Notki-master/../etc/passwd'
        mock_member3.isreg.return_value = True
        mock_member3.isdir.return_value = False

        # Test absolute path / leading slash prevention
        mock_member4 = unittest.mock.MagicMock()
        mock_member4.name = 'Notki-master//etc/passwd'
        mock_member4.isreg.return_value = True
        mock_member4.isdir.return_value = False

        # Test symlink prevention
        mock_member5 = unittest.mock.MagicMock()
        mock_member5.name = 'Notki-master/symlink_file'
        mock_member5.isreg.return_value = False
        mock_member5.isdir.return_value = False

        members = [mock_member1, mock_member2, mock_member3, mock_member4, mock_member5]

        mock_target_path = unittest.mock.MagicMock()
        mock_target_path.is_relative_to.return_value = True
        mock_root.resolve.return_value = mock_root
        mock_root.__truediv__.return_value.resolve.return_value = mock_target_path

        mock_tarfile.data_filter = True # Simulate Python 3.12+

        self.handler._extract_update_archive(mock_archive, members)

        # Should extract file1.py with filter='data'
        self.assertEqual(mock_member1.name, 'file1.py')
        mock_archive.extract.assert_called_once_with(mock_member1, path=mock_root, filter='data')

    @unittest.mock.patch('server.ROOT')
    def test_extract_update_archive_without_data_filter(self, mock_root):
        mock_archive = unittest.mock.MagicMock()

        mock_member = unittest.mock.MagicMock()
        mock_member.name = 'Notki-master/app.js'
        mock_member.isreg.return_value = True
        mock_member.isdir.return_value = False

        mock_target_path = unittest.mock.MagicMock()
        mock_target_path.is_relative_to.return_value = True
        mock_root.resolve.return_value = mock_root
        mock_root.__truediv__.return_value.resolve.return_value = mock_target_path

        with unittest.mock.patch('server.tarfile', spec=[]):
            self.handler._extract_update_archive(mock_archive, [mock_member])

        self.assertEqual(mock_member.name, 'app.js')
        mock_archive.extract.assert_called_once_with(mock_member, path=mock_root)


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


class IsRateLimitedTests(unittest.TestCase):
    def setUp(self):
        server.FAILED_AUTH_ATTEMPTS.clear()

    def tearDown(self):
        server.FAILED_AUTH_ATTEMPTS.clear()

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

        # At t=1060.0 (60 seconds later, 1060.0 - 1000.0 = 60, not < 60), attempts expire
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


class TestGenerateTOTPSecret(unittest.TestCase):
    def test_generate_totp_secret_properties(self):
        secret = server.generate_totp_secret()
        self.assertIsInstance(secret, str)
        self.assertEqual(len(secret), 16)
        valid_alphabet = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567')
        self.assertTrue(set(secret).issubset(valid_alphabet))

    def test_generate_totp_secret_uniqueness(self):
        secrets_set = {server.generate_totp_secret() for _ in range(20)}
        self.assertEqual(len(secrets_set), 20)


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

    def test_create_server_backup_uses_named_temp_file(self):
        class DummyHandler(server.NotkiHandler):
            def __init__(self):
                self.user = {'id': 1, 'role': 'admin', 'isAdmin': True}
                self.response_body = None
                self.response_status = None

            def current_user(self):
                return self.user

            def send_json(self, data, status=200):
                self.response_body = data
                self.response_status = status

        handler = DummyHandler()
        handler.require_step_up = lambda user: None
        original_named_temp_file = tempfile.NamedTemporaryFile
        temp_files_created = []

        def mock_named_temp_file(*args, **kwargs):
            tf = original_named_temp_file(*args, **kwargs)
            temp_files_created.append(tf.name)
            return tf

        with unittest.mock.patch('tempfile.NamedTemporaryFile', side_effect=mock_named_temp_file):
            handler.create_server_backup()

        self.assertEqual(handler.response_status, 201)
        self.assertEqual(len(temp_files_created), 1)
        created_backup = self.backup_dir / handler.response_body['filename']
        self.assertTrue(created_backup.exists())
        self.assertFalse(os.path.exists(temp_files_created[0]))


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
        mock_connection.execute.return_value.fetchall.return_value = []
        config = server.get_fail2ban_config()
        self.assertEqual(config, {'enabled': True, 'max_attempts': 15, 'ban_time': 60})

        # Test 2: Custom configuration when database returns values
        mock_connection.execute.return_value.fetchall.return_value = [
            {'key': 'fail2banEnabled', 'value': 'false'},
            {'key': 'fail2banMaxAttempts', 'value': '5'},
            {'key': 'fail2banBanTime', 'value': '120'}
        ]
        config = server.get_fail2ban_config()
        self.assertEqual(config, {'enabled': False, 'max_attempts': 5, 'ban_time': 120})

        # Test 3: Exception during database operation falls back to default configuration
        mock_connection.execute.side_effect = Exception("DB error")
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

    def test_totp_secret_is_encrypted_at_rest(self):
        user = self.register_user('encryptedtotp@example.com', 'user-passphrase-123')
        status, res = self.request(user, 'POST', '/api/account/totp')
        self.assertEqual(status, 200)
        code = server.compute_totp_code(res['secret'])
        status, _ = self.request(user, 'POST', '/api/account/totp/verify', {'code': code})
        self.assertEqual(status, 200)

        with server.database() as connection:
            stored = connection.execute(
                "SELECT totp_secret FROM users WHERE email = 'encryptedtotp@example.com'"
            ).fetchone()['totp_secret']
        self.assertTrue(stored.startswith('enc:v1:'))
        self.assertNotIn(res['secret'], stored)
        self.assertEqual(server.reveal_totp_secret(stored), res['secret'])

    def test_legacy_plaintext_totp_secret_is_migrated(self):
        user = self.register_user('legacytotp@example.com', 'user-passphrase-123')
        secret = server.generate_totp_secret()
        with server.database() as connection:
            connection.execute(
                "UPDATE users SET totp_secret = ? WHERE email = 'legacytotp@example.com'",
                (secret,),
            )
        server.initialize_database()
        with server.database() as connection:
            stored = connection.execute(
                "SELECT totp_secret FROM users WHERE email = 'legacytotp@example.com'"
            ).fetchone()['totp_secret']
        self.assertTrue(stored.startswith('enc:v1:'))
        self.assertEqual(server.reveal_totp_secret(stored), secret)

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

    def test_update_signature_is_verified_when_configured(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization

        private_key = Ed25519PrivateKey.generate()
        public_raw = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        payload_bytes = b'update-archive'
        signature = private_key.sign(payload_bytes)
        handler = server.NotkiHandler

        with unittest.mock.patch.dict(os.environ, {
            'NOTKI_UPDATE_PUBLIC_KEY': base64.b64encode(public_raw).decode('ascii'),
        }):
            handler._verify_update_signature(payload_bytes, {
                'signature': base64.b64encode(signature).decode('ascii'),
            })
            with self.assertRaises(server.APIError):
                handler._verify_update_signature(payload_bytes + b'x', {
                    'signature': base64.b64encode(signature).decode('ascii'),
                })
            with self.assertRaises(server.APIError):
                handler._verify_update_signature(payload_bytes, {})

    def test_csp_and_hsts_headers(self):
        status, res, headers = self.request_with_response_headers(self.admin, 'GET', '/api/admin/settings')
        self.assertEqual(status, 200)
        csp = headers.get('Content-Security-Policy', '')
        self.assertIn("object-src 'none'", csp)
        self.assertIn("base-uri 'none'", csp)
        self.assertNotIn('Strict-Transport-Security', headers)


if __name__ == '__main__':
    unittest.main()
