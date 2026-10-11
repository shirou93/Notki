import re
files_to_update = ["server.py", "index.html", "README.md", "tests/test_server.py"]
for filepath in files_to_update:
    try:
        with open(filepath, "r") as f_in:
            content = f_in.read()
        if filepath == "tests/test_server.py":
            content = content.replace("0.1.5.0", "0.1.5.1")
        content = content.replace("0.1.4.9", "0.1.5.0")
        with open(filepath, "w") as f_out:
            f_out.write(content)
    except FileNotFoundError:
        pass
