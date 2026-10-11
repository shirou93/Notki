import re
files_to_update = ["server.py", "index.html", "README.md", "tests/test_server.py"]
for filepath in files_to_update:
    try:
        with open(filepath, "r") as f_in:
            content = f_in.read()
        content = content.replace("0.1.5.4", "0.1.5.5")
        with open(filepath, "w") as f_out:
            f_out.write(content)
    except FileNotFoundError:
        pass
