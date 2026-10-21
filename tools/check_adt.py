#!/usr/bin/env python3
"""Scan an ADT/device tree blob for string properties that are not NUL terminated.

Device tree strings have to be NUL terminated, and a property holding a list of
strings has to be NUL separated. Miss either and the kernel reads one string
where several were meant (so every IONameMatch against that list silently
fails), and anything treating the value as a C string walks off the end.

    python check_adt.py tools/polaris.adt
    python check_adt.py tools/polaris.adt --strings-only
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402


def looks_like_string(b):
    """True when the bytes are plausibly text rather than a number or blob.

    Numbers (u32/u64 pairs like memory-frequency = 0x6ee68000) often contain a
    few printable bytes, so anything carrying a non printable byte - '\0'
    separators aside - is treated as binary and skipped.
    """
    if len(b) < 2:
        return False
    printable = 0
    for c in b:
        if c == 0:
            continue
        if not (0x20 <= c < 0x7f):
            return False
        printable += 1
    return printable >= 2


def walk(node, path=""):
    here = path + "/" + (node.name or "?")
    for entry in node.props:
        name, _, val = entry
        b = bytes(val) if not isinstance(val, bytes) else val
        if name == "name":
            continue
        if not looks_like_string(b):
            continue
        problems = []
        if not b.endswith(b"\0"):
            problems.append("missing trailing NUL")
        # A trailing empty string would leave two NULs; that is legal but odd.
        if b"\0\0" in b:
            problems.append("empty string in the middle")
        for p in problems:
            yield "%s: %s = %r  -> %s" % (here, name, b[:70], p)
    for child in node.children:
        for line in walk(child, here):
            yield line


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: check_adt.py FILE.adt")
    with open(args[0], "rb") as fh:
        root, _ = adt.parse(fh.read())

    bad = list(walk(root))
    print("%s: %s" % (args[0], "OK - every string property is NUL terminated"
                      if not bad else "%d problem(s)" % len(bad)))
    for line in bad:
        print("  " + line)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
