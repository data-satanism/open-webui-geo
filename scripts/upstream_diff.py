#!/usr/bin/env python3
"""Diff the fork against upstream with formatting differences removed.

    python scripts/upstream_diff.py [ref] [path ...]

Runs with no configuration, which is the point: the `textconv` driver in
`.gitattributes` does the same job inside `git diff`, but only for someone who
has run `git config diff.upstreampy.textconv ...` locally. A fresh clone has
not, and a normalisation only some people see is worse than one everybody runs
deliberately.

**At the pinned ref this changes nothing, and that is a finding rather than a
disappointment.** See `scripts/upstream_normalise.py`: the fork did not
reformat upstream's files, upstream reformatted its own between v0.8.0 and
v0.11.0. Kept because the style has flipped once already and a comparison that
survives the next flip costs almost nothing.
"""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_upstream_footprint import ROOT, TREE, blob, pinned_ref, source_files  # noqa: E402
from upstream_normalise import normalise  # noqa: E402


def main(argv: list[str]) -> int:
    ref = argv[0] if argv and not argv[0].startswith('backend/') else f'upstream-{pinned_ref()}'
    paths = [arg for arg in argv if arg.startswith('backend/')]
    if not blob(ref, 'backend/open_webui/env.py'):
        print(f'error: {ref} is not present; fetch it first', file=sys.stderr)
        return 2
    if not paths:
        paths = sorted(source_files(ref) | source_files('WORKTREE'))

    shown = 0
    for path in paths:
        theirs = blob(ref, path)
        ours = blob('WORKTREE', path)
        if theirs is None or ours is None:
            print(f'--- {path}: {"added by the fork" if theirs is None else "deleted by the fork"}')
            shown += 1
            continue
        if normalise(theirs) == normalise(ours):
            continue
        shown += 1
        # Diff the *original* lines, not the normalised ones. Normalisation
        # decides whether to show a file; showing its normalised form would
        # hand back text that exists in neither tree and cannot be applied,
        # searched for, or pasted into an editor.
        print(
            '\n'.join(
                difflib.unified_diff(
                    theirs.splitlines(),
                    ours.splitlines(),
                    fromfile=f'{ref}:{path}',
                    tofile=f'worktree:{path}',
                    lineterm='',
                )
            )
        )
    print(f'\n{shown} file(s) differ in substance from {ref}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
