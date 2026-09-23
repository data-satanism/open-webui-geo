"""No retired `gis_service` producer name may be written into this repository outside
the exempt paths."""

from __future__ import annotations

import ast
import json
import warnings
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PARITY_CORPUS = REPO_ROOT / 'backend/open_webui/services/artifacts/geotizer/assets/geotizer-validation-parity.v1.json'

RETIRED_SERVICE_PRODUCERS = ('GISagent_yulong', 'KBagent_yulong', 'WEBagent_yulong', 'SkilledAgent')

EXEMPT_PREFIXES = (
    'backend/tests/',
)

NOT_SOURCE = {'.git', '.pytest_cache', '.ruff_cache', '.venv', '__pycache__', 'node_modules', 'dist', 'build'}

SCANNED_SUFFIXES = ('.py', '.json', '.md')


def _scanned_files() -> list[Path]:
    """Every hand-written source, data and prose file, exemptions removed."""
    found: list[Path] = []
    for path in REPO_ROOT.rglob('*'):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        if NOT_SOURCE.intersection(path.relative_to(REPO_ROOT).parts):
            continue
        if relative.startswith(EXEMPT_PREFIXES):
            continue
        found.append(path)
    return sorted(found)


def _python_offenders(path: Path, relative: str) -> list[str]:
    """Return the retired producer names found in a module's string constants.

    Comments are not scanned, a docstring is skipped only when its raw text equals
    its `ast.get_docstring` form, and an unparseable module yields no offenders.
    """
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            return []

    docstrings = {
        ast.get_docstring(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if node.value in docstrings:
            continue
        for producer in RETIRED_SERVICE_PRODUCERS:
            if producer in node.value:
                offenders.append(f'{relative}:{node.lineno}: {producer}')
    return offenders


def _text_offenders(path: Path, relative: str) -> list[str]:
    offenders: list[str] = []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        for producer in RETIRED_SERVICE_PRODUCERS:
            if producer in line:
                offenders.append(f'{relative}:{number}: {producer}')
    return offenders


def test_no_producer_name_is_compiled_into_anything_outside_the_exemptions():
    offenders: list[str] = []
    for path in _scanned_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        if path.suffix == '.py':
            offenders.extend(_python_offenders(path, relative))
        else:
            offenders.extend(_text_offenders(path, relative))

    assert offenders == [], (
        'a retired gis_service producer name is written into this repository; '
        'geotizer_assignments.v2 renamed all four to agent kinds, so this string '
        'matches nothing the service sends and the producer -> kind routing '
        'belongs in the PRODUCER_KIND_MAP valve on '
        'multitask_orchestration:\n  ' + '\n  '.join(offenders)
    )


def test_the_check_actually_reaches_the_modules_the_names_came_out_of():
    """The scan reaches the modules the producer literals were removed from."""
    scanned = {path.relative_to(REPO_ROOT).as_posix() for path in _scanned_files()}

    for expected in (
        'backend/open_webui/services/core/tasks.py',
        'backend/open_webui/services/artifacts/geotizer/owner_envelope.py',
        'backend/open_webui/services/artifacts/geotizer/workflow.py',
        'backend/open_webui/tools/geotizer.py',
    ):
        assert expected in scanned, expected


def test_each_exemption_covers_something_that_is_really_there():
    """Every exempt prefix exists and still contains a retired producer name."""
    for prefix in EXEMPT_PREFIXES:
        target = REPO_ROOT / prefix
        assert target.exists(), prefix

        paths = sorted(target.rglob('*')) if target.is_dir() else [target]
        sheltered = [
            path
            for path in paths
            if path.is_file()
            and path.suffix in SCANNED_SUFFIXES
            and not NOT_SOURCE.intersection(path.relative_to(REPO_ROOT).parts)
            and _text_offenders(path, prefix)
        ]

        assert sheltered, (
            f'{prefix} no longer contains a retired producer name; drop the '
            'exemption rather than leaving a hole in the scan'
        )


def test_the_parity_corpus_carries_no_retired_producer():
    """The parity corpus is pinned to `geotizer_assignments.v3` and carries no retired
    producer name."""
    corpus = json.loads(PARITY_CORPUS.read_text(encoding="utf-8"))

    assert corpus["policy_version"] == "geotizer_assignments.v3"
    assert _text_offenders(PARITY_CORPUS, PARITY_CORPUS.name) == []


def test_a_docstring_may_still_name_a_producer_but_a_constant_may_not(tmp_path):
    """`_python_offenders` passes a one-line docstring or a comment naming a producer and
    reports a constant that does."""
    documented = (
        '"""The table held GISagent_yulong until the valve replaced it."""\n'
        '# and KBagent_yulong was the second entry\n'
        "SOMETHING = 'unrelated'\n"
    )
    offending = "PRODUCER = 'WEBagent_yulong'\n"

    scratch = tmp_path / 'probe.py'

    scratch.write_text(documented, encoding='utf-8')
    assert _python_offenders(scratch, 'probe.py') == []

    scratch.write_text(offending, encoding='utf-8')
    assert _python_offenders(scratch, 'probe.py') == ['probe.py:1: WEBagent_yulong']
