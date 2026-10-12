import re

files = ["server.py", "README.md", "index.html", "tests/test_server.py"]

for file in files:
    try:
        with open(file, "r") as f:
            content = f.read()
        content = content.replace("0.1.5.22", "0.1.5.23")
        with open(file, "w") as f:
            f.write(content)
    except FileNotFoundError:
        pass
