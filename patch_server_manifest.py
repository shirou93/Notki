import re

with open('server.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("STATIC_FILES = {", "STATIC_FILES = {\n    'manifest.json': 'application/manifest+json',")
content = content.replace("if filename not in STATIC_FILES and filename not in TRANSLATION_FILES:", "if filename not in STATIC_FILES and filename not in TRANSLATION_FILES and filename != 'manifest.json':")

with open('server.py', 'w', encoding='utf-8') as f:
    f.write(content)
