import re

def patch_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # Toggle unencrypted backup logic
    toggle_logic = """
  document.querySelector('#backup-unencrypted-toggle')?.addEventListener('change', event => {
    const pwdInput = document.querySelector('#backup-password');
    if (pwdInput) pwdInput.disabled = event.target.checked;
  });

  document.querySelector('#create-backup').addEventListener('click', async event => {
    const button = event.currentTarget;
    const isUnencrypted = document.querySelector('#backup-unencrypted-toggle')?.checked;
    const password = document.querySelector('#backup-password')?.value || '';
    if (!isUnencrypted && !password) {
      setBackupMessage(t('admin.backups.passwordRequired'), true);
      return;
    }
    button.disabled = true;
    setBackupMessage(t('admin.backups.creating'));
    try {
      const backup = await api('/api/admin/backups', {
        method: 'POST',
        body: JSON.stringify({ password: isUnencrypted ? null : password })
      });"""

    content = re.sub(
        r"  document\.querySelector\('#create-backup'\)\.addEventListener\('click', async event => \{\s*const button = event\.currentTarget;\s*button\.disabled = true;\s*setBackupMessage\(t\('admin\.backups\.creating'\)\);\s*try \{\s*const backup = await api\('/api/admin/backups', \{ method: 'POST', body: '\{\}' \}\);",
        toggle_logic,
        content
    )

    # Restore action logic to pass password
    restore_logic = """
          if (confirm(t('admin.backups.confirmRestore'))) {
            const password = document.querySelector('#restore-password')?.value || null;
            try {
              await api(`/api/admin/backups/${encodeURIComponent(backup.filename)}/restore`, {
                method: 'POST',
                body: JSON.stringify({ password })
              });"""

    content = re.sub(
        r"          if \(confirm\(t\('admin\.backups\.confirmRestore'\)\)\) \{\s*try \{\s*await api\(`/api/admin/backups/\$\{encodeURIComponent\(backup\.filename\)\}/restore`, \{ method: 'POST', body: '\{\}' \}\);",
        restore_logic,
        content
    )

    # Empty backups list text centering
    empty_backups_logic = """
  function renderBackups(backups) {
    const body = document.querySelector('#server-backups');
    if (backups.length === 0) {
      body.innerHTML = '<tr><td colspan="4" class="admin-empty-cell" style="text-align: center;" data-i18n="admin.backups.empty">No saved backups.</td></tr>';
      return;
    }
    const rows = backups.map(backup => {"""

    content = re.sub(
        r"  function renderBackups\(backups\) \{\s*const body = document\.querySelector\('#server-backups'\);\s*const rows = backups\.map\(backup => \{",
        empty_backups_logic,
        content
    )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

patch_file('admin.js')
