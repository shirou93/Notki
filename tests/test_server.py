import base64
import hashlib
import os
import http.cookiejar
import io
import json
import subprocess
import tarfile
import tempfile
import threading
import unittest
import unittest.mock
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import server


class ServerUnitTests(unittest.TestCase):
    def test_normalize_email_valid(self):
        self.assertEqual(server.normalize_email('user@example.com'), 'user@example.com')
        self.assertEqual(server.normalize_email('  user@example.com  '), 'user@example.com')
        self.assertEqual(server.normalize_email('USER@EXAMPLE.COM'), 'user@example.com')
        self.assertEqual(server.normalize_email('u.ser+tag@sub.example.co.uk'), 'u.ser+tag@sub.example.co.uk')

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
            headers={'Content-Type': content_type},
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

    def request(self, client, method, path, payload=None, headers=None):
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            headers={'Content-Type': 'application/json', **(headers or {})},
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

        status, error = self.request(owner, 'POST', '/api/notes/mine-1/shares', {'email': 'nobody@example.com', 'permission': 'read'})
        self.assertEqual(status, 404)

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
        self.assertRegex(backup['filename'], r'^notki-backup-\d{8}-\d{6}Z-[a-f0-9]{8}\.json$')
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
        status, _ = self.request(self.admin, 'POST', '/api/account/totp')
        self.assertEqual(status, 200)

        # 15 failed attempts should return 400
        for _ in range(15):
            status, _ = self.request(self.admin, 'POST', '/api/account/totp/verify', {
                'code': '000000'
            })
            self.assertEqual(status, 400)

        # The 16th attempt should be rate limited and return 429
        status, _ = self.request(self.admin, 'POST', '/api/account/totp/verify', {
            'code': '000000'
        })
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
            self.assertIn("frame-ancestors 'none'", response.headers.get('Content-Security-Policy', ''))

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
        tags_response = json.dumps([{'name': '0.1.6.0', 'tarball_url': 'https://api.github.com/repos/shirou93/Notki/tarball/v0.1.6.0'}]).encode('utf-8')
        with unittest.mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_cm = unittest.mock.MagicMock()
            mock_cm.__enter__.return_value.read.return_value = tags_response
            mock_urlopen.return_value = mock_cm

            status, res = self.request(self.admin, 'GET', '/api/admin/update/check')
            self.assertEqual(status, 200)
            self.assertTrue(res.get('updateAvailable', False))
            self.assertEqual(res.get('latestVersion'), '0.1.6.0')

        # Test check update with same tag
        tags_response_same = json.dumps([{'name': '0.1.5.89', 'tarball_url': 'https://api.github.com/repos/shirou93/Notki/tarball/v0.1.5.89'}]).encode('utf-8')
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

            status, res = self.request(self.admin, 'POST', '/api/admin/update/perform', {
                'tarballUrl': 'https://api.github.com/repos/shirou93/Notki/tarball/v0.1.5.89'
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
             unittest.mock.patch('pathlib.Path.read_text', return_value='<span class="sidebar-version">NOTKI · ALPHA 0.1.5.89</span>'), \
             unittest.mock.patch('pathlib.Path.write_text') as mock_write:
            server.NotkiHandler._finalize_update_index_html(dummy_handler, is_beta=True)
            mock_write.assert_called_once_with('<span class="sidebar-version">NOTKI · BETA 0.1.5.89</span>', encoding='utf-8')

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

        # Admin POST settings
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
        self.assertEqual(notes_info.get('announcement'), 'Patching in progress...')

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
        valid_code = server.compute_totp_code(secret)
        status, res = self.request(unauth_client, 'POST', '/api/login/2fa', {'tempToken': temp_token, 'totpCode': valid_code})
        self.assertEqual(status, 200)
        self.assertEqual(res['user']['email'], 'user2fa@example.com')

        # 4. Passkey Registration and Login Flow
        # Test missing public key
        passkey_id = 'test-passkey-id-123'
        status, res = self.request(user_client, 'POST', '/api/account/passkey', {
            'id': passkey_id, 'name': 'My Laptop', 'publicKey': ''
        })
        self.assertEqual(status, 400)

        # Generate EC key pair for passkey test
        with tempfile.NamedTemporaryFile('wb', delete=False) as key_file:
            key_path = key_file.name

        subprocess.run(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', key_path], check=True)
        spki_der = subprocess.run(['openssl', 'ec', '-in', key_path, '-pubout', '-outform', 'DER'], capture_output=True, check=True).stdout
        pub_b64 = base64.b64encode(spki_der).decode('utf-8')

        # Register valid passkey
        status, res = self.request(user_client, 'POST', '/api/account/passkey', {
            'id': passkey_id, 'name': 'My Laptop', 'publicKey': pub_b64
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

        auth_data = b'authenticator_data_32bytes_sample_padding_1234567890'
        client_data = b'{"type":"webauthn.get","challenge":""}'
        client_hash = hashlib.sha256(client_data).digest()
        signed_data = auth_data + client_hash

        with tempfile.NamedTemporaryFile('wb', delete=False) as data_file:
            data_file.write(signed_data)
            data_file_path = data_file.name

        sig_der = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', key_path, data_file_path], capture_output=True, check=True).stdout

        status, res = self.request(unauth_client, 'POST', '/api/login/passkey', {
            'tempToken': temp_token,
            'id': passkey_id,
            'authenticatorData': base64.b64encode(auth_data).decode('utf-8'),
            'clientDataJSON': base64.b64encode(client_data).decode('utf-8'),
            'signature': base64.b64encode(sig_der).decode('utf-8')
        })
        self.assertEqual(status, 200)
        self.assertEqual(res['user']['email'], 'user2fa@example.com')

        # Test passwordless login via passkey without tempToken
        passwordless_client = self.new_client()
        status, res = self.request(passwordless_client, 'POST', '/api/login/passkey', {
            'id': passkey_id,
            'authenticatorData': base64.b64encode(auth_data).decode('utf-8'),
            'clientDataJSON': base64.b64encode(client_data).decode('utf-8'),
            'signature': base64.b64encode(sig_der).decode('utf-8')
        })
        self.assertEqual(status, 200)
        self.assertEqual(res['user']['email'], 'user2fa@example.com')

        # Delete passkey
        status, res = self.request(user_client, 'DELETE', f'/api/account/passkey/{passkey_id}')
        self.assertEqual(status, 200)

        status, res = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertEqual(res['passkeys'], [])

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

        status, res = self.request(user_client, 'GET', '/api/account/2fa')
        self.assertFalse(res['hasTotp'])
        self.assertEqual(res['passkeys'], [])

    def test_totp_passkey_settings_survive_backup_restore(self):
        user_client = self.register_user('user2fa2@example.com', 'user-passphrase-123')

        # Setup TOTP
        status, res = self.request(user_client, 'POST', '/api/account/totp', {})
        secret = res['secret']
        code = server.compute_totp_code(secret)
        self.request(user_client, 'POST', '/api/account/totp/verify', {'code': code})

        # Register Passkey
        passkey_id = 'test-backup-passkey-id'
        with tempfile.NamedTemporaryFile('wb', delete=False) as key_file:
            key_path = key_file.name
        try:
            subprocess.run(['openssl', 'ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-out', key_path], check=True)
            spki_der = subprocess.run(['openssl', 'ec', '-in', key_path, '-pubout', '-outform', 'DER'], capture_output=True, check=True).stdout
            pub_b64 = base64.b64encode(spki_der).decode('utf-8')
            status, res = self.request(user_client, 'POST', '/api/account/passkey', {
                'id': passkey_id, 'name': 'My Laptop', 'publicKey': pub_b64
            })
            self.assertTrue(res.get('added'))
        finally:
            os.unlink(key_path)

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
            headers={'Origin': 'https://notes.example.com', 'X-Forwarded-Host': 'notes.example.com'}
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
            headers={'X-Forwarded-Host': 'notki.cloudflare.net', 'X-Forwarded-Proto': 'https'}
        )
        self.assertEqual(status, 201)
        self.assertTrue(invite['url'].startswith('https://notki.cloudflare.net/?invite='))

        # Test session cookie sets Secure when X-Forwarded-Proto is https
        client = self.new_client()
        req_data = json.dumps({'email': 'admin@example.com', 'password': 'secure-passphrase-1'}).encode('utf-8')
        request = Request(
            self.base_url + '/api/login',
            data=req_data,
            headers={'Content-Type': 'application/json', 'X-Forwarded-Proto': 'https'},
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


class FirstRunSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / 'fresh.sqlite3'
        server.initialize_database()
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
        self.temp_dir.cleanup()

    def request(self, method, path, payload=None, headers=None):
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            headers={'Content-Type': 'application/json', **(headers or {})},
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
            headers={'Content-Type': content_type},
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
        self.assertEqual(status, 201)
        self.assertTrue(result['user']['isAdmin'])
        status, result = self.request('GET', '/api/setup/status')
        self.assertFalse(result['needsSetup'])
        status, result = self.request('POST', '/api/setup/admin', {
            'email': 'second-admin@example.com', 'password': 'secure-second-admin-password',
        })
        self.assertEqual(status, 409)

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

        mock_member2 = unittest.mock.MagicMock()
        mock_member2.name = 'Notki-master/'

        # Test path traversal prevention
        mock_member3 = unittest.mock.MagicMock()
        mock_member3.name = 'Notki-master/../etc/passwd'

        members = [mock_member1, mock_member2, mock_member3]

        mock_target_path = unittest.mock.MagicMock()
        mock_target_path.is_relative_to.return_value = True
        mock_root.__truediv__.return_value.resolve.return_value = mock_target_path

        mock_tarfile.data_filter = True # Simulate Python 3.12+

        self.handler._extract_update_archive(mock_archive, members)

        # Should only extract file1.py
        self.assertEqual(mock_member1.name, 'file1.py')
        mock_archive.extract.assert_called_once_with(mock_member1, path=mock_root, filter='data')


class GetForwardedProtoTests(unittest.TestCase):
    def setUp(self):
        class DummyHandler(server.NotkiHandler):
            def __init__(self):
                pass
        self.handler = DummyHandler()
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




class VerifyPasskeySignatureTests(unittest.TestCase):
    def setUp(self):
        self.pub_key_pem = (
            "-----BEGIN PUBLIC KEY-----\n"
            "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEbat259HqQHD7fpD1SZc3o8IPZgGd\n"
            "MIWw1g9xkdiLAzQgxGbPFZjHMToBtfwdswaZo8PnFdHQMm01tNAbHhhoHA==\n"
            "-----END PUBLIC KEY-----\n"
        )
        self.sig_bytes = b'0E\x02!\x00\xfe\xeb\xe0\x8e+\x93\x1cMj\xbfl\xd2\r\xf1\xd8\x1c\x05q\xf6\xc2dx)\xa3\x82Pi^\x17.\x99\xcc\x02 \x08\xe0^\xa9u\xe8\xd7\x04L\xfc\xc5|n\x11t\xf9\x93\xe39|\x1a\xd5\xcdy\xb1\xef\x16\x16h\x16\xce\x89'
        self.data_bytes = b'hello world'

    def test_valid_signature(self):
        self.assertTrue(server.verify_passkey_signature(self.pub_key_pem, self.sig_bytes, self.data_bytes))

    def test_invalid_signature_wrong_data(self):
        self.assertFalse(server.verify_passkey_signature(self.pub_key_pem, self.sig_bytes, b'wrong data'))

    def test_invalid_signature_wrong_sig(self):
        wrong_sig = b'0E\x02!\x00\xfe\xeb\xe0\x8e+\x93\x1cMj\xbfl\xd2\r\xf1\xd8\x1c\x05q\xf6\xc2dx)\xa3\x82Pi^\x17.\x99\xcc\x02 \x08\xe0^\xa9u\xe8\xd7\x04L\xfc\xc5|n\x11t\xf9\x93\xe39|\x1a\xd5\xcdy\xb1\xef\x16\x16h\x16\xce\x00'
        self.assertFalse(server.verify_passkey_signature(self.pub_key_pem, wrong_sig, self.data_bytes))

    @unittest.mock.patch('server.subprocess.run')
    def test_subprocess_error(self, mock_run):
        mock_run.return_value.returncode = 1
        self.assertFalse(server.verify_passkey_signature(self.pub_key_pem, self.sig_bytes, self.data_bytes))

    @unittest.mock.patch('server.subprocess.run')
    def test_exception_handling(self, mock_run):
        mock_run.side_effect = Exception("openssl not found")
        self.assertFalse(server.verify_passkey_signature(self.pub_key_pem, self.sig_bytes, self.data_bytes))

    @unittest.mock.patch('server.tempfile.NamedTemporaryFile')
    def test_finally_cleanup_on_exception(self, mock_tempfile):
        # mock writing to file to raise exception
        mock_file1 = unittest.mock.MagicMock()
        mock_file2 = unittest.mock.MagicMock()
        mock_file3 = unittest.mock.MagicMock()
        mock_file1.name = "pub_file"
        mock_file2.name = "sig_file"
        mock_file3.name = "data_file"

        mock_tempfile.side_effect = [mock_file1, mock_file2, mock_file3]

        mock_file1.write.side_effect = Exception("write failed")

        with unittest.mock.patch('server.os.unlink') as mock_unlink:
            self.assertFalse(server.verify_passkey_signature(self.pub_key_pem, self.sig_bytes, self.data_bytes))

            # verify unlink was called on all 3 temp files despite exception
            calls = [unittest.mock.call("pub_file"), unittest.mock.call("sig_file"), unittest.mock.call("data_file")]
            mock_unlink.assert_has_calls(calls, any_order=True)


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
        server.AUTH_FAILURES.clear()

    def tearDown(self):
        server.FAILED_AUTH_ATTEMPTS.clear()
        server.AUTH_FAILURES.clear()

    @unittest.mock.patch('server.time.time')
    def test_record_failed_auth_new_ip(self, mock_time):
        mock_time.return_value = 1000.0
        server.record_failed_auth('192.168.1.1')

        self.assertIn('192.168.1.1', server.FAILED_AUTH_ATTEMPTS)
        self.assertEqual(server.FAILED_AUTH_ATTEMPTS['192.168.1.1'], [1000.0])
        self.assertIn('192.168.1.1', server.AUTH_FAILURES)
        self.assertEqual(server.AUTH_FAILURES['192.168.1.1'], [1000.0])

    @unittest.mock.patch('server.time.time')
    def test_record_failed_auth_existing_ip(self, mock_time):
        mock_time.return_value = 1000.0
        server.record_failed_auth('192.168.1.2')

        mock_time.return_value = 1010.0
        server.record_failed_auth('192.168.1.2')

        self.assertEqual(server.FAILED_AUTH_ATTEMPTS['192.168.1.2'], [1000.0, 1010.0])
        self.assertEqual(server.AUTH_FAILURES['192.168.1.2'], [1000.0, 1010.0])

    @unittest.mock.patch('server.time.time')
    def test_record_failed_auth_removes_old_attempts(self, mock_time):
        # Add an old attempt
        server.FAILED_AUTH_ATTEMPTS['192.168.1.3'] = [900.0]
        server.AUTH_FAILURES['192.168.1.3'] = [900.0]

        # Add a new attempt, old one should be filtered out because now - t = 1000 - 900 = 100 >= 60
        mock_time.return_value = 1000.0
        server.record_failed_auth('192.168.1.3')

        self.assertEqual(server.FAILED_AUTH_ATTEMPTS['192.168.1.3'], [1000.0])
        self.assertEqual(server.AUTH_FAILURES['192.168.1.3'], [900.0, 1000.0])

        # Another attempt within 60s
        mock_time.return_value = 1050.0
        server.record_failed_auth('192.168.1.3')

        # 1050.0 - 1000.0 = 50 < 60, so 1000.0 is kept
        self.assertEqual(server.FAILED_AUTH_ATTEMPTS['192.168.1.3'], [1000.0, 1050.0])
        self.assertEqual(server.AUTH_FAILURES['192.168.1.3'], [900.0, 1000.0, 1050.0])

        # Another attempt outside 60s
        mock_time.return_value = 1120.0
        server.record_failed_auth('192.168.1.3')

        # 1120.0 - 1000.0 = 120 >= 60 (discarded)
        # 1120.0 - 1050.0 = 70 >= 60 (discarded)
        self.assertEqual(server.FAILED_AUTH_ATTEMPTS['192.168.1.3'], [1120.0])
        self.assertEqual(server.AUTH_FAILURES['192.168.1.3'], [900.0, 1000.0, 1050.0, 1120.0])

        # Finally test the 3600 limit for AUTH_FAILURES
        # 4600 - 900 = 3700 >= 3600 (filtered out)
        # 4600 - 1000 = 3600 >= 3600 (filtered out)
        mock_time.return_value = 4600.0
        server.record_failed_auth('192.168.1.3')
        self.assertEqual(server.AUTH_FAILURES['192.168.1.3'], [1050.0, 1120.0, 4600.0])


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

if __name__ == '__main__':
    unittest.main()
