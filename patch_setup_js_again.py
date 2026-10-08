import re

def patch_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    import_logic = """
      if (file.name.toLowerCase().endsWith('.tgz')) {
        const formData = new FormData();
        formData.append('archive', file);
        const password = document.querySelector('#restore-password')?.value || '';
        if (password) formData.append('password', password);
        const response = await fetch('/api/setup/import-backup', {
          method: 'POST',
          headers: { 'Accept-Language': window.i18n.getLanguage() },
          body: formData,
          credentials: 'same-origin',
        });
        const result = await response.json().catch(() => ({}));
"""

    content = re.sub(
        r"      if \(file\.name\.toLowerCase\(\)\.endsWith\('\.tgz'\)\) \{\s*const response = await fetch\('/api/setup/import-backup', \{\s*method: 'POST',\s*headers: \{ 'Content-Type': 'application/gzip', 'Accept-Language': window\.i18n\.getLanguage\(\) \},\s*body: file,\s*credentials: 'same-origin',\s*\}\);\s*const result = await response\.json\(\)\.catch\(\(\) => \(\{\}\)\);",
        import_logic.strip('\n'),
        content,
        flags=re.DOTALL
    )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

patch_file('setup.js')
