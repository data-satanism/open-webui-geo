"""No retired `gis_service` producer name may be written into this repository.

`GISagent_yulong`, `KBagent_yulong`, `WEBagent_yulong` and `SkilledAgent` were
`gis_service`'s strings. They lived in `assignment_policy.json` under
`policy_version: geotizer_assignments.v1`, arrived as the `producer` field of
every batch and evidence route, and this repository never had a say in any of
them. Every copy of one compiled into a module here was a copy that went stale
the day the service renamed one -- silently, because a stale copy does not fail
to import, it just stops matching. The routing they used to drive is
configuration now: the `PRODUCER_KIND_MAP` valve on `multitask_orchestration`,
which an operator edits in Workspace without a redeploy.

Three copies came out to make that true, and each was a different shape of the
same mistake, which is why this check is repository-wide rather than pinned to
one module. `core/tasks.py` held the table. `owner_envelope.py` compared the
batch producer against `'KBagent_yulong'` to decide whether a batch got RAG-v2
retrieval plans -- routing again, in a place no valve could reach.
`workflow.py` built a synthetic `AgentTask(producer='GISagent_yulong')` for a
call GIS never planned, borrowing a contract name for a task this repository
owns outright.

None of the three broke a test when it went in. This one broke on the next --
`geotizer_assignments.v2`, which renamed all four to the agent kinds `gis`,
`kb`, `web` and `skilled`. Two things follow, and the second is a real loss:

  the four names above are now *retired*, and banning them is worth more than
  it was, not less. A rename is exactly when a stale copy appears, and a
  hardcoded `'KBagent_yulong'` left behind today matches nothing the service
  will ever send again;

  and the new names cannot be banned at all. They are this repository's own
  `AgentKind` literals -- `core/tasks.py` defines them, every valve and every
  `AgentTask` is typed by them -- so a repository-wide scan for `'kb'` would
  flag the vocabulary it exists to protect, and one narrowed enough to be
  useful would be flagging nothing. The coupling this file was written to
  police is not being watched more loosely; it stopped existing when the
  producers became the kinds. What replaced the watch is
  `test_the_parity_corpus_carries_names_this_repository_already_owns` below,
  which fires if `gis_service` ever renames back out of the kinds and makes
  `PRODUCER_KIND_MAP` load-bearing again.
"""

from __future__ import annotations

import ast
import json
import warnings
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PARITY_CORPUS = REPO_ROOT / 'backend/open_webui/services/artifacts/geotizer/assets/geotizer-validation-parity.v1.json'

# Somebody else's retired vocabulary, kept as literals so that a name coming
# back arrives here as a failure rather than as a diff nobody reads. This file
# is under `backend/tests/`, so it is exempt from its own rule -- see below.
RETIRED_SERVICE_PRODUCERS = ('GISagent_yulong', 'KBagent_yulong', 'WEBagent_yulong', 'SkilledAgent')

# Where a retired producer name is legitimately written, and why. Two entries,
# matched as path prefixes, and the list is meant to stay this short: an
# exemption nobody can hold in their head is an exemption that grows a third
# entry the next time the check is inconvenient.
EXEMPT_PREFIXES = (
    # The tests, which must be able to name what they forbid and to stand in for
    # the service by sending the strings it sends.
    'backend/tests/',
    # `docs/` had the second exemption until the mapping layer was deleted. It
    # sheltered `geotizer-one-command.md`, which told an operator to set a
    # `PRODUCER_KIND_MAP` valve naming all four retired producers. There is no
    # valve now, so that passage is gone and the exemption shelters nothing --
    # dropped for the same reason as the corpus below, and by the same failing
    # assertion telling it to. Prose is scanned like everything else, which is
    # what an operator doc reciting a retired name deserves.
    # The parity corpus had the third exemption until `.v2`. It was dropped
    # rather than kept: the corpus no longer carries a retired name, so the
    # exemption sheltered nothing and would have hidden the next offender that
    # landed under that path -- which is what the assertion below used to say in
    # its failure message, and this is that message being obeyed. The corpus is
    # now scanned like any other JSON, and a retired name reappearing in it
    # would mean a stale regeneration, which is worth failing on.
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
    next offender under the old name.

    Stricter than it was. It used to assert only that the exempt paths exist,
    plus one hand-written clause about the parity corpus -- which is how the
    corpus kept an exemption it had stopped needing. Now every exemption has to
    shelter an actual retired name, so an exemption whose contents have been
    cleaned up is reported instead of quietly widening the hole.
    """
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
    """What is still checkable here, and what deliberately is not.

    This once asserted the corpus producer was one of four `AGENT_KINDS` this
    module defined. That constant is gone: `multitask_orchestration` v4.0.0
    owns which agents exist, and a copy of its list living here is the second
    source of truth whose removal is the whole point of the change. So
    membership is no longer this repository's to check, and pretending
    otherwise would reintroduce the drift in a test rather than in a module.

    What survives is the half that does not need the list. A retired
    `*agent_yulong` name in the corpus means a stale checkout or a reverted
    rename, and the version pin says which contract the corpus was generated
    against. An agent the tool does not serve is caught where the answer lives,
    by `run_agent_task`'s `unknown_agent`.
    """
    corpus = json.loads(PARITY_CORPUS.read_text(encoding="utf-8"))

    assert corpus["policy_version"] == "geotizer_assignments.v2"
    assert _text_offenders(PARITY_CORPUS, PARITY_CORPUS.name) == []


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
