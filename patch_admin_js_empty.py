import re

def patch_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    empty_logic = """    const body = document.querySelector('#server-backups');
    if (!backups.length) {
      const row = document.createElement('tr');
      const empty = tableCell(t('admin.backups.empty'));
      empty.colSpan = 4;
      empty.className = 'admin-empty-cell';
      empty.style.textAlign = 'center';
      row.append(empty);
      body.replaceChildren(row);
      return;
    }"""

    content = re.sub(
        r"    const body = document\.querySelector\('#server-backups'\);\s*if \(\!backups\.length\) \{\s*const row = document\.createElement\('tr'\);\s*const empty = tableCell\(t\('admin\.backups\.empty'\)\);\s*empty\.colSpan = 4;\s*empty\.className = 'admin-empty-cell';\s*row\.append\(empty\);\s*body\.replaceChildren\(row\);\s*return;\s*\}",
        empty_logic,
        content
    )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

patch_file('admin.js')
