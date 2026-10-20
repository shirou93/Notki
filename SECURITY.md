# Notki security changelog

## 0.1.6.0 — security hardening release (2026-10-20)

This release addresses the findings from the independent security review of
0.1.5.94. Upgrading is recommended for every deployment.

### Breaking / operational changes

- **First-run setup always requires a token.** The setup page asks for the
  one-time `X-Setup-Token` printed on startup (or the value of
  `NOTKI_SETUP_TOKEN`). A loopback connection no longer grants setup access, and
  proxy headers cannot bypass the check.
- **Mutating requests require a matching `Origin` or `Referer`.** Scheme, host,
  and port must match the externally visible host. Non-browser API clients must
  send a valid header or use the canonical `NOTKI_PUBLIC_HOST`.
- **Sensitive operations require step-up authentication.** Removing or resetting
  2FA, managing passkeys, creating/restoring/deleting server backups, and
  installing updates require a recent full sign-in (5-minute window) or the
  `X-Step-Up-Password` / `X-Step-Up-Code` headers. When TOTP is active the second
  factor is mandatory.
- **Server backups are encrypted** with AES-256-GCM, and TOTP shared secrets are encrypted at rest. Existing plaintext JSON
  snapshots can still be imported, but new exports use `.enc` files. Keep
  `NOTKI_BACKUP_KEY` (or `data/backup.key`) safe; without it, server-key backups
  cannot be restored on another installation.
- **The `/api/users` directory endpoint was removed.** Sharing by e-mail no
  longer reveals whether an account exists.
- **Docker deployments now build a pinned image** from `Dockerfile` instead of
  running `alpine:latest` and installing packages at boot.

### Findings

| ID | Severity | Fix |
|---|---|---|
| F-01 | High | `X-Forwarded-For` is parsed right-to-left across trusted proxies; per-IP and per-account login budgets are enforced with bounded memory and database retention. |
| F-02 | High | Authentication happens before request bodies are read; requests have a 15 s timeout and the server uses a bounded 32-worker `ThreadingHTTPServer`. |
| F-03 | Medium | Step-up re-authentication protects 2FA/passkey changes, backup operations, account deletion, and updates. Sensitive changes revoke other sessions. |
| F-04 | Medium | TOTP counters are stored per user; a used code (including adjacent time windows) is rejected atomically. |
| F-05 | Medium | Backup codes are 96-bit values stored as SHA-256 hashes. Legacy PBKDF2 hashes are accepted; plaintext codes are rejected and re-hashed on import. |
| F-06 | Medium | `Origin`/`Referer` is required for mutations and validated against scheme, host, and port. |
| F-07 | High (conditional) | Setup is token-only and no longer trusts loopback or forwarding headers. |
| F-08 | Low | Auth maps are capped (10k IPs/accounts, 1k attempts/key), old entries are pruned every 300 s, and fail2ban rows are retained for 7 days. |
| F-09 | Low | `/api/users` removed; `/api/setup/status` no longer discloses accounts; share creation is non-enumerating. |
| F-10 | Medium | Pinned Python dependencies and Docker base image; beta updates are opt-in; updates require a SHA-256 and optionally an Ed25519 signature. A rollback archive is written before extraction and restored on failure. |
| F-11 | Low | All new server backups are AES-256-GCM encrypted, and TOTP secrets are encrypted at rest in SQLite with a separate `NOTKI_TOTP_KEY` or a `0600` `data/totp.key` file. |
| F-12 | Medium | HTTPS uses the `__Host-notki_session` cookie; `Secure` is set when TLS is detected. `NOTKI_COOKIE_SECURE=0` can no longer disable `Secure`. Sessions have a 24 h idle timeout. |
| F-13 | Info | Removed the unsupported `NOTKI_ALLOW_REMOTE_SETUP` guidance; documented the real proxy defaults and variables. |
| F-14 | Info | Strict e-mail validation (length limits, control/whitespace/quoting rejection, alphabetic TLD). |
| F-15 | Low | `invites.created_by` is migrated to `ON DELETE SET NULL`. |
| F-16 | Info | This changelog, updated tests, and the version bump to 0.1.6.0. |

### Update verification

For non-beta updates, provide the expected SHA-256 in the admin request or set
`NOTKI_UPDATE_SHA256`. To require signed updates, set
`NOTKI_UPDATE_PUBLIC_KEY` to a base64-encoded raw Ed25519 public key (32 bytes)
or a PEM public key and provide the base64 `signature` in the update request (or
`NOTKI_UPDATE_SIGNATURE`). Unsigned updates are rejected while a public key is
configured.

`NOTKI_ALLOW_UNVERIFIED_UPDATES=1` and `NOTKI_ALLOW_BETA_UPDATES=1` are
dangerous escape hatches intended only for controlled testing.

### Deployment checklist

1. Set `NOTKI_SETUP_TOKEN` before the first start and keep it secret.
2. Terminate TLS at a trusted reverse proxy and set `NOTKI_PUBLIC_HOST`.
3. Restrict `NOTKI_TRUST_PROXY` to the proxy address or network. Never use
   `all` on an internet-facing socket.
4. Store `NOTKI_BACKUP_KEY` and `NOTKI_TOTP_KEY` outside the application
   directory and restrict access to `data/backup.key` and `data/totp.key`.
5. Run as an unprivileged user with `NoNewPrivileges` (the provided installer
   and Docker image do this).
6. Configure signed or checksum-verified updates before enabling the admin
   update button in production.

### Verification

Run the backend regression suite:

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
```

The suite covers setup-token enforcement, Origin validation, step-up auth,
TOTP replay, backup-code hashing, encrypted backups, proxy trust, rate limits,
session cookies, and update verification.
