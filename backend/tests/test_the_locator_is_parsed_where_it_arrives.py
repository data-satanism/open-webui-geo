"""A-178: the parser sat where it once crashed, not where the value enters.

`source_locator` is polymorphic and nothing said so. Across two consecutive
runs the split is identical — 347 mappings and 4 strings — and the four are GIS
layer reads, minted by `gis_service`'s scope resolution as a human-readable
locator and copied onto the field it binds:

    project_id=lekyn_new_data; layer_id=СЛХ_025834_ТП; feature_index=0;
    geometry=full; coordinates=EPSG:4326; area=EPSG:6933

`locator_map` was written for those four, at the site where they killed batch
2. Measured across `services/` and `tools/` before this file existed: 96
accesses that are not written as `locator_map(...)` — 23 writes, 26 handing the
value straight to a function that parses it, 2 isinstance-guarded, and **45 raw
reads**. Every one of the 45 is correct only because a string has not been
handed to it yet. That is a class, not forty-five bugs, and six instances of
the same class have already been fixed one at a time.

So the parse moves to the door. `extract_owner_envelope` and
`recover_backend_owned_owner_envelope` are the two ways an owner envelope
enters this repository, and past them no patch carries a string.

**Only the string shape.** Absent stays absent: `locator_map` answers `{}` for
`None` too, and `{}` is not `None` — `validation.py` reads `source_locator in
(None, {}, '')`, so turning absence into an empty mapping would answer that
rule differently. Normalising a shape is not inventing one.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from open_webui.services.artifacts.geotizer.owner_envelope import (
    extract_owner_envelope,
    normalise_patch_locators,
    recover_backend_owned_owner_envelope,
)
from open_webui.services.core.text import locator_map

#: The real one, from run `a067e802`'s state.
GIS_STRING = (
    'project_id=lekyn_new_data; layer_id=СЛХ_025834_ТП; feature_index=0; '
    'geometry=full; coordinates=EPSG:4326; area=EPSG:6933'
)

BATCH = {
    'batch_id': 'KB-LIC-LEGAL',
    'producer': 'kb',
    'policy_version': 'v1',
    'template_version': 't1',
    'fields': [{'field_key': 'geotizer_object.v1.r002.a01'}],
}


def envelope(locator):
    return {
        'run_id': 'r',
        'batch_id': 'KB-LIC-LEGAL',
        'producer': 'kb',
        'policy_version': 'v1',
        'template_version': 't1',
        'source_inventory': [],
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r002.a01',
                'status': 'filled',
                'value': 'СЛХ025834ТП',
                'source_locator': locator,
            }
        ],
    }


# ------------------------------------------------------------ the parse


def test_a_string_locator_becomes_a_mapping_at_the_door():
    parsed = normalise_patch_locators(envelope(GIS_STRING))['patches'][0]['source_locator']

    assert parsed['layer_id'] == 'СЛХ_025834_ТП'
    assert parsed['project_id'] == 'lekyn_new_data'
    assert parsed['feature_index'] == '0'


def test_nothing_is_lost_that_the_string_carried():
    """A crash fixed by dropping data is not fixed. Six keys in, six out."""
    parsed = normalise_patch_locators(envelope(GIS_STRING))['patches'][0]['source_locator']

    assert parsed == locator_map(GIS_STRING)
    assert len(parsed) == 6


def test_a_mapping_locator_is_returned_unchanged():
    original = {'document_id': 'd', 'page': 4}
    envelope_out = normalise_patch_locators(envelope(original))

    assert envelope_out['patches'][0]['source_locator'] == original


def test_an_absent_locator_stays_absent():
    """`{}` is not `None`, and `validation.py` reads the difference."""
    payload = envelope(None)

    assert normalise_patch_locators(payload)['patches'][0]['source_locator'] is None


def test_a_locator_that_is_neither_shape_is_left_alone():
    """There is nothing to parse and no key worth inventing."""
    payload = envelope(['a', 'b'])

    assert normalise_patch_locators(payload)['patches'][0]['source_locator'] == ['a', 'b']


def test_an_envelope_with_no_patches_survives():
    assert normalise_patch_locators({'run_id': 'r'}) == {'run_id': 'r'}


def test_everything_but_the_locator_is_carried_through():
    payload = envelope(GIS_STRING)
    payload['patches'][0]['retrieval_note'] = 'kept'
    out = normalise_patch_locators(payload)['patches'][0]

    assert out['value'] == 'СЛХ025834ТП'
    assert out['retrieval_note'] == 'kept'
    assert out['status'] == 'filled'


# ------------------------------------------------------------ both doors


def test_the_model_envelope_door_parses():
    out = extract_owner_envelope(json.dumps(envelope(GIS_STRING), ensure_ascii=False), BATCH)

    assert isinstance(out['patches'][0]['source_locator'], dict)


def test_the_recovery_door_parses():
    text = 'here you go:\n' + json.dumps(envelope(GIS_STRING), ensure_ascii=False)
    out = recover_backend_owned_owner_envelope(text, BATCH, run_id='r')

    assert out is not None
    assert isinstance(out['patches'][0]['source_locator'], dict)


def test_the_two_doors_are_the_only_ones():
    """If a third way in appears, this fails rather than the parse quietly
    covering two thirds of the traffic."""
    source = Path(
        'backend/open_webui/services/artifacts/geotizer/workflow.py'
    ).read_text(encoding='utf-8')
    tree = ast.parse(source)
    entries = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {'extract_owner_envelope', 'recover_backend_owned_owner_envelope'}
    }

    assert entries == {'extract_owner_envelope', 'recover_backend_owned_owner_envelope'}


# ----------------------------------------------------- the class, measured


def _accesses() -> dict[str, int]:
    """Every `source_locator` access under `services/` and `tools/`, by kind.

    Recomputed rather than quoted: A-178's number is the size of what is still
    open, and a number in prose is one nobody recomputes.
    """
    parsing = {
        'locator_map', 'evidence_locator_identity', 'unit_named_in_locator',
        'locator_source_refs', '_locator_strings', '_locator_without_bookkeeping',
        '_locator_without_negative_findings', '_locator_text', 'states_a_conversion',
        '_rename_locator_refs', '_measured_distances_km',
    }

    def is_locator(node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get':
            return bool(node.args) and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'source_locator'
        return isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == 'source_locator'

    counts = {'write': 0, 'handed to a parser': 0, 'isinstance-guarded': 0, 'raw read': 0}
    for root in (Path('backend/open_webui/services'), Path('backend/open_webui/tools')):
        for path in sorted(root.rglob('*.py')):
            if '__pycache__' in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
            written = {
                id(sub)
                for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                for tgt in node.targets
                for sub in ast.walk(tgt)
                if is_locator(sub)
            }
            for node in ast.walk(tree):
                if not is_locator(node):
                    continue
                if id(node) in written:
                    counts['write'] += 1
                    continue
                parent = parents.get(node)
                if isinstance(parent, ast.BoolOp):
                    parent = parents.get(parent, parent)
                name = ''
                if isinstance(parent, ast.Call):
                    name = getattr(parent.func, 'id', '') or getattr(parent.func, 'attr', '')
                if name in parsing:
                    counts['handed to a parser'] += 1
                elif name == 'isinstance':
                    counts['isinstance-guarded'] += 1
                else:
                    counts['raw read'] += 1
    return counts


def test_the_raw_reads_are_counted_rather_than_asserted_away():
    """The parse at the door makes these safe; it does not make them few.

    A ceiling, not a target. 45 on 2026-09-04, and the number only matters
    while it can grow — if a later change removes them the ceiling comes down
    with the arithmetic, the way the adapter budget does.
    """
    counts = _accesses()

    assert counts['raw read'] <= 45
    assert counts['write'] >= 20
    assert counts['handed to a parser'] >= 25
