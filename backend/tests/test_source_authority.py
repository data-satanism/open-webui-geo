"""The source hierarchy as a rule the resolver runs, not prose in a prompt.

The specialist prompts have said *registries over snippets, WEB last* since the
beginning. Run `6056e157` finished with 25 conflicts and every one of them
reads "both sources are kept", because prose does not adjudicate a conflict.

Measured on that run, the two sides of a conflict carry these `source_type`
pairs:

    12  gis / web
     7  knowledge_base / web
     5  gis / knowledge_base
     1  web / web

So `WEB last` settles 19 of the 25 on its own. The 5 gis-against-document pairs
are deliberately not settled here: which wins depends on the field family — GIS
is authoritative for a geometry, a licence document for a licence number — and
that is the question standing with the domain reviewer. The 1 web-against-web
pair is two snippets and needs a person.

`source_class`, the finer vocabulary the contributor contract declares, is
absent from 44 of the 50 conflict sides on that run, so a hierarchy keyed on it
would have resolved almost nothing. `source_type` on the registered source is
what the data actually carries.
"""

from __future__ import annotations

import pytest
from open_webui.services.project_evidence.proposals import (
    PRIMARY_SOURCE_TYPES,
    WEB_SOURCE_TYPES,
    resolve_by_source_authority,
)

SOURCES = {
    'gis-1': {'source_type': 'gis'},
    'kb-1': {'source_type': 'knowledge_base'},
    'dc-1': {'source_type': 'datacube'},
    'web-1': {'source_type': 'web'},
    'web-2': {'source_type': 'web'},
    'derived-1': {'source_type': 'derived'},
    'unknown-1': {},
}


def _candidate(ref, value):
    return {'source_ref': ref, 'value': value, 'unit': 'т', 'value_origin': 'direct'}


@pytest.mark.parametrize('primary', ['gis-1', 'kb-1', 'dc-1'])
def test_a_primary_source_beats_a_web_snippet(primary):
    """19 of this run's 25 conflicts. It is the half of the prose the data can
    settle without a person."""
    winner, trace = resolve_by_source_authority(
        [_candidate(primary, 'primary'), _candidate('web-1', 'snippet')], SOURCES
    )

    assert winner['value'] == 'primary'
    assert 'WEB' in trace


def test_two_primaries_are_left_to_a_person():
    """A geometry against a licence document is a real disagreement between two
    things entitled to be believed. Guessing puts a value in the card nobody
    chose, which is what a conflict exists to prevent."""
    winner, trace = resolve_by_source_authority(
        [_candidate('gis-1', 'a'), _candidate('kb-1', 'b')], SOURCES
    )

    assert winner is None


def test_two_web_snippets_are_left_to_a_person():
    winner, trace = resolve_by_source_authority(
        [_candidate('web-1', 'a'), _candidate('web-2', 'b')], SOURCES
    )

    assert winner is None
    assert 'WEB' in trace


@pytest.mark.parametrize('ref', ['derived-1', 'unknown-1'])
def test_a_source_of_unknown_rank_stops_the_rule(ref):
    """`derived` and an unregistered ref are not classes this hierarchy ranks.
    Resolving around one would be deciding on evidence the rule never saw.

    Both shapes matter, and the second is the one that hides. Without a web
    side the rule declines anyway, so a two-candidate case proves nothing about
    the unranked guard; the three-candidate case is where dropping it would
    quietly resolve a conflict one of whose sides was never weighed.
    """
    assert resolve_by_source_authority(
        [_candidate('gis-1', 'a'), _candidate(ref, 'b')], SOURCES
    )[0] is None

    assert resolve_by_source_authority(
        [_candidate('gis-1', 'a'), _candidate(ref, 'b'), _candidate('web-1', 'c')], SOURCES
    )[0] is None


def test_two_primaries_against_a_web_source_still_stand():
    """The web value losing does not make the two primaries agree."""
    winner, trace = resolve_by_source_authority(
        [_candidate('gis-1', 'a'), _candidate('kb-1', 'b'), _candidate('web-1', 'c')], SOURCES
    )

    assert winner is None
    assert 'экспертом' in trace


def test_one_primary_beats_several_web_sources():
    winner, trace = resolve_by_source_authority(
        [_candidate('kb-1', 'doc'), _candidate('web-1', 'x'), _candidate('web-2', 'y')], SOURCES
    )

    assert winner['value'] == 'doc'
    assert '2 WEB' in trace


def test_a_single_candidate_is_not_a_conflict():
    assert resolve_by_source_authority([_candidate('web-1', 'a')], SOURCES) == (None, '')


def test_every_outcome_carries_a_reason_or_is_not_a_conflict():
    """A resolution nobody can audit is worse than a conflict, and a conflict
    with no reason is what this run produced 25 of."""
    resolved, trace = resolve_by_source_authority(
        [_candidate('gis-1', 'a'), _candidate('web-1', 'b')], SOURCES
    )
    assert resolved is not None and trace

    unresolved, trace = resolve_by_source_authority(
        [_candidate('web-1', 'a'), _candidate('web-2', 'b')], SOURCES
    )
    assert unresolved is None and trace


def test_web_is_not_a_primary_source():
    """The ranks must not overlap, or `WEB last` would depend on iteration
    order."""
    assert not (WEB_SOURCE_TYPES & PRIMARY_SOURCE_TYPES)


# -- the wiring, which is the half that keeps going missing -----------------


def _resolver_fixture(owner_source_type, proposal_domain):
    """One owner patch and one contributor proposal that disagree.

    This is the path that produced 24 of the run's 25 conflicts: "the owner
    direct value conflicts with a structured direct contributor claim".
    """
    from test_geotizer_orchestration import batch, envelope

    value = batch()
    raw = envelope()
    del raw['patches'][1:]
    raw['patches'][0].update(
        {
            'field_key': 'f1',
            'value': 'owner-value',
            'unit': 'т',
            'status': 'filled',
            'value_origin': 'direct',
            'source_locator': {'page': 7},
            'source_refs': ['owner-src'],
        }
    )
    raw['source_inventory'] = [
        {
            'source_id': 'owner-src',
            'source_type': owner_source_type,
            'title': 'Проект ГРР',
            'locator': 'стр. 7',
            'url': None,
        }
    ]
    proposals = [
        {
            'field_key': 'f1',
            'value': 'contributor-value',
            'unit': 'т',
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': 'contrib',
            'source_title': 'Пресс-релиз',
            'source_locator': {'collection_or_url': 'https://example.invalid/a'},
            'retrieval_note': 'Direct fact.',
        }
    ]
    return value, raw, [{'source_domain': proposal_domain, 'field_proposals': proposals}]


def _resolved_patch(owner_source_type, proposal_domain):
    from open_webui.services.project_evidence.proposals import (
        apply_structured_external_field_proposals,
    )

    value, raw, evidence = _resolver_fixture(owner_source_type, proposal_domain)
    return apply_structured_external_field_proposals(value, raw, evidence)['patches'][0]


def test_the_resolver_applies_the_hierarchy_when_a_document_meets_the_web():
    """The owner read a document; a web contributor disagreed. The document
    wins, the cell fills, and the rejected value is still recorded."""
    patch = _resolved_patch('knowledge_base', 'web')

    assert patch['status'] == 'filled'
    assert patch['value'] == 'owner-value'
    assert patch['source_locator']['policy'] == 'resolved_by_source_authority'
    assert 'selection_trace' in patch['source_locator']
    values = [item['value'] for item in patch['source_locator']['candidates']]
    assert 'contributor-value' in values, 'the rejected value must survive the resolution'


def test_the_resolver_leaves_two_documents_conflicted():
    """Nothing in the hierarchy separates them, so the cell stays a conflict
    and the card still says so."""
    patch = _resolved_patch('knowledge_base', 'kb')

    assert patch['status'] == 'conflicted'
    assert patch['value'] is None
    assert patch['source_locator']['policy'] == 'direct_disagreement_is_conflicted'


def test_a_resolved_cell_keeps_both_source_refs():
    """The losing source is part of how the value was arrived at, and dropping
    it would make the trace unverifiable."""
    patch = _resolved_patch('gis', 'web')

    assert len(patch['source_refs']) == 2


def _negative_finding_fixture():
    """Run `6af7479f`, cell D24, as the pipeline actually produced it.

    A GIS layer inventory answered «Не выявлено» for the intrusive-control
    row; a document answered «диориты, кварцевые диориты, плагиограниты» for
    the same row. The GIS answer filled the cell, the document answer then
    disagreed with it, and the cell ended `conflicted` with `value: None` --
    sixteen times, all in `KB-GEO`, which is why that batch fell from 39
    filled to 14.
    """
    from test_geotizer_orchestration import batch, envelope

    value = batch()
    raw = envelope()
    del raw['patches'][1:]
    raw['patches'][0].update(
        {
            'field_key': 'f1',
            'value': None,
            'unit': None,
            'status': 'not_found',
            'value_origin': None,
            'source_locator': {'query': 'field f1'},
            'source_refs': ['s1'],
        }
    )
    gis = [
        {
            'field_key': 'f1',
            'value': 'Не выявлено',
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': 'lekyn_layers',
            'source_title': 'layer inventory',
            'source_locator': {'layer_id': 'list_layers'},
            'retrieval_note': 'Layer inventory.',
        }
    ]
    document = [
        {
            'field_key': 'f1',
            'value': 'диориты, кварцевые диориты, плагиограниты',
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': 'doc-115',
            'source_title': 'Отчёт',
            'source_locator': {'page': '115'},
            'retrieval_note': 'Direct fact.',
        }
    ]
    return value, raw, [
        {'source_domain': 'gis', 'field_proposals': gis},
        {'source_domain': 'kb', 'field_proposals': document},
    ]


def _negative_finding_patch():
    from open_webui.services.project_evidence.proposals import (
        apply_structured_external_field_proposals,
        apply_structured_gis_field_proposals,
    )

    value, raw, evidence = _negative_finding_fixture()
    after = apply_structured_gis_field_proposals(value, raw, evidence)
    after = apply_structured_external_field_proposals(value, after, evidence)
    return after['patches'][0]


def test_a_source_that_found_nothing_does_not_disagree_with_one_that_did():
    """The sixteen. A negative finding is a statement about one source, not a
    claim about the object, so there is nothing for the hierarchy to weigh and
    the answer that exists is the answer."""
    patch = _negative_finding_patch()

    assert patch['status'] == 'filled'
    assert patch['value'] == 'диориты, кварцевые диориты, плагиограниты'


def test_the_empty_search_is_still_on_the_record():
    """Dropping the negative would fix the cell and lose the fact that GIS
    looked. It is kept beside the value, under its own key: both readers of
    `candidates` print every entry as a value someone proposed."""
    patch = _negative_finding_patch()
    locator = patch['source_locator']

    assert [item['value'] for item in locator['negative_findings']] == ['Не выявлено']
    assert locator['negative_findings'][0]['source_ref'] in patch['source_refs']
    assert 'candidates' not in locator


def _same_source_fixture(owner_value, owner_unit, proposal_value, proposal_unit):
    """One document read twice: the owner's patch and the same proposal.

    Run `6af7479f`'s `D47`, `H48` and `H66` in one shape. The owner wrote the
    figure into its patch and the contributor's structured proposal arrived
    carrying the same figure from the same source, so the pair reaching the
    comparison is one claim spelled two ways.
    """
    from test_geotizer_orchestration import batch, envelope

    value = batch()
    raw = envelope()
    del raw['patches'][1:]
    raw['patches'][0].update(
        {
            'field_key': 'f1',
            'value': owner_value,
            'unit': owner_unit,
            'status': 'filled',
            'value_origin': 'direct',
            'source_locator': {'page': 127},
            'source_refs': ['vsluh-2007-07-03'],
        }
    )
    raw['source_inventory'] = [
        {
            'source_id': 'vsluh-2007-07-03',
            'source_type': 'web',
            'title': 'vsluh.ru',
            'locator': 'стр. 127',
            'url': None,
        }
    ]
    proposals = [
        {
            'field_key': 'f1',
            'value': proposal_value,
            'unit': proposal_unit,
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': 'vsluh-2007-07-03',
            'source_title': 'vsluh.ru',
            'source_locator': {'page': '127'},
            'retrieval_note': 'Direct fact.',
        }
    ]
    return value, raw, [{'source_domain': 'web', 'field_proposals': proposals}]


def _same_source_patch(owner_value, owner_unit, proposal_value, proposal_unit):
    from open_webui.services.project_evidence.proposals import (
        apply_structured_external_field_proposals,
    )

    value, raw, evidence = _same_source_fixture(owner_value, owner_unit, proposal_value, proposal_unit)
    return apply_structured_external_field_proposals(value, raw, evidence)['patches'][0]


@pytest.mark.parametrize(
    ('owner_value', 'owner_unit', 'proposal_value', 'proposal_unit'),
    (
        (830000, 'тонн меди', '830000', 'тонн меди'),
        ('1978', 'год', '1978', None),
        (1978, None, '1978', 'год'),
        ('медь', None, 'Медь', None),
        ('  Медно-Молибденовые  руды ', None, 'медно-молибденовые руды', None),
    ),
)
def test_one_figure_spelled_two_ways_is_not_a_disagreement(
    owner_value,
    owner_unit,
    proposal_value,
    proposal_unit,
):
    """Eight of run `6af7479f`'s 41 conflicts were a cell conflicting with
    itself: same source, same figure, differing in JSON type, letter case, or
    a unit one side stated and the other did not."""
    patch = _same_source_patch(owner_value, owner_unit, proposal_value, proposal_unit)

    assert patch['status'] == 'filled'
    assert patch['value'] == owner_value


def test_two_stated_units_still_disagree():
    """`тонн меди` against `тонн руды` is copper against ore. The unit rule
    only forgives a unit nobody stated, never two that were."""
    patch = _same_source_patch(830000, 'тонн меди', 830000, 'тонн руды')

    assert patch['status'] == 'conflicted'
    assert patch['value'] is None


def test_a_conflict_side_names_a_source_the_merged_state_holds():
    """`merge_owner_envelopes` renames the inventory and rewrites
    `source_refs`; it left `candidates[].source_ref` pointing at the pre-merge
    id. On run `6af7479f` that was all 50 sides of 25 conflicts, so neither the
    DOCX conflict cell nor `conflict_summary` could resolve either side."""
    from open_webui.services.artifacts.geotizer.owner_envelope import merge_owner_envelopes
    from test_geotizer_orchestration import batch

    chunk = {**batch(), 'fields': [{'field_key': 'f1', 'row_id': 1}]}
    envelope = {
        'batch_id': 'GIS-DC',
        'producer': 'gis',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [
            {'source_id': 'doc-a', 'source_type': 'knowledge_base', 'title': 'A'},
            {'source_id': 'doc-b', 'source_type': 'web', 'title': 'B'},
        ],
        'patches': [
            {
                'field_key': 'f1',
                'value': None,
                'unit': None,
                'status': 'conflicted',
                'value_origin': None,
                'source_refs': ['doc-a', 'doc-b'],
                'source_locator': {
                    'policy': 'direct_disagreement_is_conflicted',
                    'candidates': [
                        {'value': 'a', 'unit': None, 'value_origin': 'direct', 'source_ref': 'doc-a', 'locator': {}},
                        {'value': 'b', 'unit': None, 'value_origin': 'direct', 'source_ref': 'doc-b', 'locator': {}},
                    ],
                },
            }
        ],
    }

    merged = merge_owner_envelopes(chunk, [chunk], [envelope], run_id='r1')
    known = {source['source_id'] for source in merged['source_inventory']}
    sides = [item['source_ref'] for item in merged['patches'][0]['source_locator']['candidates']]

    assert sides == merged['patches'][0]['source_refs']
    assert set(sides) <= known


def _resource_envelope(source_type, field_key='geotizer_object.v1.r046.a01'):
    return {
        'batch_id': 'GIS-DC',
        'producer': 'gis',
        'policy_version': 'geotizer_assignments.v1',
        'template_version': 'geotizer_object.v1',
        'source_inventory': [
            {'source_id': 's1', 'source_type': source_type, 'title': 'источник'},
        ],
        'patches': [
            {
                'field_key': field_key,
                'value': '830000',
                'unit': 'тонн руды',
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['s1'],
                'source_locator': {'page': 3},
                'retrieval_note': 'Пресс-релиз 2007 года.',
            }
        ],
    }


@pytest.mark.parametrize('field_key', (
    'geotizer_object.v1.r044.a01',
    'geotizer_object.v1.r046.a01',
    'geotizer_object.v1.r056.a03',
))
def test_a_resource_row_is_not_filled_by_a_lone_web_source(field_key):
    """48 of the 74 filled resource cells on run `05169ef1` cite web and
    nothing else. `GT-POLICY-01` puts WEB last only when two sources compete;
    alone it wins by default and no conflict rule ever reaches it."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        LONE_WEB_RESOURCE_RULE,
        refuse_lone_web_resource_values,
    )

    repaired, notes = refuse_lone_web_resource_values(_resource_envelope('web', field_key))
    patch = repaired['patches'][0]

    assert patch['status'] == 'requires_expert_review'
    assert patch['value'] is None
    assert patch['source_locator']['if_not_why_not']['rule'] == LONE_WEB_RESOURCE_RULE
    assert notes and 'WEB' in notes[0]


def test_the_refused_figure_stays_where_a_reader_can_see_it():
    """A refusal a reader cannot see is the same defect as a silent
    resolution, so the rejected value goes where a resolved conflict keeps its
    losing side."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_lone_web_resource_values,
    )

    repaired, _ = refuse_lone_web_resource_values(_resource_envelope('web'))
    locator = repaired['patches'][0]['source_locator']

    assert [(item['value'], item['unit']) for item in locator['candidates']] == [('830000', 'тонн руды')]
    assert locator['candidates'][0]['source_ref'] == 's1'
    assert 'WEB' in locator['selection_trace']


@pytest.mark.parametrize('source_type', ('knowledge_base', 'gis', 'datacube'))
def test_a_resource_row_is_still_filled_by_a_document_or_a_layer(source_type):
    """14 of those 74 came from the knowledge base and 12 from GIS. The rule
    is about what a press number cannot carry, not about sole sources."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_lone_web_resource_values,
    )

    repaired, notes = refuse_lone_web_resource_values(_resource_envelope(source_type))

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []


@pytest.mark.parametrize('field_key', (
    'geotizer_object.v1.r043.a01',
    'geotizer_object.v1.r057.a01',
    'geotizer_object.v1.r106.a02',
))
def test_a_lone_web_source_still_fills_outside_the_resource_rows(field_key):
    """A licensee's registered address from a state registry is a sound sole
    web source. The reason resources are different is that a bare tonnage has
    no category, date, author or method -- and that reasoning does not
    generalise to the rest of the card."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_lone_web_resource_values,
    )

    repaired, notes = refuse_lone_web_resource_values(_resource_envelope('web', field_key))

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []


def test_a_measured_distance_outranks_a_number_read_from_prose():
    """r078 asks how far the nearest settlement is and took `130` from a
    licence appendix, while the licence polygon and a settlements layer would
    have measured it. The hierarchy could not tell the two apart, because
    nothing said one side had actually measured."""
    from open_webui.services.project_evidence.proposals import resolve_by_source_authority

    computed = {
        'source_ref': 'gis-1',
        'value': 151.2,
        'unit': 'км',
        'value_origin': 'calculated',
        'locator': {
            'operation': 'minimum_geometry_to_geometry',
            'calculation_crs': 'EPSG:32642',
            'raw_distance_m': 151200.0,
        },
    }
    read = {
        'source_ref': 'kb-1',
        'value': 130,
        'unit': 'км',
        'value_origin': 'direct',
        'locator': {'page': '4', 'document_id': 'licence-appendix'},
    }

    winner, trace = resolve_by_source_authority([computed, read], SOURCES)

    assert winner is computed
    assert 'геометрии' in trace


def test_two_documents_are_not_settled_by_the_spatial_rule():
    """The rule fires on the presence of a computation, so a pair with none is
    the hierarchy's ordinary business and must not be decided by it."""
    from open_webui.services.project_evidence.proposals import resolve_by_source_authority

    winner, _ = resolve_by_source_authority(
        [
            {'source_ref': 'kb-1', 'value': 130, 'unit': 'км', 'value_origin': 'direct', 'locator': {'page': '4'}},
            {'source_ref': 'dc-1', 'value': 151, 'unit': 'км', 'value_origin': 'direct', 'locator': {'page': '9'}},
        ],
        SOURCES,
    )

    assert winner is None


def test_two_computations_still_need_a_person():
    """Two measurements disagreeing is a real disagreement between two things
    entitled to be believed. The rule settles measured-against-read only."""
    from open_webui.services.project_evidence.proposals import resolve_by_source_authority

    def _measured(ref, value):
        return {
            'source_ref': ref,
            'value': value,
            'unit': 'км',
            'value_origin': 'calculated',
            'locator': {'operation': 'minimum_geometry_to_geometry', 'calculation_crs': 'EPSG:32642'},
        }

    winner, _ = resolve_by_source_authority([_measured('gis-1', 151.2), _measured('dc-1', 148.9)], SOURCES)

    assert winner is None


def test_a_row_with_no_layer_to_measure_it_is_refused_not_cited():
    """`lekyn_new_data` holds no settlements layer, so r078's `130` is a number
    about some geometry read out of prose. The value is kept where a refused
    resource figure is kept, and the cell goes to a person."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        ABSENT_SPATIAL_LAYER_RULE,
        refuse_unanswerable_spatial_rows,
    )

    envelope = {
        'source_inventory': [{'source_id': 'kb-1', 'source_type': 'knowledge_base', 'title': 'Приложение'}],
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r078.a01',
                'value': 130,
                'unit': 'км',
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['kb-1'],
                'source_locator': {'page': '4'},
                'retrieval_note': 'Из приложения к лицензии.',
            }
        ],
    }
    unanswerable = [
        {
            'field_key': 'geotizer_object.v1.r078.a01',
            'roles': ['settlement'],
            'role_labels': ['населённый пункт'],
            'code': 'layer_not_found',
        }
    ]

    repaired, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)
    patch = repaired['patches'][0]

    assert patch['status'] == 'requires_expert_review'
    assert patch['value'] is None
    assert patch['source_locator']['if_not_why_not']['rule'] == ABSENT_SPATIAL_LAYER_RULE
    assert [item['value'] for item in patch['source_locator']['candidates']] == [130]
    assert 'населённый пункт' in patch['source_locator']['selection_trace']
    assert notes and 'r078' in notes[0]


def test_a_row_whose_layer_exists_is_left_alone():
    """The refusal is keyed on the absent layer, not on the block."""
    from open_webui.services.artifacts.geotizer.owner_envelope import refuse_unanswerable_spatial_rows

    envelope = {
        'source_inventory': [],
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r084.a01',
                'value': 'автомобильная дорога: 9.47 км',
                'unit': None,
                'status': 'filled',
                'value_origin': 'calculated',
                'source_refs': ['gis-1'],
                'source_locator': {'operation': 'minimum_geometry_to_geometry'},
            }
        ],
    }

    repaired, notes = refuse_unanswerable_spatial_rows(envelope, [{'field_key': 'geotizer_object.v1.r078.a01'}])

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []
