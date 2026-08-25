#!/usr/bin/env python3
"""`textconv` filter: print a file's normalised form for `git diff`.

Enable with, from the repository root:

    git config diff.upstreampy.textconv 'python3 scripts/upstream_textconv.py'

`.gitattributes` already routes `backend/open_webui/**/*.py` through the
`upstreampy` driver, so this takes effect the moment the config line exists and
does nothing before it -- git falls back to a plain diff for an unconfigured
driver rather than failing.

Display only. It never touches the working tree, the blobs, or a merge. There
is deliberately no `merge` driver: normalising during a merge would rewrite the
fork's own formatting and produce commits nobody wrote, and the problem is
reading the diff rather than producing the merge.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upstream_normalise import normalise  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print('usage: upstream_textconv.py <file>', file=sys.stderr)
        return 2
    source = Path(argv[0]).read_text(encoding='utf-8', errors='replace')
    sys.stdout.write(normalise(source))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
