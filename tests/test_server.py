import http.cookiejar
import io
import json
import tarfile
import tempfile
import threading
import unittest
import unittest.mock
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

import server


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

    @staticmethod
    def new_client():
        return build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

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
    def note_payload(note_id, title, body='Treść'):
        return {
            'id': note_id, 'title': title, 'body': body, 'bodyFormat': 0, 'color': 'default', 'tags': [],
            'pinned': False, 'archived': False, 'deleted': False,
            'createdAt': server.iso_time(), 'updatedAt': server.iso_time(), 'order': 1,
        }

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

    def test_shares_survive_server_backup_restore(self):
        owner = self.register_user('owner3@example.com')
        reader = self.register_user('reader3@example.com')
        self.request(owner, 'PUT', '/api/notes', {'notes': [self.note_payload('backup-1', 'Kopia')]})
        self.request(owner, 'POST', '/api/notes/backup-1/shares', {'email': 'reader3@example.com', 'permission': 'write'})

        status, backup = self.request(self.admin, 'POST', '/api/admin/backups', {})
        self.assertEqual(status, 201)

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
        self.assertRegex(backup['filename'], r'^notki-server-\d{8}-\d{6}Z-[a-f0-9]{8}\.tgz$')
        status, backups = self.request(self.admin, 'GET', '/api/admin/backups')
        self.assertEqual(status, 200)
        self.assertEqual(backups['backups'][0]['filename'], backup['filename'])
        request = Request(self.base_url + f"/api/admin/backups/{backup['filename']}")
        with self.admin.open(request) as response:
            archive = response.read()
            self.assertEqual(response.headers.get_content_type(), 'application/gzip')
        self.assertTrue(archive.startswith(b'\x1f\x8b'))
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
        for language in ('pl', 'en'):
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
            for script in ('translations/pl.js', 'translations/en.js', 'i18n.js'):
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
            self.assertIn('data-theme-toggle', html, path)

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
        tags_response = json.dumps([{'name': 'v0.1.1.7', 'tarball_url': 'https://api.github.com/repos/shirou93/Notki/tarball/v0.1.1.7'}]).encode('utf-8')
        with unittest.mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_cm = unittest.mock.MagicMock()
            mock_cm.__enter__.return_value.read.return_value = tags_response
            mock_urlopen.return_value = mock_cm

            status, res = self.request(self.admin, 'GET', '/api/admin/update/check')
            self.assertEqual(status, 200)
            self.assertTrue(res['updateAvailable'])
            self.assertEqual(res['latestVersion'], '0.1.1.7')

        # Test check update with same tag
        tags_response_same = json.dumps([{'name': 'v0.1.1.6', 'tarball_url': 'https://api.github.com/repos/shirou93/Notki/tarball/v0.1.1.6'}]).encode('utf-8')
        with unittest.mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_cm = unittest.mock.MagicMock()
            mock_cm.__enter__.return_value.read.return_value = tags_response_same
            mock_urlopen.return_value = mock_cm

            status, res = self.request(self.admin, 'GET', '/api/admin/update/check')
            self.assertEqual(status, 200)
            self.assertFalse(res['updateAvailable'])

        # Test perform update fails when tarball contains same version
        tarball_buf = io.BytesIO()
        server_code = f"VERSION = '{server.VERSION}'\n".encode('utf-8')
        with tarfile.open(fileobj=tarball_buf, mode='w:gz') as archive:
            member = tarfile.TarInfo('repo-tag/server.py')
            member.size = len(server_code)
            archive.addfile(member, io.BytesIO(server_code))

        with unittest.mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_cm = unittest.mock.MagicMock()
            mock_cm.__enter__.return_value.read.return_value = tarball_buf.getvalue()
            mock_urlopen.return_value = mock_cm

            status, res = self.request(self.admin, 'POST', '/api/admin/update/perform', {
                'tarballUrl': 'https://api.github.com/repos/shirou93/Notki/tarball/v0.1.1.6'
            })
            self.assertEqual(status, 400)
            self.assertEqual(res['error'], 'No newer version available.')

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


if __name__ == '__main__':
    unittest.main()