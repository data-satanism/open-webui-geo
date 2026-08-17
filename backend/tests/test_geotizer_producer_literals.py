"""No `gis_service` producer name may be written into this repository's logic.

`GISagent_yulong`, `KBagent_yulong`, `WEBagent_yulong` and `SkilledAgent` are
`gis_service`'s strings. They live in `assignment_policy.json` under
`policy_version: geotizer_assignments.v1`, arrive as the `producer` field of
every batch and evidence route, and this repository has no say in any of them.
Every copy of one compiled into a module here is a copy that goes stale the day
the service renames it -- silently, because a stale copy does not fail to
import, it just stops matching. The routing they used to drive is configuration
now: the `PRODUCER_KIND_MAP` valve on `multitask_orchestration`, which an
operator edits in Workspace without a redeploy.

Three copies came out to make that true, and each was a different shape of the
same mistake, which is why this check is repository-wide rather than pinned to
one module. `core/tasks.py` held the table. `owner_envelope.py` compared the
batch producer against `'KBagent_yulong'` to decide whether a batch got RAG-v2
retrieval plans -- routing again, in a place no valve could reach.
`workflow.py` built a synthetic `AgentTask(producer='GISagent_yulong')` for a
call GIS never planned, borrowing a contract name for a task this repository
owns outright.

None of the three broke a test when it went in. This one breaks on the next.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Somebody else's vocabulary, kept as literals so that a name coming back
# arrives here as a failure rather than as a diff nobody reads. This file is
# under `backend/tests/`, so it is exempt from its own rule -- see below.
SERVICE_PRODUCERS = ('GISagent_yulong', 'KBagent_yulong', 'WEBagent_yulong', 'SkilledAgent')

# Where a producer name is legitimately written, and why. Three entries, matched
# as path prefixes, and the list is meant to stay this short: an exemption
# nobody can hold in their head is an exemption that grows a fourth entry the
# next time the check is inconvenient.
EXEMPT_PREFIXES = (
    # The tests, which must be able to name what they forbid and to stand in for
    # the service by sending the strings it sends.
    'backend/tests/',
    # Prose about the deployed contour. `docs/geotizer-one-command.md` describes
    # the agents an operator sees in Workspace, under the names they carry there.
    'docs/',
    # Corpus, not logic: a parity fixture regenerated from `gis_service`, in
    # which the producer names are recorded data. Rewriting them here would make
    # the fixture disagree with the service it was captured from.
    'backend/open_webui/services/artifacts/geotizer/assets/geotizer-validation-parity.v1.json',
)

# Not source. Walked past rather than exempted, because none of it is written by
# hand and an offender inside would be a symptom of something else.
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
    """Producer names in string constants, with docstrings allowed through.

    The allowlist is the point. A text scan fails on the comment that records
    why the name was removed, which forces the removal to go in undocumented --
    this repository has been caught by that twice. Comments are invisible to the
    AST and so are allowed for free; docstrings are constants and have to be
    subtracted by hand, which is what the `docstrings` set does.
    """
    with warnings.catch_warnings():
        # `tools/knowledge_fs.py` writes regex patterns in non-raw strings and
        # emits seven escape-sequence warnings when parsed. Attention register
        # A-47, and not this check's finding to repeat on every run.
        warnings.simplefilter('ignore', DeprecationWarning)
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            # Not this check's job to police. `scripts/check_geotizer_import_boundary.py`
            # reports unparseable modules in the pure tree, and the rest of the
            # repository has its own gates.
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
        for producer in SERVICE_PRODUCERS:
            if producer in node.value:
                offenders.append(f'{relative}:{node.lineno}: {producer}')
    return offenders


def _text_offenders(path: Path, relative: str) -> list[str]:
    offenders: list[str] = []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        for producer in SERVICE_PRODUCERS:
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
        'a gis_service producer name is written into this repository; the '
        'producer -> kind routing belongs in the PRODUCER_KIND_MAP valve on '
        'multitask_orchestration:\n  ' + '\n  '.join(offenders)
    )


def test_the_check_actually_reaches_the_modules_the_names_came_out_of():
    """A gate that scans nothing passes forever.

    The three modules the literals were removed from are named here, so a scan
    narrowed by an exemption, a suffix list or a pruned directory fails loudly
    instead of going quiet.
    """
    scanned = {path.relative_to(REPO_ROOT).as_posix() for path in _scanned_files()}

    for expected in (
        'backend/open_webui/services/core/tasks.py',
        'backend/open_webui/services/artifacts/geotizer/owner_envelope.py',
        'backend/open_webui/services/artifacts/geotizer/workflow.py',
        'backend/open_webui/tools/geotizer.py',
    ):
        assert expected in scanned, expected


def test_each_exemption_covers_something_that_is_really_there():
    """An exemption for a path that has moved is an exemption that hides the
    next offender under the old name. Each of the three has to still be earning
    its place, and the parity asset has to still contain what it is exempt for.
    """
    for prefix in EXEMPT_PREFIXES:
        assert (REPO_ROOT / prefix).exists(), prefix

    parity = REPO_ROOT / 'backend/open_webui/services/artifacts/geotizer/assets/geotizer-validation-parity.v1.json'
    corpus = parity.read_text(encoding='utf-8')

    assert any(producer in corpus for producer in SERVICE_PRODUCERS), (
        'the parity asset no longer carries a producer name; drop its exemption rather than leaving a hole in the scan'
    )


def test_a_docstring_may_still_name_a_producer_but_a_constant_may_not(tmp_path):
    """The allowlist, exercised rather than asserted about.

    Every rule this file states about docstrings and comments is a claim about
    `_python_offenders`, and a claim about a helper is worth what its test is
    worth. Both halves are checked: the explanation passes, the value does not.
    """
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
