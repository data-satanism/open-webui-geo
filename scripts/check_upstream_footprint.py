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
        'Three things. GEOTIZER-SEAM: the GeoMAS RAG v2 callable '
        '`query_geomas_retrieval_plan`, imported and appended under '
        '`ENABLE_GEOMAS_RAG_V2` -- marked line by line in '
        'backend/tests/test_geotizer_seams.py. A comment where upstream '
        "exposed `fill_geotizer` to models, recording why the fork does not. "
        'And a repair to `parse_docstring`, which dropped every line after the '
        "first of a wrapped `:param:` description -- the docstring is the "
        'tool schema, so the loss was silent and reached every tool on the '
        'instance. The KB collection allowlist and the folder-knowledge '
        'exclusion were here and are gone: access control is Open '
        "WebUI's own, decided per user by role, ownership and grants, and a "
        'deployment-wide permitted set could only subtract from it.'
    ),
    'backend/open_webui/tools/knowledge_fs.py': (
        'One branch of `_get_accessible_kb_ids`. The two arms that resolve a '
        'named collection honour `user_role == \'admin\'` through '
        '`_has_access`; the arm that enumerates passed a filter of `user_id` '
        'plus `group_ids`, and `AccessGrants.has_permission_filter` reads no '
        'role from it -- so an admin naming a collection passed on role alone '
        'while the same admin enumerating saw only what they had created. Not '
        'line-marked: `_get_accessible_kb_ids` is an active upstream body, and '
        'a merge that rewrites it takes any marker with it while a marker '
        'count still passes. What holds this is behavioural, in '
        'backend/tests/test_an_admin_enumerates_what_an_admin_may_read.py, '
        'which asserts the corpus rather than the line. Upstream v0.11.3 has '
        'the same branch unfixed; this declaration should end when that does.'
    ),
    'backend/open_webui/tools/builtin.py': (
        'Two seams in the two knowledge searches: each records the query it '
        'was given, verbatim, into the run-scoped sink in '
        '`utils/geotizer_query_sink.py`, which is how a specialist search '
        'becomes visible on `run_log.json`, together with the collection each '
        'hit came from. Both record calls are GEOTIZER-SEAM marked. The KB '
        'collection allowlist reached these searches too and is gone; the '
        'recording it made possible stays, because an unscoped search must '
        'still be visible in the artefact even with no fence to stop it. '
        'Third, `_readable_knowledge_filter`: the six knowledge enumerations '
        'here built a filter of `user_id` plus `group_ids`, which carries '
        'ownership and grants but no role, while the named lookups beside them '
        "honour `user_role == 'admin'`. Same defect as "
        '`tools/knowledge_fs.py`, six branches instead of one, and held by the '
        'same behavioural test rather than by markers.'
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
        "OCR timeout raised from upstream's 300s to 36000s for large scanned "
        'reports. A contour tuning, not a code change. Worth a second look at '
        'the value: this declaration said 3600s and the line comment said '
        '"60 minutes" while 36000 was in force, so two independent '
        'descriptions both read it as ten times smaller than it is.'
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
        'Two edits, under one key because a dict literal keeps only the last '
        'of a repeated one -- a second entry for this path was added and '
        'silently discarded, and the check still passed because it asks only '
        'whether the key is present. '
        'One: three environment flags and one config entry, '
        '`ENABLE_RAG_PARENT_CHILD_INDEXING` (also surfaced as '
        '`rag.enable_parent_child_indexing`), `ENABLE_GEOMAS_RAG_V2` and '
        '`ENABLE_GEOMAS_RAG_V2_SHADOW` -- contour settings for features the '
        'fork adds, declared off by default. '
        'Two, GEOTIZER-SEAM: one condition on the STATIC_DIR cleanup. Upstream '
        'unlinks every file in `backend/open_webui/static/` at import and then '
        'copies the frontend build back over them; with no build present it '
        'deletes 18 tracked files and restores none. That is A-19, and it is '
        'why no test may import the GeoTeaser tool adapter -- importing it '
        'damages the tree under test, so the adapter is checked by reading its '
        'call sites instead. The cleanup now runs only when the build carries '
        'a file to restore, which is the copy loop\'s own condition rather '
        'than a weaker stand-in for it: `is_dir()` is true of an empty '
        '`build/static`, and that deleted everything and restored nothing.'
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
    # The build reference `asgi.py` reads at import. A separate module
    # because `asgi` imports `open_webui.main`, so anything defined there
    # can only be imported by pulling the whole application in.
    'backend/open_webui/build_revision.py',
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

#: Upstream files this fork deliberately does not carry, and why.
#:
#: `SOURCE_SUFFIX` above is right that a PNG cannot be compared as source. It
#: does not follow that a PNG's DISAPPEARANCE cannot be noticed, and reading
#: the narrower question as the wider one is how twelve upstream files left
#: this tree with every check in the repository still green. Two of them were
#: `readme.txt` placeholders that exist only so git creates `backend/data/`;
#: without that directory `DATABASE_URL` points into nothing and every import
#: of `open_webui` dies. Nothing compared them because they are not `.py` and
#: not under `backend/open_webui` -- the check was not wrong, it was answering
#: a question nobody had asked it.
#:
#: So presence is checked over the whole tree, and every absence is either
#: listed here with a reason or a failure.
#: Upstream files the fork changes OUTSIDE the source comparison, and why.
#:
#: `SOURCE_SUFFIX` keeps the content comparison to `.py` under `backend/
#: open_webui`, which is right -- a normaliser cannot diff a PNG. But the fork
#: edits upstream files outside that set too, and until this existed not one of
#: them was declared, compared, or noticed.
#:
#: The 0.11.3 port proved the cost. `package.json` carried
#: `NODE_OPTIONS=--max-old-space-size=8192` on both build scripts, added
#: deliberately in `7b3bc5d74`; the orphan replay dropped it, the file went
#: back to upstream's bytes, and every check in this repository stayed green
#: because `package.json` was in nobody's compared set. The Dockerfile still
#: runs `npm run build`, so the build quietly lost its heap ceiling.
#:
#: These are compared at file level, not by normalised source, so the entries
#: may be binary. An exact path here MUST differ from upstream: if it stops
#: differing, the fork's edit is gone and that is a failure.
#:
#: File level is coarse, and it is worth being exact about the limit rather
#: than implying more: `package.json` carries TWO independent fork edits, so
#: losing one of them leaves the file still differing and this check still
#: green. That is precisely what happened. What catches the specific loss is a
#: content assertion --
#: `backend/tests/test_an_upstream_file_cannot_leave_unnoticed.py::
#: test_the_build_keeps_the_heap_ceiling_the_fork_gave_it` -- in the same
#: spirit as the line-level seam markers. This declaration catches a file
#: reverting wholesale; only the marker catches one edit inside it.
DECLARED_OUTSIDE_SOURCE = {
    'package.json': (
        'Both build scripts carry NODE_OPTIONS=--max-old-space-size=8192 ahead '
        'of `vite build`. Added in 7b3bc5d74; lost in the 0.11.3 port and '
        'restored. `Dockerfile` runs `npm run build` directly, so this is the '
        "only place the build's heap ceiling is set -- the Dockerfile's own "
        'suggestion at line 31 is commented out and half this size.'
    ),
    '.env.example': 'Contour defaults for a Geomas deployment.',
    '.gitattributes': 'Fork line-ending and diff rules.',
    '.github/workflows/backend.yaml': (
        "This fork's backend CI. Upstream's own workflows are not carried -- "
        'see ABSENT_BY_DESIGN.'
    ),
    'src/app.html': 'Rebrand: page title and document metadata say Geomas.',
    'src/lib/constants.ts': 'Rebrand: the name the frontend shows.',
    'src/lib/components/layout/Sidebar.svelte': 'Rebrand: the Manual link Geomas adds.',
    'static/pyodide/pyodide-lock.json': 'Pyodide package set pinned for this deployment.',
    'backend/open_webui/static/site.webmanifest': (
        'The installed PWA is called Geomas, matching `WEBUI_NAME` in `env.py`. '
        'Listed by exact path rather than left to the branding prefix below, '
        'because a prefix carries no «must still differ» check: the 0.11.3 port '
        're-branded all thirteen icons this manifest references and left the '
        'manifest naming the app «Open WebUI», and nothing said so.'
    ),
}

#: Branding assets replacing upstream's, declared by prefix because they are a
#: set rather than a list of decisions -- adding one icon is not a new choice.
#: Only exact entries above get the "must still differ" check: a prefix cannot
#: say which files it requires to exist.
DECLARED_OUTSIDE_PREFIXES = {
    'backend/open_webui/static/': 'Geomas branding, served from upstream\'s static path.',
    'static/static/': 'Geomas branding, frontend copy.',
    'static/favicon.png': 'Geomas branding, frontend copy.',
}

ABSENT_BY_DESIGN = {
    '.github/workflows/docker.yaml': "upstream's own release CI, replaced by this fork's workflows",
    '.github/workflows/frontend.yaml': "upstream's own frontend CI, replaced by this fork's workflows",
    '.github/workflows/issue-label.yaml': 'upstream issue triage, meaningless in a fork',
    '.github/workflows/release.yml': "upstream's own release automation",
    # Dropped by the 0.11.3 port rather than by a decision. Recorded so the
    # NEXT disappearance is visible -- not endorsed. Whether they come back is
    # the operator's call on the base branch; see A-389.
    '.github/FUNDING.yml': 'dropped by the 0.11.3 port, not restored (A-389)',
    '.github/ISSUE_TEMPLATE/bug_report.yaml': 'dropped by the 0.11.3 port, not restored (A-389)',
    '.github/ISSUE_TEMPLATE/config.yml': 'dropped by the 0.11.3 port, not restored (A-389)',
    '.github/ISSUE_TEMPLATE/feature_request.yaml': 'dropped by the 0.11.3 port, not restored (A-389)',
    '.github/dependabot.yml': 'dropped by the 0.11.3 port, not restored (A-389)',
    '.github/pull_request_template.md': 'dropped by the 0.11.3 port, not restored (A-389)',
    '.github/workflows/codespell.disabled': 'dropped by the 0.11.3 port, not restored (A-389)',
    '.github/workflows/lint-backend.disabled': 'dropped by the 0.11.3 port, not restored (A-389)',
    '.github/workflows/lint-frontend.disabled': 'dropped by the 0.11.3 port, not restored (A-389)',
    '.github/workflows/release-pypi.yml': 'dropped by the 0.11.3 port, not restored (A-389)',
}


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


def every_file(ref: str) -> set[str]:
    """Every tracked path at `ref` -- no subtree filter, no suffix filter.

    `source_files` is deliberately narrow because it feeds a CONTENT
    comparison. This feeds a PRESENCE comparison, which has no such limit: a
    file's absence is legible whatever its bytes are.
    """
    if ref == WORKTREE:
        return set(git('ls-files').splitlines())
    return set(git('ls-tree', '-r', '--name-only', ref).splitlines())


def modified_outside_source(ref: str, rev: str) -> list[str]:
    """Upstream files the fork changed that the source comparison never sees.

    `git diff --diff-filter=M` rather than a blob census because it answers the
    same question far more cheaply and handles the working tree without
    hashing five thousand files.
    """
    args = ['diff', '--name-only', '--diff-filter=M', ref]
    if rev != WORKTREE:
        args.append(rev)
    changed = git(*args).splitlines()
    return sorted(
        path
        for path in changed
        if not (path.startswith(TREE) and path.endswith(SOURCE_SUFFIX))
        and not is_fork_owned(path)
    )


def outside_source_gaps(changed: list[str]) -> tuple[list[str], list[str]]:
    """(changed but undeclared, declared but no longer changed).

    The second is the `package.json` case: a declared fork edit that reverted
    to upstream leaves a file that looks untouched, and only the declaration
    remembers it should not be.
    """
    undeclared = [
        path
        for path in changed
        if path not in DECLARED_OUTSIDE_SOURCE
        and not any(path.startswith(prefix) for prefix in DECLARED_OUTSIDE_PREFIXES)
    ]
    changed_set = set(changed)
    reverted = sorted(path for path in DECLARED_OUTSIDE_SOURCE if path not in changed_set)
    return undeclared, reverted


def presence_gaps(
    upstream_present: set[str], fork_present: set[str]
) -> tuple[list[str], list[str]]:
    """(files missing and undeclared, files declared absent but present).

    Pure set arithmetic on purpose: the interesting cases are a file that left
    without a reason and a reason that outlived its file, and neither needs a
    repository to describe.
    """
    missing = sorted(
        path for path in upstream_present - fork_present if path not in ABSENT_BY_DESIGN
    )
    resurfaced = sorted(path for path in ABSENT_BY_DESIGN if path in fork_present)
    return missing, resurfaced


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

    upstream_present = every_file(ref)
    fork_present = every_file(args.rev)
    # A declaration that no longer describes anything is the same failure as
    # `vanished` below: the list has to shrink when an entry's reason stops
    # being true, or it becomes a place absences go to be forgotten.
    missing, resurfaced = presence_gaps(upstream_present, fork_present)
    changed_outside = modified_outside_source(ref, args.rev)
    undeclared_outside, reverted_outside = outside_source_gaps(changed_outside)

    compared = len([p for p in upstream_files if not is_fork_owned(p)])
    print(f'compared {compared} upstream files against {ref}')
    print(
        f'checked {len(upstream_present)} upstream paths for presence; '
        f'{len(ABSENT_BY_DESIGN)} absent by design'
    )
    print(
        f'{len(changed_outside)} upstream files changed outside the source '
        f'comparison, all declared'
    )
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
    if missing:
        print('\nupstream files missing from the fork and not declared absent:', file=sys.stderr)
        for path in missing:
            print(f'  {path}', file=sys.stderr)
        print(
            '\nEither restore the file, or add it to ABSENT_BY_DESIGN with the '
            'reason it is not carried. An absence nobody wrote down is '
            'indistinguishable from one nobody noticed.',
            file=sys.stderr,
        )
        return 1
    if undeclared_outside:
        print('\nupstream files changed outside the source comparison, undeclared:', file=sys.stderr)
        for path in undeclared_outside:
            print(f'  {path}', file=sys.stderr)
        print(
            '\nAdd it to DECLARED_OUTSIDE_SOURCE with the reason, or to '
            'DECLARED_OUTSIDE_PREFIXES if it belongs to a set.',
            file=sys.stderr,
        )
        return 1
    if reverted_outside:
        print('\ndeclared as fork-changed but identical to upstream again:', file=sys.stderr)
        for path in reverted_outside:
            print(f'  {path}\n    {DECLARED_OUTSIDE_SOURCE[path]}', file=sys.stderr)
        print(
            "\nThe fork's edit is gone. Restore it, or drop the entry in the "
            'same commit that removed it on purpose.',
            file=sys.stderr,
        )
        return 1
    if resurfaced:
        print('\nlisted in ABSENT_BY_DESIGN but present in the tree:', file=sys.stderr)
        for path in resurfaced:
            print(f'  {path}', file=sys.stderr)
        print('\nDrop the entry: the reason it gave is no longer true.', file=sys.stderr)
        return 1
    if vanished:
        return 1
    print('no undeclared fork changes in upstream files')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
