"""Rewrite the `sha256` of every recipe whose source is a kit shipped inside Charpente (`charpente://NAME`).

Run it after editing anything under charpente/kit_sources/ (`python tools/sync_kit_digests.py`); a test fails if a
recipe's digest no longer matches its kit's content, so a forgotten sync cannot ship.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from charpente.pkg import localsrc  # noqa: E402

URL = re.compile(r'(?m)^url = "(charpente://[^"]+)"$')
SHA = re.compile(r'(?m)^sha256 = "[0-9a-f]{64}"$')


def main(check: bool = False) -> int:
    stale = 0
    for recipe in sorted((ROOT / "charpente" / "pkg" / "recipes").glob("*.toml")):
        text = recipe.read_text(encoding="utf-8")
        found = URL.search(text)
        if not found:
            continue
        digest = localsrc.tree_digest(localsrc.resolve(found.group(1)))
        updated = SHA.sub(f'sha256 = "{digest}"', text, count=1)
        if updated != text:
            stale += 1
            if check:
                print(f"{recipe.name}: digest is stale (run python tools/sync_kit_digests.py)", file=sys.stderr)
            else:
                recipe.write_bytes(updated.encode("utf-8"))
                print(f"updated {recipe.name}")
    return 1 if (check and stale) else 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv))
