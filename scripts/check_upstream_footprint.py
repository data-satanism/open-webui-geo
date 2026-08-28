#!/usr/bin/env python3
"""Fail when a fork change appears in an upstream file nobody declared.

`test_geotizer_seams.py` asserts the seams the fork *needs* are present. This
asserts no seams exist that the fork has not *declared*. Together they bound
the footprint from both ends, and this is the end that would have caught the
version-bump merge: it deleted `query_geomas_retrieval_plan_handler`, the
`data` parameter on `update_user_api_key_by_id` and the
`provision-geotizer-service-account` command, and nothing noticed.

    for every backend/open_webui file that is not fork-owned:
        normalise both sides against the pinned upstream ref
        identical           -> pass
        differs, declared   -> pass, print the diff
        differs, undeclared -> FAIL, name the file

Usage:
    python scripts/check_upstream_footprint.py [--ref REF] [--rev REV] [-v]

`--rev` compares an arbitrary commit instead of the working tree, which is how
this is verified against the historical deletion rather than only against the
tree it was written on.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upstream_normalise import normalise  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REF_FILE = Path(__file__).resolve().parent / 'upstream_ref.txt'
TREE = 'backend/open_webui'

#: Upstream files the fork is allowed to change, and why. Keep this identical
#: in spirit to `backend/tests/test_geotizer_seams.py`: that one lists the
#: lines, this one lists the files. A file here without a seam marker in it is
#: a declaration nobody honoured.
DECLARED = {
    'backend/open_webui/utils/tools.py': (
        'GEOTIZER-SEAM: the KB collection allowlist and the folder-knowledge '
        'exclusion, applied to orchestrated calls only. Marked line by line in '
        'backend/tests/test_geotizer_seams.py.'
    ),
    'backend/open_webui/tools/builtin.py': (
        'The KB collection allowlist reaches the two builtin searches here -- '
        '`__collection_allowlist__` and the read-access helper it needs. '
        'NOT line-marked yet: this is the largest undeclared footprint the '
        'check found and marking it is follow-up work.'
    ),
    'backend/open_webui/env.py': (
        "Deployment branding: WEBUI_NAME defaults to 'Geomas' and drops "
        "upstream's ' (Open WebUI)' suffix. Not GeoTeaser's, and not a seam -- "
        'a contour setting that happens to live in a tracked file.'
    ),
    'backend/open_webui/utils/plugin.py': (
        'Two bare `return`s disable pip installs driven by tool frontmatter. '
        'A deliberate hardening of the contour. See the note in the runbook: '
        "the second one sits above the function's docstring, which makes the "
        'docstring unreachable code rather than documentation.'
    ),
    'backend/open_webui/retrieval/loaders/mistral.py': (
        'OCR timeout raised from 300s to 3600s for large scanned reports. '
        'A contour tuning, not a code change.'
    ),
    # The five below are not GeoTeaser's. They arrived with the integration
    # branch and carry two coherent features that predate this declaration --
    # the check was measuring against v0.11.0 while the tree was on v0.11.1,
    # so their real size was buried inside a 138-file report of upstream's own
    # version delta. Re-pinning made them visible as five.
    #
    # Each reason states what the change does, read from the diff. None of
    # them states why the fork wants it: that belongs to whoever wrote it, and
    # a declaration that guesses at intent is worse than one that describes
    # behaviour. Correct the wording rather than the membership.
    #
    # API-key path scoping (two files):
    'backend/open_webui/models/users.py': (
        'Adds `get_api_key_by_key`, returning the ApiKey row as a model. '
        "Upstream offers only `get_user_by_api_key`, which resolves the user "
        'and discards the key record -- so the per-key scope stored on '
        '`ApiKey.data` had no way to reach the caller that enforces it.'
    ),
    'backend/open_webui/utils/auth.py': (
        'Enforces the per-key path allowlist: resolves the key record, 401s '
        'an unknown key, then 403s a request path `is_api_key_path_allowed` '
        'refuses. The predicate itself lives in the fork-owned '
        '`utils/api_key_scope.py`; this is the call site inside upstream'
        "'s authentication dependency, which is the only place it can sit."
    ),
    # RAG parent/child indexing and the GeoMAS RAG v2 flags (three files):
    'backend/open_webui/config.py': (
        'Three environment flags and one config entry: '
        '`ENABLE_RAG_PARENT_CHILD_INDEXING` (also surfaced as '
        '`rag.enable_parent_child_indexing`), `ENABLE_GEOMAS_RAG_V2` and '
        '`ENABLE_GEOMAS_RAG_V2_SHADOW`. Contour settings for features the '
        'fork adds, declared off by default.'
    ),
    'backend/open_webui/retrieval/utils.py': (
        'Wires two fork-authored modules into hybrid search: '
        "`retrieval.lexical`'s `LEGACY_LEXICAL_INDEX_CACHE` and "
        '`geological_lexical_tokens`, and `retrieval.chunking`'
        "'s `expand_parent_context_result`. Neither module exists upstream, "
        'so neither is compared; this file is where they are reached from.'
    ),
    'backend/open_webui/routers/retrieval.py': (
        'The control surface for parent/child indexing: '
        '`ENABLE_RAG_PARENT_CHILD_INDEXING` in and out of the config '
        'endpoints, and an ingestion path that skips the plain splitter when '
        '`documents_have_parent_child_lineage` says the documents already '
        'carry it. Also calls `invalidate_legacy_lexical_cache`. The '
        'chunking and lexical helpers are fork-owned files.'
    ),
}

#: Paths under the upstream tree that the fork owns outright. Everything here
#: is expected to differ and is not compared.
FORK_OWNED_PREFIXES = (
    'backend/open_webui/services/',
    'backend/open_webui/tools/geotizer',
    'backend/open_webui/utils/geotizer',
    'backend/open_webui/utils/kb_collection_scope.py',
    'backend/open_webui/utils/chat_id.py',
    'backend/open_webui/utils/api_key_scope.py',
    'backend/open_webui/routers/geotizer.py',
    # The ASGI wrapper that mounts that router. Fork-authored and inside
    # upstream's tree, so it is listed here rather than declared: upstream has
    # no `asgi.py` to compare it against. It shipped briefly as its own
    # `open_webui_geo` package, which was never compared at all -- a whole
    # fork tree outside this check's reach. Here it is at least accounted for.
    'backend/open_webui/asgi.py',
    # Fork-authored files that happen to sit in upstream's tree rather than
    # under `services/`. Added by `acd64f3` for the GeoMAS RAG v2 pipeline;
    # they are new files, not edits of upstream ones, so there is nothing for
    # a merge to conflict with and nothing for this check to compare.
    'backend/open_webui/retrieval/chunking.py',
    'backend/open_webui/retrieval/lexical.py',
)

#: Compared as source. Anything else -- icons, templates, locale JSON -- is
#: outside what this check can reason about, and pretending otherwise would
#: mean either false failures or a normaliser that lies about binary files.
SOURCE_SUFFIX = '.py'


def pinned_ref() -> str:
    for line in REF_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            return line
    raise SystemExit(f'error: no ref in {REF_FILE}')


def git(*args: str) -> str:
    return subprocess.run(
        ['git', *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


#: `--rev` sentinel meaning "the files on disk". The default, because the
#: change a developer most needs caught is the one not committed yet -- a
#: check that only reads committed revisions cannot fail on a stray line
#: until after it has been recorded in history.
WORKTREE = 'WORKTREE'


def blob(ref: str, path: str) -> str | None:
    if ref == WORKTREE:
        candidate = ROOT / path
        return (
            candidate.read_text(encoding='utf-8', errors='replace')
            if candidate.is_file()
            else None
        )
    result = subprocess.run(
        ['git', 'show', f'{ref}:{path}'], cwd=ROOT, capture_output=True, text=True
    )
    return None if result.returncode else result.stdout


def source_files(ref: str) -> set[str]:
    if ref == WORKTREE:
        return {
            str(path.relative_to(ROOT))
            for path in (ROOT / TREE).rglob(f'*{SOURCE_SUFFIX}')
            if '__pycache__' not in path.parts
        }
    return {
        path
        for path in git('ls-tree', '-r', '--name-only', ref, TREE).splitlines()
        if path.endswith(SOURCE_SUFFIX)
    }


def is_fork_owned(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in FORK_OWNED_PREFIXES)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--ref', default=None, help='upstream ref; defaults to the pinned one')
    parser.add_argument(
        '--rev',
        default=WORKTREE,
        help='fork revision to compare; default is the working tree',
    )
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    ref = args.ref or f'upstream-{pinned_ref()}'
    if not blob(ref, 'backend/open_webui/env.py'):
        print(
            f'error: upstream ref {ref!r} is not present. Fetch it with:\n'
            f'  git fetch --depth 1 https://github.com/open-webui/open-webui.git '
            f'refs/tags/{pinned_ref()}:refs/tags/upstream-{pinned_ref()}',
            file=sys.stderr,
        )
        return 2

    # Union of both sides. A file the fork deleted is as much a footprint
    # change as one it edited, and listing only the fork's tree would miss it.
    upstream_files = source_files(ref)
    fork_files = source_files(args.rev)

    undeclared: list[str] = []
    declared_changed: list[str] = []
    for path in sorted(upstream_files | fork_files):
        if is_fork_owned(path):
            continue
        if path not in upstream_files:
            # The fork added a file into the upstream tree without declaring
            # it fork-owned. Not damage, but not invisible either.
            undeclared.append(f'{path} (added by the fork, not fork-owned by prefix)')
            continue
        theirs = blob(ref, path)
        ours = blob(args.rev, path)
        if ours is None:
            undeclared.append(f'{path} (deleted by the fork)')
            continue
        if normalise(theirs) == normalise(ours):
            continue
        if path in DECLARED:
            declared_changed.append(path)
            continue
        undeclared.append(path)

    compared = len([p for p in upstream_files if not is_fork_owned(p)])
    print(f'compared {compared} upstream files against {ref}')
    for path in declared_changed:
        print(f'  declared  {path}\n            {DECLARED[path]}')
        if args.verbose:
            print(git('diff', f'{ref}:{path}', f'{args.rev}:{path}') or '')
    # A declared file that no longer differs is the deletion case, and it is a
    # failure rather than a note.
    #
    # This is the half the specification did not have, and running the check
    # across history is what showed it. At `6d8ade1^`, with the GeoMAS handler
    # still in `routers/retrieval.py`, the check names that file as an
    # undeclared fork change -- correct, and the reason it was deletable. At
    # `14fc6e5`, the merge that deleted it, the check goes quiet: there is no
    # fork change there any more, because the fork change is gone. A check
    # that only looks for the *presence* of undeclared code reports green on
    # the exact commit that did the damage.
    #
    # So a declaration is a two-way contract. Saying «the fork changes this
    # file» asserts the change is still there, and its disappearance is
    # exactly what nobody noticed the first time.
    vanished = [path for path in DECLARED if path not in declared_changed]
    if vanished:
        print(
            '\ndeclared fork changes that have vanished from upstream files:',
            file=sys.stderr,
        )
        for path in vanished:
            print(f'  {path}\n      declared as: {DECLARED[path]}', file=sys.stderr)
        print(
            '\nEither the change was deleted by a merge -- restore it -- or it '
            'was removed on purpose, in which case drop the entry from '
            'DECLARED in the same commit.',
            file=sys.stderr,
        )
    if undeclared:
        print('\nundeclared fork changes in upstream files:', file=sys.stderr)
        for path in undeclared:
            print(f'  {path}', file=sys.stderr)
        print(
            '\nEither revert the change, move the code into a fork-owned file, '
            'or add the file to DECLARED with the reason and a GEOTIZER-SEAM '
            'marker on each line.',
            file=sys.stderr,
        )
        return 1
    if vanished:
        return 1
    print('no undeclared fork changes in upstream files')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
