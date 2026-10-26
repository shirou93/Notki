# Notki encrypted backups

Notki backups are single-file, password-encrypted snapshots of the whole server.
They contain all accounts, notes, note shares, invitations, passkeys, TOTP
secrets, MFA recovery codes, and server settings. Active sessions are never
included.

## Security properties

- **Always encrypted.** There is no plaintext export path. Every backup created
  by the server is encrypted, and every upload/import must be encrypted.
- **Authenticated encryption.** Payloads use AES-256-GCM. A unique 96-bit nonce
  is generated with `secrets.token_bytes` for every backup.
- **Password-based key derivation.** The 256-bit encryption key is derived with
  scrypt (`n=65536`, `r=8`, `p=1`, 16-byte random salt, 32-byte key). This
  intentionally makes guessing the backup password expensive.
- **Authenticated metadata.** The canonical JSON header (format, version,
  creation time and all KDF/cipher parameters) is passed to AES-GCM as
  additional authenticated data (AAD). Changing the version, salt, nonce,
  algorithm or timestamp invalidates the authentication tag.
- **No hidden server key.** The backup password is the only way to decrypt a
  backup. The server never stores the backup password and does not fall back to
  a server-side key.
- **Self-contained.** A single `.enc` file is enough to rebuild the server data.
  No database file, key file, or sidecar metadata is required.
- **Fail closed.** If a stored TOTP secret cannot be decrypted, backup creation
  aborts instead of silently dropping MFA data. Similarly, a user with a stored
  but undecryptable TOTP secret still requires a second factor and cannot log in
  with only a password.

The backup password must be at least 12 characters and at most 1024 characters.
It cannot be recovered by Notki. Store it separately from the backup file.

## File format (version 2)

The backup is UTF-8 JSON with this shape:

```json
{
  "format": "notki-backup",
  "version": 2,
  "createdAt": "2026-10-22T19:00:00+00:00",
  "kdf": {
    "algorithm": "scrypt",
    "salt": "<base64, 16 bytes>",
    "n": 65536,
    "r": 8,
    "p": 1
  },
  "cipher": {
    "algorithm": "AES-256-GCM",
    "nonce": "<base64, 12 bytes>"
  },
  "ciphertext": "<base64, AES-GCM ciphertext and 16-byte tag>"
}
```

The plaintext inside `ciphertext` is a JSON server snapshot:

```json
{
  "format": "notki-server-snapshot",
  "version": 2,
  "appVersion": "0.1.6.2",
  "createdAt": "...",
  "users": [],
  "notes": [],
  "invites": [],
  "shares": [],
  "passkeys": [],
  "settings": []
}
```

Snapshots are validated strictly before any database change:

- unknown fields, unsupported versions, duplicate IDs/e-mails, orphaned notes
  and shares, invalid dates, invalid TOTP secrets, oversized collections and
  invalid password hashes are rejected;
- restore runs inside a single `BEGIN IMMEDIATE` transaction and rolls back on
  any error, so a failed restore changes no data;
- backup creation and restore are serialized by a non-blocking process-wide
  lock; a second operation receives HTTP 409 instead of capturing or applying
  partially updated state;
- plaintext snapshots are capped at 100 MB.

## Creating a backup

Admin Panel → **Server-wide backups** → **Create encrypted backup**. Enter the
backup password twice when prompted. The server writes a timestamped
`notki-backup-YYYYMMDD-HHMMSSZ-<random>.enc` file into `NOTKI_BACKUP_DIR`
(default: `data/backups`) with restrictive permissions.

API equivalent:

```bash
curl -X POST https://notki.example.com/api/admin/backups \
  -H "Content-Type: application/json" \
  -H "X-Backup-Password: your long backup password" \
  -b cookies.txt \
  -d '{}'
```

The JSON body may also contain `encryptionPassword` (or `password`) for
compatibility with older clients, but the header is preferred because request
bodies can end up in logs.

Creating or restoring a backup is a sensitive operation and additionally
requires a recent login (step-up). The web UI handles this automatically; API
clients must send `X-Step-Up-Password` and, when 2FA is enabled,
`X-Step-Up-Code`, or log in again.

## Restoring a backup

Admin Panel → **Server-wide backups** → choose an `.enc` file → **Restore**. Enter the backup password. Restoring replaces every account,
note, share, invitation, passkey and setting, and signs every user out.
Afterwards, sign in with the credentials stored in the backup.

API equivalent:

```bash
curl -X POST https://notki.example.com/api/admin/backups/notki-backup-....enc/restore \
  -H "Content-Type: application/json" \
  -H "X-Backup-Password: your long backup password" \
  -b cookies.txt \
  -d '{}'
```

### CLI restore for large backups

For larger archives, stop the Notki
server and restore the file locally on the server host:

```bash
python server.py --restore-backup /path/to/notki-backup-....enc
```

The command asks for the backup password (input is hidden) and requires typing
`RESTORE` to confirm that all existing data will be replaced. This is an offline
administrative recovery path: shell access to the host plus the backup password is
sufficient to replace data, so protect both. For automation, provide the password
through a protected file and skip the prompt:

```bash
python server.py \
  --restore-backup /path/to/notki-backup-....enc \
  --backup-password-file /run/secrets/notki-backup-password \
  --yes
```

Alternatively, set `NOTKI_BACKUP_PASSWORD` in the environment; an explicit
`--backup-password-file` takes precedence. Do not pass the password as a command
line argument, because process listings may expose it.

The CLI uses the same authenticated decryption, KDF bounds, snapshot validation
and transaction as the web endpoint. Only the file-size cap is raised: the default
is 2048 MiB and can be changed with `--max-backup-size-mb` (maximum 16384 MiB).
The archive is read and decrypted in memory, so the host needs enough RAM for the
file plus its decoded JSON; for very large instances, increase the limit
deliberately and monitor memory. Run the restore while the server is stopped and
use one Notki process per SQLite database.

If the archive does not fit even the CLI limit, it is outside the supported
format envelope; split historical data or reduce attachment/avatar sizes before
creating the backup.

## Compatibility

Only the current `notki-backup` version 2 format is accepted. Older version 1
encrypted backups (`notki-encrypted-snapshot`, PBKDF2-HMAC-SHA256) and snapshot
version 1 payloads are rejected rather than silently downgraded. Plaintext JSON
snapshots and `.tgz` archives remain unsupported.

To migrate old data, restore it with an older Notki version, sign in, create a new
encrypted version 2 backup with an explicit password, and restore that file with
the current version. Backups created with the removed server-side key are not
recoverable through this code because there is no server-key fallback.

## Recovery and limitations

- **Lost backup password = lost backup.** There is no recovery key, hint, or
  server-side escrow. Keep the password in a password manager or another secure
  location.
- **Backups do not include sessions.** All users must sign in after a restore.
- **Passkey private keys never leave the client.** Backups contain only the
  public key, name and signature counter. Users keep using their existing
  authenticators; losing an authenticator still requires a recovery code or an
  admin 2FA reset.
- **TOTP secrets are included in encrypted backups** so MFA survives a restore.
  The backup file itself never contains a plaintext TOTP secret.
- **The backup password is not the user password.** It protects the backup file
  only. User passwords remain individually hashed inside the encrypted snapshot.
- **Backups are not a substitute for TLS.** Use HTTPS for every admin request
  that carries `X-Backup-Password`, and do not put the password in URLs or logs.
- **Large installations.** The web UI and HTTP API enforce a 100 MB snapshot
  limit. For larger archives, use the CLI restore described above;
  its default limit is 2048 MiB and its memory use grows with the file size.
- **Legacy formats are not accepted.** Version 1 encrypted backups and snapshot
  version 1 payloads must be migrated with an older Notki release.
- **Clock skew affects TOTP.** Restoring a backup preserves the replay counter
  (`totp_last_used_step`); codes from already-used time steps remain rejected
  after a restore.
- **The operation lock is process-local.** Run a single Notki process per
  database. If you deploy multiple processes against one SQLite file, do not
  trigger backup/restore concurrently from different workers.

## Operational checklist

1. Use a unique, long backup password and store it outside the backup directory.
2. Keep backups on encrypted storage and restrict access to administrators.
3. Test a restore on a staging instance periodically; never assume a backup is
   valid just because it exists.
4. Keep the setup token separate from backup files.
5. Rotate the backup password by creating a new backup and securely deleting the
   old one when policy requires it.
6. For CLI restores, stop the server and use a protected password file rather than
   a command-line argument.
