import re

with open('server.py', 'r') as f:
    content = f.read()

content = content.replace("def save_settings(self, payload):\n        user = self.require_user(admin=True)", "def save_settings(self, payload):\n        global _FAIL2BAN_CONFIG_CACHE\n        _FAIL2BAN_CONFIG_CACHE = None\n        user = self.require_user(admin=True)")

with open('server.py', 'w') as f:
    f.write(content)
