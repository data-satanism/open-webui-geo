"""Every number `services/README.md` states, recomputed from the tree.

That file has been wrong in four separate ways at once: a total that was really
its table's largest single row, a tree size eight commits stale, a layer table
five modules short of the tree it claims to describe, and "the other 35 live in
`artifacts/geotizer/*`" when 32 do and 3 live somewhere the same sentence's
justification does not cover.

None of it was caught, because prose is the one place nobody recomputes. Three
mutually inconsistent statements of the same residue survived a fully green CI.
So the numbers are parsed out of the document and checked against the code here,
and a reader can trust them for the same reason they can trust a test.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[1] / 'open_webui/services'
README = SERVICES / 'README.md'


def _modules() -> list[Path]:
    return sorted(p for p in SERVICES.rglob('*.py') if '__pycache__' not in p.parts)


def _definitions() -> list[tuple[str, str, bool]]:
    """(module, name, mentions_field_key) for every top-level definition."""
    found: list[tuple[str, str, bool]] = []
    for path in _modules():
        source = path.read_text(encoding='utf-8')
        for node in ast.parse(source).body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                segment = ast.get_source_segment(source, node) or ''
                found.append((str(path.relative_to(SERVICES)), node.name, 'field_key' in segment))
    return found


@pytest.fixture(scope='module')
def readme() -> str:
    return README.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def definitions() -> list[tuple[str, str, bool]]:
    return _definitions()


def test_the_tree_size_is_what_the_readme_says(readme, definitions):
    stated = re.search(r'(\d+) top-level definitions in (\d+) modules', readme)

    assert stated, 'the README states a tree size'
    assert int(stated.group(1)) == len(definitions)
    assert int(stated.group(2)) == len(_modules())


def test_the_layer_table_lists_every_module(readme):
    """A module missing from the table is a module whose layer nobody declared,
    and the layering test's own map is a different file -- so an omission here
    is invisible from both sides."""
    listed = set(re.findall(r'^\| *\d+ \| `([^`]+)`', readme, re.M))
    actual = {str(p.relative_to(SERVICES)) for p in _modules()}

    assert listed == actual


def test_the_field_key_residue_totals_are_recomputed(readme, definitions):
    mentions = [(module, name) for module, name, hit in definitions if hit]
    stated = re.search(r'\*\*(\d+) of the (\d+)\n?definitions still mention', readme)

    assert stated, 'the README states the residue'
    assert int(stated.group(1)) == len(mentions)
    assert int(stated.group(2)) == len(definitions)


def test_the_residue_is_split_by_where_it_lives(readme, definitions):
    """The split is the whole point: only `project_evidence/` is coupling. The
    README claimed 35 in `artifacts/geotizer/*`; three of those are in the
    consistency checker and the evaluator, which compare both artefacts and so
    need both vocabularies -- a different justification, folded into the
    artefact's by a number that was never checked."""
    mentions = [module for module, _, hit in definitions if hit]
    in_evidence = sum(1 for m in mentions if m.startswith('project_evidence/'))
    in_geotizer = sum(1 for m in mentions if m.startswith('artifacts/geotizer/'))
    elsewhere = len(mentions) - in_evidence - in_geotizer

    assert re.search(rf'\*\*{in_geotizer}\*\* are in\n`artifacts/geotizer/\*`', readme)
    assert re.search(rf'remaining \*\*{elsewhere}\*\* are in', readme)
    assert 'thirteen' in readme and in_evidence == 13


def test_the_rule_copy_count_is_the_same_everywhere_in_the_file(readme):
    """The file said "13 hand-written copies" in the layer table and "eleven"
    a hundred lines later. Both cannot be the count; `validation.py` holds 13
    functions of which 2 are entry points."""
    tree = ast.parse((SERVICES / 'artifacts/geotizer/validation.py').read_text(encoding='utf-8'))
    entry_points = {'validate_owner_envelope', 'owner_submission'}
    copies = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name not in entry_points]

    assert len(copies) == 11
    assert f'{len(copies)} hand-written copies' in readme
    assert 'eleven hand-written copies' in readme
    assert '13 hand-written copies' not in readme


def test_no_sentence_still_says_nine(readme):
    """The residue was corrected from "nine" to "thirteen" in one paragraph and
    left as "those nine" fifteen lines below it."""
    assert 'those nine' not in readme
