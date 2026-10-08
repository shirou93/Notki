import re

def patch_setup_html():
    with open('setup.html', 'r', encoding='utf-8') as f:
        content = f.read()

    backup_additions = """<label class="field-label" for="snapshot-file" data-i18n="setup.snapshotLabel">BACKUP ARCHIVE (.TGZ)</label>
        <input class="auth-input" id="snapshot-file" type="file" accept=".tgz,.json,application/gzip,application/json">
        <input class="auth-input" id="restore-password" type="password" data-i18n-placeholder="admin.backups.passwordPlaceholder" style="margin-top: 5px; margin-bottom: 10px;" placeholder="Backup password (if any)">
        <button class="button-secondary" id="import-snapshot" type="button" disabled data-i18n="setup.snapshotImport">Import backup</button>"""

    content = re.sub(
        r'<label class="field-label" for="snapshot-file" data-i18n="setup\.snapshotLabel">BACKUP ARCHIVE \(\.TGZ\)</label>\s*<input class="auth-input" id="snapshot-file" type="file" accept=".*?">\s*<button class="button-secondary" id="import-snapshot" type="button" disabled data-i18n="setup\.snapshotImport">Import backup</button>',
        backup_additions,
        content
    )

    with open('setup.html', 'w', encoding='utf-8') as f:
        f.write(content)

patch_setup_html()
