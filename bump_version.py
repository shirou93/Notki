import re

files_to_update = ['server.py', 'index.html', 'README.md', 'tests/test_server.py']

for filepath in files_to_update:
    with open(filepath, 'r') as f:
        content = f.read()

    content = content.replace('0.1.3.2', '0.1.3.3')

    with open(filepath, 'w') as f:
        f.write(content)
