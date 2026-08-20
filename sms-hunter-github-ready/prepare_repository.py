#!/usr/bin/env python3
"""Fill repository-owner placeholders before the first upload."""

import re
import sys
from pathlib import Path


if len(sys.argv) != 2 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?", sys.argv[1]):
    raise SystemExit("Aufruf: python3 prepare_repository.py github-benutzername-klein")

username = sys.argv[1]
root = Path(__file__).resolve().parent
files = [
    root / "templates" / "sms-hunter.xml",
    root / "templates" / "sms-hunter-gluetun.xml",
    root / "README.md",
    root / "LICENSE",
]

for path in files:
    text = path.read_text(encoding="utf-8")
    text = text.replace("REPLACE_GITHUB_USER", username)
    text = text.replace("Repository owner", username)
    path.write_text(text, encoding="utf-8")

print(f"Vorlagen für GitHub-Benutzer '{username}' vorbereitet.")
