"""Tests that every fork line required inside an upstream Open WebUI file is present and marked `GEOTIZER-SEAM`, that
departed files carry no fork code, and that `main.py` matches upstream.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

MARKER = 'GEOTIZER-SEAM'

SEAMS: dict[str, tuple[str, ...]] = {
    'open_webui/utils/tools.py': (
        'from open_webui.tools.geotizer import query_geomas_retrieval_plan',
        'builtin_functions.append(query_geomas_retrieval_plan)',
    ),
}

DEPARTED = (
    'open_webui/routers/retrieval.py',
    'open_webui/models/users.py',
    'open_webui/__init__.py',
    'open_webui/main.py',
)


def _missing_seams(content: str, expected: tuple[str, ...]) -> list[str]:
    """Expected seam substrings that are absent from `content`, or present only on lines without the marker."""
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
    """Every marked line in a seam file carries a listed seam substring."""
    marked = [line for line in read(relative).splitlines() if MARKER in line]

    unlisted = [
        line.strip()
        for line in marked
        if not any(substring in line for substring in SEAMS[relative])
    ]
    assert unlisted == [], unlisted


def test_the_detector_notices_a_deleted_seam():
    """Deleting any listed seam line makes `_missing_seams` report it."""
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
    """A seam line with its marker removed is reported as unmarked."""
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
    """No file in `DEPARTED` carries the marker or the word `geotizer`."""
    content = read(relative)

    assert MARKER not in content
    assert 'geotizer' not in content.lower()


def test_the_seam_surface_is_one_upstream_file():
    """`SEAMS` lists one upstream file and two seam lines."""
    assert len(SEAMS) == 1
    assert sum(len(expected) for expected in SEAMS.values()) == 2


def test_main_carries_no_fork_code():
    """`main.py` has an empty diff against the pinned upstream ref; skipped when that ref is not fetched."""
    import subprocess

    root = BACKEND.parent
    ref = (root / 'scripts/upstream_ref.txt').read_text(encoding='utf-8')
    ref = next(
        line.strip()
        for line in ref.splitlines()
        if line.strip() and not line.startswith('#')
    )
    probe = subprocess.run(
        ['git', 'rev-parse', '--verify', f'upstream-{ref}'],
        cwd=root, capture_output=True, text=True,
    )
    if probe.returncode != 0:
        pytest.skip(f'the pinned upstream ref upstream-{ref} is not fetched here')

    diff = subprocess.run(
        ['git', 'diff', f'upstream-{ref}', '--', 'backend/open_webui/main.py'],
        cwd=root, capture_output=True, text=True,
    )

    assert diff.stdout == '', diff.stdout[:2000]
