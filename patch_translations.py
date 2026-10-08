import re

def patch_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    replacements = {
        'translations/en.js': """  'topbar.themeLabel': 'THEME',
  'theme.switch': 'Change theme',
  'theme.system': 'System',
  'theme.light': 'Light',
  'theme.dark': 'Dark',
  'topbar.logout':""",
        'translations/pl.js': """  'topbar.themeLabel': 'MOTYW',
  'theme.switch': 'Zmień motyw',
  'theme.system': 'Systemowy',
  'theme.light': 'Jasny',
  'theme.dark': 'Ciemny',
  'topbar.logout':"""
    }

    content = content.replace("  'topbar.theme.enableDark'", "// 'topbar.theme.enableDark'")
    content = content.replace("  'topbar.theme.enableLight'", "// 'topbar.theme.enableLight'")

    content = re.sub(r"  'topbar\.logout':", replacements[filename], content)

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

patch_file('translations/en.js')
patch_file('translations/pl.js')
