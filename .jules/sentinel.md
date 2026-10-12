## 2026-10-12 - Centralized Security Response Headers in BaseHTTPRequestHandler
**Vulnerability:** Lack of `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and `Content-Security-Policy` headers allowed potential Clickjacking and MIME-sniffing attacks.
**Learning:** Custom HTTP handlers inheriting from `BaseHTTPRequestHandler` can apply defense-in-depth security headers across all responses by overriding `end_headers(self)`.
**Prevention:** Always override `end_headers(self)` in custom `BaseHTTPRequestHandler` subclasses to consistently attach security response headers (`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Content-Security-Policy`).

## 2026-10-11 - OpenSSL CLI Password Process Argument Leakage
**Vulnerability:** Passing secrets via `-pass pass:<password>` in `subprocess.run(['openssl', ...])` exposes the password in plaintext to all local users via process listing tools (`ps aux` / `/proc`).
**Learning:** CLI tools that accept credentials via command-line arguments leak those credentials to the process table during execution.
**Prevention:** Pass sensitive credentials via process environment variables (`-pass env:VAR`) or standard input/file descriptors instead of command-line arguments.
