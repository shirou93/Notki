import re

def patch_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # The reviewer said RC4 is broken and insecure. We must use a better cipher.
    # Python standard library doesn't have AES. But it has ChaCha20 in os.urandom? No.
    # What standard lib cipher is secure?
    # Python has no symmetric encryption built-in besides extremely old/deprecated ones if any.
    # Actually wait. Is `sqlite3` capable of doing this? No.
    # What about subprocess calling `openssl enc`?
    # The reviewer didn't forbid `subprocess.run(["openssl", "enc", "-aes-256-cbc"])`.
    # Let's use `subprocess` to call `openssl aes-256-cbc`.

    rc4_code = """
def rc4_crypt(data, password_str):
    key = hashlib.pbkdf2_hmac('sha256', password_str.encode('utf-8'), b'notki-backup', 100_000)
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    j = 0
    i = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        out.append(byte ^ S[(S[i] + S[j]) % 256])
    return bytes(out)
"""

    openssl_code = """
import subprocess

def aes_encrypt(data, password_str):
    proc = subprocess.run(
        ['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-pass', f'pass:{password_str}'],
        input=data,
        capture_output=True,
        check=True
    )
    return proc.stdout

def aes_decrypt(data, password_str):
    proc = subprocess.run(
        ['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-pass', f'pass:{password_str}'],
        input=data,
        capture_output=True,
        check=True
    )
    return proc.stdout
"""

    content = content.replace(rc4_code, openssl_code)
    content = content.replace("rc4_crypt(backup_bytes, password)", "aes_encrypt(backup_bytes, password)")
    content = content.replace("rc4_crypt(archive_bytes, password)", "aes_decrypt(archive_bytes, password)")

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

patch_file('server.py')
