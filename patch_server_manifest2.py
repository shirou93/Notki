import re

with open('server.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("'manifest.json': 'application/manifest+json','index.html',", "'manifest.json', 'index.html',")

with open('server.py', 'w', encoding='utf-8') as f:
    f.write(content)
