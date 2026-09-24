"""Remove UTF-8 BOM from personality JSON files (PowerShell UTF8 writes BOM)."""
from __future__ import print_function

import os
import sys

JOURNAL_DIR = os.path.join(
    os.path.expanduser("~"),
    "OneDrive", "Documents", "My Games", "beyond the sword", "civ4ai-autotest",
)
PERSONALITY_DIR = os.path.join(JOURNAL_DIR, "sidecar-personalities")


def main():
    if not os.path.isdir(PERSONALITY_DIR):
        print("STRIP_BOM=SKIP no personality dir")
        return 0
    fixed = 0
    for name in os.listdir(PERSONALITY_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(PERSONALITY_DIR, name)
        with open(path, "rb") as handle:
            data = handle.read()
        if data.startswith(b"\xef\xbb\xbf"):
            with open(path, "wb") as handle:
                handle.write(data[3:])
            fixed += 1
    print("STRIP_BOM=OK fixed=%d" % fixed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
