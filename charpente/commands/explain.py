"""`charpente explain CHxxxx` -- the long explanation of an error code, in
the user's language (--lang fr|en overrides CHARPENTE_LANG)."""
from __future__ import annotations

import argparse
import re
from typing import List

from .. import i18n
from ..errors import ChError, describe


def execute(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="charpente explain",
                                     description="Explain an error code (e.g. CH3001).")
    parser.add_argument("code", nargs="?", help="Error code, e.g. CH1001")
    parser.add_argument("--lang", choices=list(i18n.SUPPORTED), help="Language of the explanation")
    parser.add_argument("--list", action="store_true", help="List every known error code")
    parsed = parser.parse_args(args)

    lang = parsed.lang or i18n.current_lang()

    if parsed.list:
        for code in i18n.codes():
            entry = i18n.entry(code, lang)
            if entry is not None:
                print(f"{code}  {entry['title']}")
        return 0

    if not parsed.code:
        raise ChError("CH4005", usage="Usage: charpente explain CHxxxx   (or --list)")

    code = parsed.code.strip().upper()
    if re.fullmatch(r"\d{4}", code):
        code = "CH" + code
    text = describe(code, lang)
    if not text:
        print(f"charpente: {i18n.label('unknown_code', lang)}: {parsed.code}. "
              f"Try: charpente explain --list")
        return 1
    print(text)
    return 0
