## 2026-10-11 - OpenSSL CLI Password Process Argument Leakage
**Vulnerability:** Passing secrets via `-pass pass:<password>` in `subprocess.run(['openssl', ...])` exposes the password in plaintext to all local users via process listing tools (`ps aux` / `/proc`).
**Learning:** CLI tools that accept credentials via command-line arguments leak those credentials to the process table during execution.
**Prevention:** Pass sensitive credentials via process environment variables (`-pass env:VAR`) or standard input/file descriptors instead of command-line arguments.
