"""Every line the fork requires inside an upstream Open WebUI file.

The last upstream merge deleted three fork additions from upstream files and
nothing noticed: the app booted, every test passed, and the failure waited for
a run to raise `ImportError` as a specialist failure with no obvious cause.
What made that possible is that nothing knew the additions existed.

This is the merge-damage equivalent of `test_deferred_imports_resolve.py` --
same reason for existing, that the class of failure survives a green suite.

**The seam list is the point.** Three of the four upstream files the fork used
to change are out of it entirely now, so the list is one file and four lines.
If it grows, that growth shows up here, on the change that causes it, rather
than on a run weeks later.

`_missing_seams` takes file *content* rather than reading the tree, so the
detector can be pointed at a mutated copy. A seam test that has only ever seen
the seams present proves that the current code is the current code;
`test_the_detector_notices_a_deleted_seam` deletes one and proves it fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

MARKER = 'GEOTIZER-SEAM'

#: (path relative to `backend/`, the substrings that must appear on a marked
#: line). One entry per upstream file the fork cannot leave.
SEAMS: dict[str, tuple[str, ...]] = {
    'open_webui/utils/tools.py': (
        'from open_webui.utils.kb_collection_scope import',
        'collection_allowlist = kb_collection_allowlist()',
        'model_knowledge = geotizer_kb_scope(model_knowledge, metadata, request)',
        "'__collection_allowlist__': collection_allowlist,",
    ),
}

#: Upstream files the fork used to change and no longer does. Listed so the
#: reduction is a checked fact rather than a claim in a commit message: if one
#: of them grows fork code again, `test_the_departed_files_stay_departed`
#: fails.
DEPARTED = (
    'open_webui/routers/retrieval.py',
    'open_webui/models/users.py',
    'open_webui/__init__.py',
)


def _missing_seams(content: str, expected: tuple[str, ...]) -> list[str]:
    """Expected seam substrings that are absent, or present but unmarked.

    Both halves matter. A seam whose line lost its marker is still working
    code, and would pass a plain substring check while being invisible to the
    next person reading the file for what the fork needs.
    """
    marked = [line for line in content.splitlines() if MARKER in line]
    missing = []
    for substring in expected:
        if substring not in content:
            missing.append(f'{substring!r} is gone')
        elif not any(substring in line for line in marked):
            missing.append(f'{substring!r} is present but unmarked')
    return missing


def read(relative: str) -> str:
    return (BACKEND / relative).read_text(encoding='utf-8')


@pytest.mark.parametrize('relative', sorted(SEAMS))
def test_every_seam_is_present_and_marked(relative):
    assert _missing_seams(read(relative), SEAMS[relative]) == []


@pytest.mark.parametrize('relative', sorted(SEAMS))
def test_the_file_carries_no_unlisted_marked_lines(relative):
    """A marker the list does not know about is a seam nobody counted, which
    is the state this exists to prevent -- in the other direction."""
    marked = [line for line in read(relative).splitlines() if MARKER in line]

    unlisted = [
        line.strip()
        for line in marked
        if not any(substring in line for substring in SEAMS[relative])
    ]
    assert unlisted == [], unlisted


def test_the_detector_notices_a_deleted_seam():
    """The verification the deferred-import test got: point the detector at the
    real file with one seam removed and require it to complain.

    Done for every listed seam rather than one, because a detector that catches
    the first line and not the fourth is worse than none -- it reports green
    over exactly the line nobody checked."""
    for relative, expected in SEAMS.items():
        content = read(relative)
        for substring in expected:
            mutated = '\n'.join(
                line for line in content.splitlines() if substring not in line
            )
            assert mutated != content, f'{substring!r} matched no line'
            problems = _missing_seams(mutated, expected)

            assert problems, f'deleting {substring!r} from {relative} went unnoticed'
            assert any(substring in problem for problem in problems)


def test_the_detector_notices_a_seam_that_lost_its_marker():
    """The quieter half. The line still works, so nothing fails at runtime and
    nothing fails in the suite -- but the next reader of that file has no way
    to know the fork depends on it."""
    relative, expected = next(iter(SEAMS.items()))
    substring = expected[0]
    unmarked = '\n'.join(
        line.replace(f'  # {MARKER}', '') if substring in line else line
        for line in read(relative).splitlines()
    )

    problems = _missing_seams(unmarked, expected)

    assert any('unmarked' in problem for problem in problems), problems


@pytest.mark.parametrize('relative', DEPARTED)
def test_the_departed_files_stay_departed(relative):
    """Three upstream files the fork used to change. Each is a whole file back
    out of the merge surface, and re-entering one should be a decision rather
    than a drift."""
    content = read(relative)

    assert MARKER not in content
    assert 'geotizer' not in content.lower()


def test_the_seam_surface_is_one_upstream_file():
    """The number that matters. It was four files; the task was to reduce it,
    and an accidental fifth should fail here rather than be noticed later."""
    assert len(SEAMS) == 1
    assert sum(len(expected) for expected in SEAMS.values()) == 4
