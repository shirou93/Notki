import re

def patch_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # The client sends multipart form data now instead of raw gzip body,
    # because setup.js uses FormData when sending the file.
    import_backup_logic = """
            if path == '/api/setup/import-backup':
                # Since setup.js sends FormData, we must read the multipart request
                import cgi
                ctype, pdict = cgi.parse_header(self.headers.get('Content-Type'))
                if ctype == 'multipart/form-data':
                    pdict['boundary'] = bytes(pdict['boundary'], 'utf-8')
                    pdict['CONTENT-LENGTH'] = int(self.headers.get('Content-Length', 0))
                    fields = cgi.parse_multipart(self.rfile, pdict)
                    archive_bytes = fields.get('archive', [b''])[0]
                    password = fields.get('password', [b''])[0].decode('utf-8')
                    if not archive_bytes:
                        raise APIError('Brak archiwum w żądaniu.', 400)
                    if len(archive_bytes) > MAX_SNAPSHOT_BYTES:
                        raise APIError('Plik backupu przekracza limit rozmiaru.', 413)
                    self.import_snapshot_archive(archive_bytes, password if password else None)
                else:
                    if ctype not in ('application/gzip', 'application/x-gzip'):
                        raise APIError('Oczekiwano archiwum .tgz lub multipart/form-data.', 415)
                    self.import_snapshot_archive(self.read_body(MAX_SNAPSHOT_BYTES))
                return
"""

    content = re.sub(
        r"            if path == '/api/setup/import-backup':.*?self\.import_snapshot_archive\(self\.read_body\(MAX_SNAPSHOT_BYTES\)\)\s*return",
        import_backup_logic.strip('\n'),
        content,
        flags=re.DOTALL
    )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

patch_file('server.py')
