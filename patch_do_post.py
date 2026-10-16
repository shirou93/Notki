import re

with open('server.py', 'r') as f:
    content = f.read()

search_block = """    def handle_setup_post(self, path, payload):
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
            self.send_error_json(str(error), 400)"""

replace_block = """    def do_POST(self):
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
            self.send_error_json(str(error), 400)"""

if search_block in content:
    content = content.replace(search_block, replace_block)
    with open('server.py', 'w') as f:
        f.write(content)
    print("Replaced successfully")
else:
    print("Search block not found")
