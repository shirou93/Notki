import re

with open('server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Tar slip fix
tar_slip_code = """
                    if len(parts) > 1:
                        member.name = parts[1]
                        try:
                            target_path = (ROOT / member.name).resolve()
                            if not target_path.is_relative_to(ROOT):
                                continue
                        except ValueError:
                            continue
                        archive.extract(member, path=ROOT)
"""

content = re.sub(
    r'(\s+if len\(parts\) > 1:\s+member\.name = parts\[1\]\s+)archive\.extract\(member, path=ROOT\)',
    tar_slip_code,
    content
)

# Tarball URL validation fix
tarball_val = """
        if not tarball_url:
            raise APIError('Brak adresu tarball w odpowiedzi.', 400)
        if not tarball_url.startswith('https://api.github.com/repos/shirou93/Notki/tarball/'):
            raise APIError('Nieprawidłowy URL aktualizacji.', 400)
"""

content = re.sub(
    r'\s+if not tarball_url:\s+raise APIError\(\'Brak adresu tarball w odpowiedzi.\', 400\)',
    tarball_val,
    content
)

with open('server.py', 'w', encoding='utf-8') as f:
    f.write(content)
