import re

def patch_admin_html():
    with open('admin.html', 'r', encoding='utf-8') as f:
        content = f.read()

    backup_additions = """<label class="field-label" style="display: flex; align-items: center; gap: 8px;"><input type="checkbox" id="backup-unencrypted-toggle"> <span data-i18n="admin.backups.allowUnencrypted">Allow unencrypted backup</span></label>
        <input class="auth-input" id="backup-password" type="password" data-i18n-placeholder="admin.backups.passwordPlaceholder" style="margin-top: 5px; margin-bottom: 10px;">
        <button class="button-primary" id="create-backup" type="button" data-i18n="admin.backups.create">+ Create .tgz backup</button>"""

    content = content.replace('<button class="button-primary" id="create-backup" type="button" data-i18n="admin.backups.create">+ Create .tgz backup</button>', backup_additions)

    restore_additions = """<div class="admin-table-wrap">
        <div style="padding: 10px; border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 10px;">
          <input class="auth-input" id="restore-password" type="password" data-i18n-placeholder="admin.backups.passwordPlaceholder" style="max-width: 250px;" placeholder="Backup password (if any)">
        </div>
        <table class="admin-table">"""

    content = content.replace('<div class="admin-table-wrap">\n        <table class="admin-table">', restore_additions, 1)

    with open('admin.html', 'w', encoding='utf-8') as f:
        f.write(content)

patch_admin_html()
