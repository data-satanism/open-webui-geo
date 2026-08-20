"""S1.3: the row semantics come from GMM's asset, verified on load.

Before this the nineteen row policies were transcribed into Python next to the
document that defines them. Two copies of a controlled vocabulary that can
diverge silently is A-08; a transcription is the worse half of that pair,
because it carries no digest and so cannot even be checked.

What these tests hold is the loading contract, not the content: a copy that
drifts must refuse to load, a copy of the wrong policy version must refuse to
load, and the tables the rest of the tree imports must still be exactly what
they were before the change.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from open_webui.services.geotizer import semantics
from open_webui.services.geotizer.errors import GeotizerOrchestrationError

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS = REPO_ROOT / 'backend/open_webui/services/geotizer/assets'

# The five tables as they were transcribed, kept here verbatim. If the derived
# ones ever differ, this is what says which side moved.
TRANSCRIBED_GEOLOGY = {
    15: 'tectonic_domain',
    16: 'metallogenic_province',
    17: 'ore_district',
    18: 'ore_node',
    19: 'ore_field',
}
TRANSCRIBED_RESOURCE_SCOPE = {
    44: 'ore_node',
    45: 'ore_field',
    46: 'licence_area',
    47: 'licence_area',
    48: 'licence_area',
    49: 'target_deposit',
    50: 'named_subarea',
    51: 'named_subarea',
    52: 'named_subarea',
    53: 'named_subarea',
    54: 'analogue_deposit',
    55: 'analogue_deposit',
    56: 'analogue_deposit',
}
TRANSCRIBED_ANALOGUE = {
    54: 'same_structure',
    55: 'neighbouring_structure',
    56: 'national_or_global_analogue',
}
TRANSCRIBED_GRR_STAGE = {
    68: 'routes',
    69: 'trenches',
    70: 'drilling',
    71: 'geochemistry',
    72: 'geophysics',
    73: 'prospecting',
    74: 'evaluation',
    75: 'exploration',
    76: 'all_grr',
}


@pytest.fixture
def copied_assets(tmp_path):
    target = tmp_path / 'assets'
    shutil.copytree(ASSETS, target)
    semantics._load.cache_clear()
    semantics._by_row.cache_clear()
    yield target
    semantics._load.cache_clear()
    semantics._by_row.cache_clear()


def rewrite(assets: Path, mutate) -> None:
    path = assets / semantics.POLICY_FILE
    document = json.loads(path.read_text(encoding='utf-8'))
    mutate(document)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def reprovenance(assets: Path) -> None:
    """Re-record the digest, so a test can change the content *and* the record
    and still be caught by something other than the hash."""
    path = assets / semantics.POLICY_FILE
    raw = path.read_bytes()
    provenance = json.loads((assets / semantics.PROVENANCE_FILE).read_text(encoding='utf-8'))
    entry = provenance['files'][semantics.POLICY_FILE]
    entry['sha256'] = hashlib.sha256(raw).hexdigest()
    entry['bytes'] = len(raw)
    (assets / semantics.PROVENANCE_FILE).write_text(
        json.dumps(provenance, ensure_ascii=False, indent=1) + '\n', encoding='utf-8'
    )


# -- the tables did not change ---------------------------------------------


def test_the_derived_tables_equal_the_transcription_they_replaced():
    assert semantics.GEOLOGY_ENTITY_SCOPE_BY_ROW == TRANSCRIBED_GEOLOGY
    assert semantics.RESOURCE_ENTITY_SCOPE_BY_ROW == TRANSCRIBED_RESOURCE_SCOPE
    assert semantics.ANALOGUE_RELATION_BY_ROW == TRANSCRIBED_ANALOGUE
    assert semantics.GRR_WORK_STAGE_BY_ROW == TRANSCRIBED_GRR_STAGE


def test_the_estimate_states_are_frozen_sets_per_row():
    states = semantics.RESOURCE_ESTIMATE_STATES_BY_ROW

    assert states[44] == frozenset({'author_estimate', 'conditional_p1'})
    assert states[47] == frozenset({'approved'})
    assert states[48] == frozenset({'current'})
    assert states[49] == frozenset({'target_plan'})
    assert states[54] == frozenset({'analogue'})
    assert set(states) == set(TRANSCRIBED_RESOURCE_SCOPE)


def test_the_grr_work_stage_is_read_positionally_and_the_count_is_checked(copied_assets):
    """`grr_plan` is a row range plus an ordered list of nine stages, so row 70
    is the third of nine. A tenth stage with nine rows is a policy that no
    longer says which row means what, and it must not load."""
    rewrite(
        copied_assets,
        lambda d: next(e for e in d['row_semantics'] if e['semantic_family'] == 'grr_plan')['work_stages'].append(
            'extra_stage'
        ),
    )
    reprovenance(copied_assets)

    with pytest.raises(GeotizerOrchestrationError, match='work stages'):
        semantics._by_row(str(copied_assets))


# -- the loading contract ---------------------------------------------------


def test_a_drifted_copy_refuses_to_load(copied_assets):
    path = copied_assets / semantics.POLICY_FILE
    path.write_bytes(path.read_bytes() + b'\n')

    with pytest.raises(GeotizerOrchestrationError, match='does not match its recorded digest'):
        semantics.load_policy(copied_assets)


def test_the_wrong_policy_version_refuses_to_load(copied_assets):
    """A byte-identical copy of the wrong policy is still the wrong policy, so
    the version check is separate from the digest."""
    rewrite(copied_assets, lambda d: d.update({'schema_version': '0.3.0'}))
    reprovenance(copied_assets)

    with pytest.raises(GeotizerOrchestrationError, match='not geomas-geotizer-runtime-semantics@0.2.0'):
        semantics.load_policy(copied_assets)


def test_a_row_removed_from_the_policy_refuses_to_load(copied_assets):
    """The provenance records the entry count, so silently dropping a row is
    caught even when the digest is re-recorded with it."""
    rewrite(copied_assets, lambda d: d['row_semantics'].pop())
    reprovenance(copied_assets)

    with pytest.raises(GeotizerOrchestrationError, match='row_semantics count'):
        semantics.load_policy(copied_assets)


def test_the_copy_is_byte_identical_to_its_recorded_digest():
    provenance = json.loads((ASSETS / semantics.PROVENANCE_FILE).read_text(encoding='utf-8'))
    entry = provenance['files'][semantics.POLICY_FILE]
    raw = (ASSETS / semantics.POLICY_FILE).read_bytes()

    assert hashlib.sha256(raw).hexdigest() == entry['sha256']
    assert len(raw) == entry['bytes']
    assert entry['source_repository'] == 'data-satanism/GMM'
    assert entry['source_path'] == 'contracts/ontology/geotizer-runtime-semantics.v0.2.json'


# -- what the executor now says ---------------------------------------------


def test_a_row_the_policy_covers_gets_its_source_priority_and_negative_cases():
    """The transcription carried neither for most rows. Reading the document
    means the hint says what the policy says, not a subset someone retyped."""
    hint = semantics.semantic_hint({'row_id': 54})

    assert hint['semantic_family'] == 'resource_analogue'
    assert hint['required_analogue_relation'] == 'same_structure'
    assert hint['source_priority'] == ['project_document', 'approved_report', 'authoritative_web']
    assert hint['rules'] == ['target_object_cannot_be_own_analogue']


def test_the_spatial_rows_now_get_a_hint_at_all():
    """Rows 78-87 are in the policy and were absent from the transcription, so
    the executor returned nothing but a version string for ten of them."""
    hint = semantics.semantic_hint({'row_id': 80})

    assert hint['semantic_family'] == 'infrastructure_spatial'
    assert hint['required_qualifiers'] == ['project_id', 'calculation_crs', 'measurement_method']
    assert hint['rules'] == ['missing_gis_layer_does_not_negate_document_fact']


def test_the_grr_value_kinds_still_come_from_the_attribute_name():
    """Attribute-level, and the row-level policy has no home for it -- A-50."""
    hint = semantics.semantic_hint({'row_id': 70, 'attribute_name': 'Объемы'})

    assert hint['required_work_stage'] == 'drilling'
    assert hint['allowed_value_kinds'] == ['planned_quantity', 'planned_volume']


def test_a_row_outside_the_policy_gets_only_the_version():
    assert semantics.semantic_hint({'row_id': 1}) == {'policy_version': 'geotizer_runtime_semantics.v0.2'}


def test_the_named_site_rows_still_require_a_site_name():
    """Rows 50-53 are the teaser's own subdivision, so the site name is what
    tells two otherwise identical estimates apart."""
    for row_id in (50, 51, 52, 53):
        assert 'site_name' in semantics.semantic_hint({'row_id': row_id})['required_qualifiers']
    assert 'site_name' not in semantics.semantic_hint({'row_id': 44})['required_qualifiers']


def test_no_qualifier_is_required_twice():
    """The asset already lists `resource_estimate_id` on rows 44-53 and
    `site_name` on 50-53, and the code appended both again -- so the model was
    handed each one twice.

    The older test asserted membership (`'site_name' in required`), which a
    duplicate satisfies, so nothing objected.
    """
    from open_webui.services.geotizer import semantics

    for row_id in range(1, 109):
        for attribute in ('значение', 'единица', 'источник', 'тип'):
            hint = semantics.semantic_hint({'row_id': row_id, 'attribute': attribute})
            required = (hint or {}).get('required_qualifiers')
            if not required:
                continue
            assert len(required) == len(set(required)), (row_id, attribute, required)
