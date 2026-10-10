import re

files_to_update = ['server.py', 'index.html', 'README.md', 'tests/test_server.py']

for filepath in files_to_update:
    with open(filepath, 'r') as f:
        content = f.read()

    # If updating test file, update newer version tag as well if needed
    if filepath == 'tests/test_server.py':
        content = content.replace('0.1.4.3', '0.1.4.4')

    content = content.replace('0.1.4.2', '0.1.4.3')

    with open(filepath, 'w') as f:
        f.write(content)
