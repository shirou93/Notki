## 2026-10-09 - Secure password passing to subprocess
**Vulnerability:** Backup encryption/decryption passwords were being passed directly as command line arguments to openssl using subprocess.run().
**Learning:** Passing secrets as command line arguments is highly insecure as they can be captured by system logging, or command monitoring utilities like ps or top.
**Prevention:** Pass sensitive information securely through environment variables when running commands via subprocess, especially for cryptographic keys/passwords. Use `env=os.environ.copy()` and add the sensitive value to the env dictionary.
