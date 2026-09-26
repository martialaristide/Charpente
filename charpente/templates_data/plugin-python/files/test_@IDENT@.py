"""Run after building:  python -m pytest   (or just: python test_@IDENT@.py). Point Python at the build folder first."""
import glob
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
for folder in glob.glob(os.path.join(here, "build", "*", "@IDENT@")):
    sys.path.insert(0, folder)

import @IDENT@  # noqa: E402


def test_add():
    assert @IDENT@.add(2, 3) == 5


def test_mean():
    assert abs(@IDENT@.mean([1.0, 2.0, 6.0]) - 3.0) < 1e-12


def test_shout():
    assert @IDENT@.shout("hey") == "hey!"


if __name__ == "__main__":
    test_add(); test_mean(); test_shout()
    print("ok: module from", @IDENT@.__file__)
