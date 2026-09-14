"""A definition nothing in production reaches is not covered by its tests.

`test_nothing_in_the_pure_core_is_defined_and_never_used` already looks for
dead core definitions and did not see these, for two reasons that are each
defensible alone and blind together:

  - it counts `backend/tests` as a consumer, so a function used only by the
    tests written for it reads as used
  - it exempts `__all__` entries, on the grounds that a module may export what
    only a future caller needs

Every one of the sixteen below is exempt under both. The one that cost
something was `divergent_claim_keys`, whose own docstring calls it "the card's
«Расхождения между источниками» list, and the reason GT-4 tells a reader to
look there before the completeness figure" -- a list `GT-4` points readers at,
computed by nothing, on a card that did not carry it. Its tests passed
throughout.

So this is the strict companion: **no production reference at all** -- scripts
count as production, `__all__` and tests do not. It is a ratchet, not a
prohibition. The allowlist may shrink and must not grow: a new entry means
something was written, tested, and never wired in, which is the state this
exists to make visible on the day it happens rather than a month later.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SERVICES = BACKEND / 'open_webui/services'
PRODUCTION = (BACKEND / 'open_webui', BACKEND.parent / 'scripts')

#: Defined, tested, reached by nothing. Each entry is a debt with an owner.
#:
#: The eleven under `artifacts/cpr/` are one fact, not eleven: the CPR
#: readiness document has no runtime entry point. `render_docx` itself is not
#: here because two offline scripts call it -- `verify_release_artifacts.py`
#: and the UAT runner -- but they render from a frozen example dossier, and
#: nothing builds a dossier from a run. Closing that removes most of this list
#: in one change.
UNREACHED = {
    ('artifacts/cpr/catalog.py', 'is_draft'),
    ('artifacts/cpr/coverage.py', 'sections_needing_attention'),
    ('artifacts/cpr/narrative.py', 'analogy_sentences'),
    ('artifacts/cpr/narrative.py', 'cited_claim_ids'),
    ('artifacts/cpr/narrative.py', 'sentences_by_kind'),
    ('artifacts/cpr/project.py', 'slice_requirement_ids'),
    ('artifacts/cpr/render.py', 'render_manifest'),
    ('artifacts/cpr/requirements.py', 'coverage_gaps'),
    ('artifacts/cpr/requirements.py', 'evidence_expectations'),
    ('artifacts/cpr/requirements.py', 'requirements_by_section'),
    ('artifacts/cpr/requirements.py', 'reviewer_workload'),
    # Not the CPR pipeline. These four are reached by nothing for their own
    # reasons, and `divergent_claim_keys` is the one a prompt already promises.
    ('evaluation/rag_ab.py', 'attribution_is_preserved'),
    ('geotizer/semantics.py', 'load_policy'),
    ('project_evidence/agreement.py', 'divergent_claim_keys'),
    ('project_evidence/agreement.py', 'score_claim_agreement'),
    ('project_evidence/claims.py', 'reviewed_gap'),
    # Reached by nothing at all -- not even a test, which is why the first
    # sweep for "tested but never wired in" did not see them.
    ('artifacts/cpr/requirements.py', 'plan_ids'),
    ('artifacts/cpr/requirements.py', 'requirements_forbidding_analogy'),
    ('artifacts/cpr/requirements.py', 'requirements_needing_a_figure'),
}


WORD = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def _code_tokens(text: str) -> Counter[str]:
    """Identifiers outside comments. Strings still count; `#` lines do not.

    A mention is not a call. Documenting a defect used to make this checker
    lie about it: a comment in `owner_envelope.py` naming `reviewed_gap` as
    one of four substring defects was counted as a reference, and a function
    reached by nothing began to read as reached. The failure mode is the same
    family as the defects that comment records -- matching text where code was
    meant.

    Comments only, and not string literals. A comment can never be a
    reference; a string can be one -- a name in a dispatch table, an `__all__`
    entry, a script naming a function it calls through `getattr`. Dropping
    strings as well moved forty definitions into the dead set at once, and
    every one of them would have been a false accusation.

    Falls back to raw tokenising if the file will not tokenise, so a syntax
    error in one module cannot silently empty the whole count.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):  # pragma: no cover
        return Counter(WORD.findall(text))
    counts: Counter[str] = Counter()
    for token in tokens:
        if token.type == tokenize.COMMENT:
            continue
        counts.update(WORD.findall(token.string))
    return counts


def _production_sources() -> dict[Path, str]:
    sources = {}
    for root in PRODUCTION:
        # Asserted rather than skipped: a root that quietly does not exist
        # turns this into a check that passes because it looked nowhere.
        assert root.is_dir(), root
        for path in root.rglob('*.py'):
            if '__pycache__' not in path.parts:
                sources[path] = path.read_text(encoding='utf-8')
    return sources


def _exported(tree: ast.Module) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == '__all__' for target in node.targets
        ):
            return {item.value for item in node.value.elts if isinstance(item, ast.Constant)}
    return set()


def _unreached() -> set[tuple[str, str]]:
    """Every top-level function in the core with no production reference.

    Counted by tokenising each file once rather than by re-scanning the tree
    per name: the per-name form took a minute, and a check that slow gets
    marked slow and then gets skipped.
    """
    sources = _production_sources()
    totals: Counter[str] = Counter()
    per_module: dict[Path, Counter[str]] = {}
    for path, text in sources.items():
        counts = _code_tokens(text)
        per_module[path] = counts
        totals.update(counts)

    found: set[tuple[str, str]] = set()
    for module in sorted(SERVICES.rglob('*.py')):
        if '__pycache__' in module.parts:
            continue
        tree = ast.parse(sources[module])
        exported = _exported(tree)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            if name.startswith('__'):
                continue
            # Token counting, so `reviewed_gap` is credited neither to
            # `reviewed_gaps` -- two real functions, one of them dead, and a
            # substring count would have called the dead one reachable -- nor
            # to a comment that merely names it.
            uses = totals[name] - 1                           # minus the definition
            if name in exported:
                uses -= 1                                     # minus the `__all__` entry
            if uses <= 0:
                found.add((str(module.relative_to(SERVICES)), name))
    return found


def test_no_new_definition_is_written_tested_and_never_wired_in():
    """The ratchet. Shrinking this set is progress; growing it is the defect."""
    unreached = _unreached()

    assert unreached - UNREACHED == set(), (
        'these are defined and reached by nothing in production -- wire them '
        'in or delete them, and do not add them to UNREACHED without saying '
        'who owns the debt'
    )


def test_the_allowlist_has_no_stale_entries():
    """An entry that is now reached should leave, or the list stops meaning
    anything. This is the half that makes it a ratchet rather than a
    permanent exemption."""
    assert UNREACHED - _unreached() == set(), 'these are reached now; remove them from UNREACHED'
