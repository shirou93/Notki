import re

with open('tests/test_server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Since we replaced the theme-toggle button with a select, we don't have data-theme-toggle anymore.
# We have data-theme-select.
content = content.replace("self.assertIn('data-theme-toggle', html, path)", "self.assertIn('data-theme-select', html, path)")

with open('tests/test_server.py', 'w', encoding='utf-8') as f:
    f.write(content)
