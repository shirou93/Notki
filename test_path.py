from pathlib import Path

ROOT = Path("/app").resolve()
target = (ROOT / "../etc/passwd").resolve()
print(target.is_relative_to(ROOT))
