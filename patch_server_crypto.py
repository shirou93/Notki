import re

def patch_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add rc4_crypt function after build_snapshot
    rc4_logic = """
    def build_snapshot(self):
        # ... (we'll replace right after build_snapshot finishes)
"""

    rc4_code = """
def rc4_crypt(data, password_str):
    key = hashlib.pbkdf2_hmac('sha256', password_str.encode('utf-8'), b'notki-backup', 100_000)
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    j = 0
    i = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        out.append(byte ^ S[(S[i] + S[j]) % 256])
    return bytes(out)

"""

    content = re.sub(
        r'(\nclass NotkiHandler\(BaseHTTPRequestHandler\):\n)',
        rc4_code + r'\1',
        content
    )

    # Update create_server_backup
    create_backup_logic = """
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
            backup_bytes = rc4_crypt(backup_bytes, password)

        backup_dir = backup_directory()
        backup_dir.mkdir(parents=True, exist_ok=True)
        filename = f"notki-server-{created_at.strftime('%Y%m%d-%H%M%SZ')}-{secrets.token_hex(4)}.tgz"
        backup_path = backup_dir / filename
        temporary_path = backup_dir / f'.{secrets.token_hex(16)}.tmp'
        try:
            with temporary_path.open('xb') as stream:
                stream.write(backup_bytes)
"""
    content = re.sub(
        r"    def create_server_backup\(self\):.*?stream\.write\(archive_buffer\.getvalue\(\)\)",
        create_backup_logic.strip('\n'),
        content,
        flags=re.DOTALL
    )

    # Update do_POST calls
    content = re.sub(
        r"            elif path == '/api/admin/backups':\s*self\.create_server_backup\(\)",
        r"            elif path == '/api/admin/backups':\n                self.create_server_backup(payload)",
        content
    )

    content = re.sub(
        r"                    self\.restore_server_backup\(match\.group\(1\)\)",
        r"                    self.restore_server_backup(match.group(1), payload)",
        content
    )

    # Update restore_server_backup
    restore_logic = """
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
                archive_bytes = rc4_crypt(archive_bytes, password)
            snapshot = self.snapshot_from_archive(archive_bytes)
"""
    content = re.sub(
        r"    def restore_server_backup\(self, filename\):.*?snapshot = self\.snapshot_from_archive\(path\.read_bytes\(\)\)",
        restore_logic.strip('\n'),
        content,
        flags=re.DOTALL
    )

    # Update import_snapshot_archive to accept optional password
    import_archive_logic = """
    def import_snapshot_archive(self, archive_bytes, password=None):
        if not self.is_local_setup_request():
            raise APIError('Import snapshotu jest dostępny tylko lokalnie.', 403)
        if password:
            archive_bytes = rc4_crypt(archive_bytes, password)
        self.restore_snapshot(self.snapshot_from_archive(archive_bytes), replace_existing=False)
"""
    content = re.sub(
        r"    def import_snapshot_archive\(self, archive_bytes\):.*?replace_existing=False\)",
        import_archive_logic.strip('\n'),
        content,
        flags=re.DOTALL
    )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

patch_file('server.py')
