import re

def patch_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    replacements = {
        'translations/en.js': """  'admin.backups.empty': 'No saved backups.',
  'admin.backups.allowUnencrypted': 'Allow unencrypted backup',
  'admin.backups.passwordPlaceholder': 'Backup password',
  'admin.backups.passwordRequired': 'Password is required to encrypt the backup.',
  'admin.backups.title':""",
        'translations/pl.js': """  'admin.backups.empty': 'Brak zapisanych backupów.',
  'admin.backups.allowUnencrypted': 'Pozwalaj na backup nieszyfrowany',
  'admin.backups.passwordPlaceholder': 'Hasło do backupu',
  'admin.backups.passwordRequired': 'Hasło jest wymagane do zaszyfrowania backupu.',
  'admin.backups.title':"""
    }

    content = content.replace("  'admin.backups.title':", replacements[filename])

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

patch_file('translations/en.js')
patch_file('translations/pl.js')
