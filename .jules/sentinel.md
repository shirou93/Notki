## 2026-10-19 - Unbounded Unauthenticated In-Memory State (Passkey Challenges / Temp 2FA Tokens)
**Vulnerability:** `generate_passkey_challenge` and `create_temp_2fa_token` appended entries to module-level dictionaries with no upper bound. The passkey challenge endpoint (`GET /api/login/passkey/challenge`) is unauthenticated, so a remote attacker could create unlimited 5-minute entries and exhaust server memory (denial of service).
**Learning:** Any in-memory map populated by unauthenticated requests must have a hard capacity bound, not only an expiry, because expiry alone does not stop a burst within the retention window.
**Prevention:** Prune expired entries and evict the oldest entries once a fixed cap (`MAX_PASSKEY_CHALLENGES`, `MAX_TEMP_2FA_TOKENS`) is reached before inserting.

## 2026-10-19 - Remote First-Run Setup via Loopback Reverse Proxy (Forwarded Header Spoofing)
**Vulnerability:** Local-only first-run setup was authorized purely from `client_address.is_loopback` plus the client-controlled `Host` header. A reverse proxy running on the same host connects over loopback, so a remote attacker could reach setup by sending `Host: localhost` (and the proxy forwarded the header), enabling administrator creation/takeover on a fresh deployment.
**Learning:** `client_address` is the proxy address, not the real client, whenever a reverse proxy is in front. Locality decisions must also inspect forwarded client headers.
**Prevention:** Treat setup as local only when the peer is loopback, the host is a localhost name, and forwarded client headers (`X-Forwarded-For`, `X-Real-IP`, `X-Forwarded-Host`) do not identify a remote client. A valid `X-Setup-Token` remains the escape hatch.

## 2026-10-19 - Fail2ban False Positives After Successful Authentication
**Vulnerability:** Failed login/2FA/passkey attempts were never reset after a successful authentication, so a user who mistyped a password a few times stayed one attempt away from a lockout for the entire window, and stale failures kept counting toward the ban threshold.
**Learning:** A successful authentication proves ownership of the account and should reset the per-IP failure budget; otherwise rate limiting degrades into a self-inflicted lockout.
**Prevention:** Call `clear_failed_auth(ip)` (memory + `fail2ban_attempts` table) only after full authentication succeeds — never on password-only success when a second factor is still pending, so TOTP guessing cannot reset the counter.

## 2026-10-19 - Unvalidated Invitation Validity Window
**Vulnerability:** `POST /api/admin/invites` passed the requested `days` value straight into `timedelta`, so a non-numeric value raised `TypeError` (HTTP 500) and extreme values created far-future invitations.
**Learning:** Numeric request fields need explicit type handling and clamping even on admin-only endpoints, to avoid crashes and state that is effectively permanent.
**Prevention:** Accept only integers within a sane range (`1..3650` days) and fall back to the default on any type/conversion error.

## 2026-10-19 - Content-Security-Policy Allowed Inline Scripts
**Vulnerability:** The CSP sent on every response included `script-src 'self' 'unsafe-inline'`, defeating the primary XSS mitigation even though the application ships no inline scripts.
**Learning:** `'unsafe-inline'` in `script-src` is only acceptable with per-request nonces/hashes; otherwise every HTML-injection bug becomes script execution.
**Prevention:** Drop `'unsafe-inline'` from `script-src` (keep it only for `style-src`, which the UI requires for inline style attributes).

## 2026-10-13 - User Enumeration Timing Attack on Login
**Vulnerability:** Short-circuiting password verification when a user email is not found in the database caused a significant timing discrepancy between existing (~50-100ms for 310k PBKDF2 iterations) and non-existing (~0ms) accounts.
**Learning:** Database lookup short-circuits prior to expensive password hashing functions expose an email enumeration timing side-channel.
**Prevention:** Always perform password verification against a dummy hash when an account email is not found to ensure constant-time response characteristics.

## 2026-10-13 - Path Traversal in Backup Filename Regex
**Vulnerability:** Loose backup filename regex `r'^notki-.*\.json$'` allowed `..` and `/` characters in filename parameters, enabling potential directory traversal attacks in admin backup file download, restore, and deletion endpoints.
**Learning:** Overly broad regex patterns (`.*`) in file name validation permit directory traversal sequences (`/`, `..`).
**Prevention:** Constrain filename regex validation strictly to safe characters (e.g., `[A-Za-z0-9_-]`) and enforce filesystem containment checks using `Path.resolve().is_relative_to(base_directory)`.

## 2026-10-12 - Centralized Security Response Headers in BaseHTTPRequestHandler
**Vulnerability:** Lack of `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and `Content-Security-Policy` headers allowed potential Clickjacking and MIME-sniffing attacks.
**Learning:** Custom HTTP handlers inheriting from `BaseHTTPRequestHandler` can apply defense-in-depth security headers across all responses by overriding `end_headers(self)`.
**Prevention:** Always override `end_headers(self)` in custom `BaseHTTPRequestHandler` subclasses to consistently attach security response headers (`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Content-Security-Policy`).

## 2026-10-11 - OpenSSL CLI Password Process Argument Leakage
**Vulnerability:** Passing secrets via `-pass pass:<password>` in `subprocess.run(['openssl', ...])` exposes the password in plaintext to all local users via process listing tools (`ps aux` / `/proc`).
**Learning:** CLI tools that accept credentials via command-line arguments leak those credentials to the process table during execution.
**Prevention:** Pass sensitive credentials via process environment variables (`-pass env:VAR`) or standard input/file descriptors instead of command-line arguments.
