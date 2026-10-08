import re

def patch_file(filename, is_setup=False):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    if is_setup:
        theme_select = '<label class="sr-only" data-i18n="topbar.themeLabel">Theme</label><select class="auth-input profile-select" id="setup-theme" data-theme-select aria-label="Change theme" data-i18n-aria-label="theme.switch"><option value="system" data-i18n="theme.system">System</option><option value="light" data-i18n="theme.light">Light</option><option value="dark" data-i18n="theme.dark">Dark</option></select>'
        content = re.sub(
            r'(<select id="language-select".*?</select></label>)',
            r'\1\n        ' + theme_select,
            content,
            flags=re.DOTALL
        )
    else:
        theme_select = '<label class="field-label" for="profile-theme" data-i18n="topbar.themeLabel">THEME</label>\n      <select class="auth-input profile-select" id="profile-theme" data-theme-select aria-label="Change theme" data-i18n-aria-label="theme.switch"><option value="system" data-i18n="theme.system">System</option><option value="light" data-i18n="theme.light">Light</option><option value="dark" data-i18n="theme.dark">Dark</option></select>'
        content = re.sub(
            r'(<label class="field-label" for="profile-language".*?</select>)',
            r'\1\n      ' + theme_select,
            content,
            flags=re.DOTALL
        )

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

patch_file('index.html')
patch_file('admin.html')
patch_file('setup.html', is_setup=True)
