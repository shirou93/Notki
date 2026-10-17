files = ["server.py", "README.md", "index.html", "tests/test_server.py", "package.json"]

for file in files:
    try:
        with open(file, "r") as f:
            content = f.read()
        content = content.replace("0.1.5.88", "0.1.5.89")
        with open(file, "w") as f:
            f.write(content)
    except FileNotFoundError:
        pass
