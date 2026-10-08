import re

def patch_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # Pass password for snapshot restore
    import_logic = """
      if (file.name.toLowerCase().endsWith('.tgz')) {
        const formData = new FormData();
        formData.append('archive', file);
        const password = document.querySelector('#restore-password')?.value || '';
        if (password) formData.append('password', password);
        const response = await fetch('/api/setup/import-backup', {
          method: 'POST',
          body: formData
        });"""

    content = re.sub(
        r"      if \(file\.name\.toLowerCase\(\)\.endsWith\('\.tgz'\)\) \{\s*const response = await fetch\('/api/setup/import-backup', \{\s*method: 'POST',\s*body: file\s*\}\);",
        import_logic,
        content
    )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

patch_file('setup.js')
