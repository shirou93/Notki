import re

def fix_setup():
    with open('setup.html', 'r', encoding='utf-8') as f:
        content = f.read()

    # The previous patch injected the theme select multiple times. We'll reconstruct the auth-controls block correctly.
    clean_auth_controls = """      <div class="auth-controls">
        <label class="language-picker"><span class="sr-only" data-i18n="language.label">Language</span><select id="language-select" data-language-select aria-label="Change language" data-i18n-aria-label="language.switch"><option value="pl">Polski</option><option value="en">English</option></select></label>
        <label class="sr-only" data-i18n="topbar.themeLabel">Theme</label><select class="auth-input profile-select" id="setup-theme" data-theme-select aria-label="Change theme" data-i18n-aria-label="theme.switch"><option value="system" data-i18n="theme.system">System</option><option value="light" data-i18n="theme.light">Light</option><option value="dark" data-i18n="theme.dark">Dark</option></select>
      </div>"""

    content = re.sub(
        r'      <div class="auth-controls">.*?</div>',
        clean_auth_controls,
        content,
        flags=re.DOTALL
    )

    with open('setup.html', 'w', encoding='utf-8') as f:
        f.write(content)

fix_setup()
