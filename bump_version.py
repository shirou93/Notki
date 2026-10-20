"""Replace a version string in the user-facing files.

Usage: python3 bump_version.py OLD_VERSION NEW_VERSION
"""
import sys
from pathlib import Path

FILES = ("server.py", "README.md", "index.html")

if len(sys.argv) != 3:
    raise SystemExit(__doc__)

old_version, new_version = sys.argv[1], sys.argv[2]
for filename in FILES:
    path = Path(filename)
    if not path.exists():
        continue
    content = path.read_text(encoding="utf-8")
    updated = content.replace(old_version, new_version)
    if updated != content:
        path.write_text(updated, encoding="utf-8")
        print(f"Updated {filename}")
