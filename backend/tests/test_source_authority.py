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

    merged, _ = merge_owner_envelopes(chunk, [chunk], [envelope], run_id='r1')
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


def test_the_hierarchy_is_not_inverted_by_a_measurement():
    """`Расширение использования GIS` §12 excludes «Замена документальной
    иерархии источников принципом "GIS всегда главнее"», and an earlier version
    of this module did exactly that: a candidate carrying `calculation_crs`
    short-circuited `resolve_by_source_authority` and beat any documentary
    source. §5.4 rule 8 is narrower -- the document may still outrank, and what
    must change is that the computed candidate and the divergence survive into
    the report."""
    from open_webui.services.project_evidence.proposals import resolve_by_source_authority

    winner, trace = resolve_by_source_authority([_computed_distance(), _read_distance()], SOURCES)

    assert winner is None, 'a measurement must not outrank a document by itself'
    assert trace == ''


def _computed_distance():
    return {
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


def _read_distance():
    return {
        'source_ref': 'kb-1',
        'value': 130,
        'unit': 'км',
        'value_origin': 'direct',
        'locator': {'page': '4', 'document_id': 'licence-appendix'},
    }


def test_a_measured_and_a_read_value_are_named_as_a_divergence():
    """§5.4 rule 8's actual requirement. `candidates` already carries both
    sides; nothing said which of them measured, so a reader of r078 sees two
    numbers and no reason to prefer either."""
    from open_webui.services.project_evidence.proposals import spatial_divergence

    record = spatial_divergence([_computed_distance(), _read_distance()])

    assert record['kind'] == 'computed_against_read'
    assert record['measured'][0]['value'] == 151.2
    assert record['measured'][0]['operation'] == 'minimum_geometry_to_geometry'
    assert record['read'][0]['value'] == 130


def test_a_pair_with_no_computation_is_not_a_spatial_divergence():
    """Two documents disagreeing is an ordinary conflict and must not be
    dressed as a computed-against-read one."""
    from open_webui.services.project_evidence.proposals import spatial_divergence

    assert spatial_divergence([_read_distance(), {**_read_distance(), 'source_ref': 'dc-1'}]) is None


def test_two_computations_are_not_a_divergence_of_this_kind():
    """Two measurements disagreeing is a real disagreement between two things
    entitled to be believed, and needs a person, not this record."""
    from open_webui.services.project_evidence.proposals import spatial_divergence

    second = {**_computed_distance(), 'source_ref': 'dc-1', 'value': 148.9}

    assert spatial_divergence([_computed_distance(), second]) is None


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


def _measured_patch_fixture():
    """Run `08330f72`, cell D85, as the pipeline actually produced it.

    The GIS pass filled `r084.a01` with a road measured at 0.0 m from the
    licence polygon. The KB/WEB pass then arrived with «п. Полярный» for the
    same cell, read out of a GRR project document.

    The document is entitled to win -- `Расширение использования GIS` §12
    excludes «GIS всегда главнее» and §5.4 rule 8 asks only that the computed
    candidate and the divergence survive into the report. What the run did
    instead was overwrite the patch whole: value, `source_refs`, locator and
    note all replaced, leaving no evidence on the cell that a measurement had
    ever been made. Eight of this run's twelve GIS proposals disappeared that
    way -- `r084.a01`-`a05`, `r085.a01` and `r088.a02`-`a03` -- and the only
    reason it is visible at all is that `sources` still holds seventeen
    `gis-infrastructure-*` entries that no field references.
    """
    from test_geotizer_orchestration import batch, envelope

    value = batch()
    raw = envelope()
    del raw['patches'][1:]
    raw['patches'][0].update(
        {
            'field_key': 'f1',
            'value': 'автомобильная дорога: автомобильная дорога row:17; 0.0 км',
            'unit': None,
            'status': 'filled',
            'value_origin': 'calculated',
            'source_refs': ['gis-measured'],
            'source_locator': {
                'operation': 'minimum_geometry_to_geometry',
                'calculation_crs': 'EPSG:32642',
                'raw_distance_m': 0.0,
                'semantic_role': 'road',
                'target_feature_id': 'row:17',
            },
        }
    )
    raw['source_inventory'] = [
        {
            'source_id': 'gis-measured',
            'source_type': 'gis',
            'title': 'GIS infrastructure calculation: road',
            'locator': 'road row:17',
            'url': None,
        }
    ]
    proposals = [
        {
            'field_key': 'f1',
            'value': 'п. Полярный',
            'unit': None,
            'value_origin': 'direct',
            'relation_to_object': 'direct',
            'source_id': 'grr-project',
            'source_title': 'Проект ГРР',
            'source_locator': {'page': 12, 'document_id': 'grr'},
            'retrieval_note': 'Прямая выгрузка из проекта ГРР: п. Полярный (60 км).',
        }
    ]
    return value, raw, [{'source_domain': 'kb', 'field_proposals': proposals}]


def _measured_patch_result():
    from open_webui.services.project_evidence.proposals import (
        apply_structured_external_field_proposals,
    )

    value, raw, evidence = _measured_patch_fixture()
    return apply_structured_external_field_proposals(value, raw, evidence)


def test_a_document_may_take_a_measured_cell_but_not_erase_the_measurement():
    """§5.4 rule 8. The document wins -- that part is §12 and is not in
    question -- and the measurement it displaced is still on the cell."""
    patch = _measured_patch_result()['patches'][0]

    assert patch['value'] == 'п. Полярный', 'the documentary hierarchy is unchanged'
    divergence = patch['source_locator'].get('spatial_divergence')
    assert divergence is not None, 'the displaced measurement left no record'
    assert divergence['kind'] == 'computed_against_read'
    assert divergence['measured'][0]['operation'] == 'minimum_geometry_to_geometry'
    assert divergence['measured'][0]['calculation_crs'] == 'EPSG:32642'
    assert divergence['read'][0]['value'] == 'п. Полярный'


def test_the_displaced_measurement_keeps_a_source_ref_that_resolves():
    """A record whose `source_ref` cannot be found in `state.sources` is the
    defect `merge_owner_envelopes` produced on 50 conflict sides of run
    `6af7479f`. The measurement's source stays cited by the cell."""
    result = _measured_patch_result()
    patch = result['patches'][0]
    known = {str(source.get('source_id') or '') for source in result['source_inventory']}

    ref = patch['source_locator']['spatial_divergence']['measured'][0]['source_ref']
    assert ref in known
    assert ref in patch['source_refs']


def test_the_note_says_a_measurement_was_displaced():
    """`spatial_divergence` is in `state.json` and nothing renders it. The note
    is the one field that reaches both the XLSX and the DOCX card, so the
    geologist reading the cell can see that a computed value exists."""
    patch = _measured_patch_result()['patches'][0]

    assert 'GIS' in patch['retrieval_note']
    assert 'п. Полярный' in patch['retrieval_note'], 'the winning value keeps its own note'


def test_a_displaced_documentary_value_is_not_dressed_as_a_divergence():
    """Only a measurement is one. An ordinary document-over-document overwrite
    must not acquire this record."""
    from open_webui.services.project_evidence.proposals import (
        apply_structured_external_field_proposals,
    )

    value, raw, evidence = _measured_patch_fixture()
    raw['patches'][0].update({'value_origin': 'direct', 'source_locator': {'page': 3}})

    patch = apply_structured_external_field_proposals(value, raw, evidence)['patches'][0]

    assert 'spatial_divergence' not in patch['source_locator']


def test_a_measurement_that_cannot_take_the_cell_is_still_recorded():
    """The mirror of the case above, and r078's actual history: a document
    filled the cell first and `_proposal_may_replace_patch` keeps a calculated
    value out of it. §12 says that is right; §5.4 rule 8 says the measurement
    still has to be visible."""
    from open_webui.services.project_evidence.proposals import (
        apply_structured_gis_field_proposals,
    )
    from test_geotizer_orchestration import batch, envelope

    value = batch()
    raw = envelope()
    del raw['patches'][1:]
    raw['patches'][0].update(
        {
            'field_key': 'f1',
            'value': 130,
            'unit': 'км',
            'status': 'filled',
            'value_origin': 'direct',
            'source_refs': ['owner-src'],
            'source_locator': {'page': 188, 'document_id': 'licence-appendix'},
        }
    )
    raw['source_inventory'] = [
        {'source_id': 'owner-src', 'source_type': 'knowledge_base', 'title': 'Лицензия'}
    ]
    evidence = [
        {
            'source_domain': 'gis',
            'field_proposals': [
                {
                    'field_key': 'f1',
                    'value': 151.2,
                    'unit': 'км',
                    'value_origin': 'calculated',
                    'relation_to_object': 'direct',
                    'source_id': 'gis-infrastructure-abc',
                    'source_title': 'GIS infrastructure calculation: settlement',
                    'source_locator': {
                        'operation': 'minimum_geometry_to_geometry',
                        'calculation_crs': 'EPSG:32642',
                        'raw_distance_m': 151200.0,
                    },
                    'retrieval_note': 'Calculated minimum distance.',
                }
            ],
        }
    ]

    result = apply_structured_gis_field_proposals(value, raw, evidence)
    patch = result['patches'][0]
    known = {str(source.get('source_id') or '') for source in result['source_inventory']}

    assert patch['value'] == 130, 'the document keeps the cell'
    divergence = patch['source_locator']['spatial_divergence']
    assert divergence['measured'][0]['value'] == 151.2
    assert divergence['read'][0]['value'] == 130
    assert divergence['measured'][0]['source_ref'] in known
    assert divergence['measured'][0]['source_ref'] in patch['source_refs']


def test_the_run_says_how_many_cells_hold_a_measurement_they_did_not_use():
    """A per-cell key in `state.json` is not a thing a reader goes looking for.
    Run `08330f72` lost eight measurements and the only way to see it was to
    count `gis-infrastructure-*` sources against the fields citing them."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        spatial_divergence_notes,
    )

    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r084.a01',
                'source_locator': {'spatial_divergence': {'kind': 'computed_against_read'}},
            },
            {'field_key': 'geotizer_object.v1.r084.a02', 'source_locator': {'page': 3}},
        ]
    }

    notes = spatial_divergence_notes(envelope)

    assert len(notes) == 1
    assert '1 ячеек' in notes[0]
    assert 'geotizer_object.v1.r084.a01' in notes[0]
    assert spatial_divergence_notes({'patches': []}) == []


def test_a_conflict_the_owner_declared_without_sides_says_so():
    """Fourteen of run `08330f72`'s twenty-seven conflicts were declared in the
    owner's own patch with two or three `source_refs` and no record of what any
    of those sources said. The DOCX conflict cell prints `candidates`, so the
    card showed «КОНФЛИКТ — ТРЕБУЕТ РАЗРЕШЕНИЯ» with nothing under it."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        record_unrecorded_conflicts,
    )

    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r045.a01',
                'status': 'conflicted',
                'value': None,
                'source_refs': ['kb-a', 'kb-b'],
                'source_locator': {'entity_scope': 'ore_field'},
            },
            {
                'field_key': 'geotizer_object.v1.r005.a01',
                'status': 'conflicted',
                'value': None,
                'source_refs': ['kb-a', 'kb-b'],
                'source_locator': {'candidates': [{'value': 'R-42'}, {'value': 'Q-42'}]},
            },
        ]
    }

    repaired, notes = record_unrecorded_conflicts(envelope)
    first, second = repaired['patches']

    assert first['status'] == 'conflicted', 'the status is the owner’s and is not repaired'
    assert first['source_locator']['policy'] == 'owner_declared_conflict_without_candidates'
    assert 'kb-a, kb-b' in first['source_locator']['selection_trace']
    assert 'selection_trace' not in second['source_locator'], 'a recorded conflict is left alone'
    assert len(notes) == 1
    assert '1 конфликтных ячеек' in notes[0]


def test_an_envelope_with_no_conflicts_gets_no_note():
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        record_unrecorded_conflicts,
    )

    repaired, notes = record_unrecorded_conflicts(
        {'patches': [{'field_key': 'f1', 'status': 'filled', 'value': 'x'}]}
    )

    assert notes == []
    assert repaired['patches'][0]['status'] == 'filled'


def _radius_patch(field_key, value, divergence=None):
    locator = {'page': 12}
    if divergence is not None:
        locator['spatial_divergence'] = divergence
    return {
        'field_key': field_key,
        'value': value,
        'unit': None,
        'status': 'filled',
        'value_origin': 'direct',
        'source_refs': ['doc-1'],
        'source_locator': locator,
    }


def _road_divergence(value):
    return {
        'kind': 'computed_against_read',
        'measured': [{'value': value, 'unit': None, 'source_ref': 'gis-1'}],
        'read': [{'value': 'документ', 'source_ref': 'doc-1'}],
    }


def test_a_value_that_says_it_is_130_km_away_cannot_fill_the_50_km_row():
    """Run `84afa9e2`, cells D85-F85. Three of r084's five cells held objects
    at 70-130 km under a heading that asks for 50, and each had displaced a
    road this project measured. The measurement takes the cell back -- not
    because GIS outranks a document, which §12 excludes, but because the
    document lost to the question the row asks."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    envelope = {
        'patches': [
            _radius_patch(
                'geotizer_object.v1.r084.a01',
                'г. Лабытнанги (130 км)',
                _road_divergence('автомобильная дорога row:17; 0.0 км'),
            )
        ]
    }

    repaired, notes = refuse_out_of_radius_infrastructure(envelope)
    patch = repaired['patches'][0]

    assert patch['status'] == 'filled'
    assert patch['value'] == 'автомобильная дорога row:17; 0.0 км'
    assert patch['value_origin'] == 'calculated'
    assert patch['source_refs'][0] == 'gis-1'
    assert patch['source_locator']['policy'] == 'out_of_radius_value_replaced_by_measurement'
    refused = patch['source_locator']['candidates'][-1]
    assert refused['value'] == 'г. Лабытнанги (130 км)'
    assert refused['locator']['stated_distance_km'] == 130.0
    assert refused['locator']['row_radius_km'] == 50.0
    assert '1 ячеек' in notes[0]


def test_an_out_of_radius_value_with_no_measurement_goes_to_a_person():
    """`not_found` would say nobody found anything. Somebody did, and it does
    not answer this row."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        OUT_OF_RADIUS_RULE,
        refuse_out_of_radius_infrastructure,
    )

    envelope = {'patches': [_radius_patch('geotizer_object.v1.r084.a01', 'г. Воркута (130 км)')]}

    repaired, notes = refuse_out_of_radius_infrastructure(envelope)
    patch = repaired['patches'][0]

    assert patch['status'] == 'requires_expert_review'
    assert patch['value'] is None
    assert patch['value_origin'] is None
    assert OUT_OF_RADIUS_RULE in patch['source_locator']['selection_trace']
    assert patch['source_locator']['candidates'][-1]['value'] == 'г. Воркута (130 км)'
    assert 'передано эксперту' in notes[0]


def test_a_value_inside_the_radius_keeps_its_cell_against_a_measurement():
    """The half that makes this not a hierarchy change. A document stating a
    distance the row accepts wins, measurement or no measurement."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    envelope = {
        'patches': [
            _radius_patch(
                'geotizer_object.v1.r084.a01',
                'п. Полярный (30 км)',
                _road_divergence('автомобильная дорога row:17; 0.0 км'),
            )
        ]
    }

    repaired, notes = refuse_out_of_radius_infrastructure(envelope)

    assert repaired['patches'][0]['value'] == 'п. Полярный (30 км)'
    assert notes == []


def test_a_value_stating_no_distance_is_left_alone():
    """«п. Полярный» says nothing about how far away it is, and a rule that
    guessed would be parsing prose. Untouched."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    envelope = {
        'patches': [
            _radius_patch(
                'geotizer_object.v1.r085.a01',
                'п. Полярный',
                _road_divergence('автомобильная дорога row:11; 51.293 км'),
            )
        ]
    }

    repaired, notes = refuse_out_of_radius_infrastructure(envelope)

    assert repaired['patches'][0]['value'] == 'п. Полярный'
    assert notes == []


def test_a_range_is_read_at_its_nearest_end():
    """«70–130 км» is refused by the 50 km row and accepted by the 100 km one:
    the nearest end is the reading most favourable to keeping the value."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        stated_distance_km,
    )

    assert stated_distance_km('ж/д ветка (70–130 км)') == 70.0
    assert stated_distance_km('в 60 км к северу') == 60.0
    assert stated_distance_km('расстояние 60-300 км') == 60.0
    assert stated_distance_km('автомобильная дорога row:13; 40.813 км') == 40.813
    assert stated_distance_km('п. Полярный') is None
    assert stated_distance_km(130) is None


def test_an_empty_cell_on_an_unanswerable_row_is_told_why():
    """Run `6e68eeec` shipped r079, r080, r082 and r083 reading «Значение не
    найдено. Где искали: Web search: no data.» — true, and an invitation to
    search again. No layer in a 34-layer project can answer those rows, which
    is permanent, and the cell did not say so.

    Stamped, not restatused: `requires_expert_review` is for a cell where a
    documentary value was refused and a person may still know. Here nobody
    found anything, so `not_found` is the honest status and the reason is what
    was missing.
    """
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
    )

    unanswerable = [
        {
            'field_key': 'geotizer_object.v1.r082.a01',
            'roles': ['port'],
            'role_labels': ['порт'],
            'code': 'layer_not_found',
            'code_meaning_ru': 'В проекте нет слоя для этой роли.',
        }
    ]
    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r082.a01',
                'value': None,
                'status': 'not_found',
                'source_refs': ['web'],
                'retrieval_note': 'Значение не найдено. Где искали: Web search: no data.',
                'source_locator': {'relation_to_object': 'direct'},
            }
        ]
    }
    repaired, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)
    patch = repaired['patches'][0]

    assert patch['status'] == 'not_found'
    assert patch['value'] is None
    assert patch['source_locator']['absence_code'] == 'layer_not_found'
    # The sentence is the contract's own `code_meaning_ru`, carried on the
    # item. A second wording here would be the catalogue transcribed into a
    # Python string.
    assert patch['retrieval_note'].endswith('В проекте нет слоя для этой роли.')
    assert 'Web search: no data' in patch['retrieval_note']
    assert 'Роли: порт' in patch['retrieval_note']
    assert notes and 'layer_not_found' in notes[0]


def test_an_unanswerable_row_the_run_never_reached_is_left_alone():
    """A status that is neither filled nor not_found is somebody else's."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
    )

    unanswerable = [
        {
            'field_key': 'geotizer_object.v1.r082.a01',
            'role_labels': ['порт'],
            'code': 'layer_not_found',
            'code_meaning_ru': 'В проекте нет слоя для этой роли.',
        }
    ]
    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r082.a01',
                'value': None,
                'status': 'agent_contract_failed',
                'source_refs': ['web'],
                'source_locator': {},
            }
        ]
    }
    repaired, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)

    assert repaired['patches'][0]['status'] == 'agent_contract_failed'
    assert notes == []


def test_every_absence_code_the_catalogue_names_has_a_sentence():
    """The rendering keyed on two code names and fell back to
    `layer_not_found` for anything else, so a third code would have rendered as
    «в проекте нет слоя» — the opposite of what it means.

    `only_the_source_feature_in_layer` is run `6e68eeec`'s: `licence` and
    `subsoil_user` measure against a layer of exactly one feature, the run's
    own licence, and «there are no other licences» is an answer rather than an
    obstacle.
    """
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        ABSENCE_NOTE_RU,
        ABSENCE_TRACE_RU,
    )

    codes = {
        'layer_not_found',
        'no_labelled_feature_in_layer',
        'only_the_source_feature_in_layer',
    }

    assert set(ABSENCE_TRACE_RU) == codes
    assert set(ABSENCE_NOTE_RU) == codes
    assert len({*ABSENCE_TRACE_RU.values()}) == len(codes)
    assert len({*ABSENCE_NOTE_RU.values()}) == len(codes)
    # The one that is an answer must not read like the one that is an obstacle.
    assert 'нет слоя' not in ABSENCE_TRACE_RU['only_the_source_feature_in_layer']
    assert 'истинное отсутствие' in ABSENCE_TRACE_RU['only_the_source_feature_in_layer']


def test_the_note_is_read_when_the_value_names_no_distance():
    """Where the first shape of the rule could not look.

    Of 176 filled r084/r085 cells across eighteen exported runs, 143 state the
    distance in the value and **28 state it only in the note -- twelve of them
    outside their row's radius**. All five filled r084 cells of run `d0a464be`
    are among the twelve: «ж/д ветка Обская – Бованенково» on the 50 km row,
    with a note reading «Прямая оценка из лицензии: … в 70 км».
    """
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        note_distance_km,
    )

    assert note_distance_km('Прямая оценка из лицензии: … в 70 км.', limit_km=50.0) == 70.0
    assert note_distance_km('п. Полярный (в диапазоне 60-300 км)', limit_km=50.0) == 60.0
    assert note_distance_km('точка доступа, расстояния нет', limit_km=50.0) is None

    # The row's own radius restated. «Населенный пункт в радиусе 100 км» is
    # five cells of run `92661b9b` and says nothing about where the object is;
    # reading it as the object's distance is a misread in both directions.
    # Dropping it costs nothing even when it is the real distance, because a
    # distance equal to the limit is inside it.
    assert note_distance_km('Населенный пункт в радиусе 100 км', limit_km=100.0) is None
    assert (
        note_distance_km('в радиусе 50 км (фактически 70 км)', limit_km=50.0) == 70.0
    )
    # But a radius that is not the row's is the object's bound and still counts:
    # «Населённый пункт в радиусе 130 км» on the 50 km row.
    assert note_distance_km('Населённый пункт в радиусе 130 км', limit_km=50.0) == 130.0


def test_the_measurement_this_run_wrote_into_the_note_is_not_the_object_s_distance():
    """When a computed candidate is displaced the run writes the measurement
    into the note, so the note holds two distances: the object's, from the
    specialist, and the measurement's, from this pipeline. On r084.a01 of run
    `d0a464be` those are 70 km for a railway and 0.0 km for a road, and reading
    the nearer of them answers the radius question about a different object.
    """
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        _measured_distances_km,
        note_distance_km,
    )

    locator = {
        'spatial_divergence': {
            'kind': 'computed_against_read',
            'measured': [{'value': 'автомобильная дорога row:17; 0.0 км'}],
        }
    }
    note = (
        'Прямая оценка из лицензии: ж/д ветка Обская – Бованенково в 70 км. '
        'Расчёт GIS для этой ячейки не выбран: автомобильная дорога row:17; 0.0 км.'
    )

    assert _measured_distances_km(locator) == {0.0}
    assert note_distance_km(note, limit_km=50.0) == 0.0
    assert (
        note_distance_km(note, limit_km=50.0, measured_km=_measured_distances_km(locator))
        == 70.0
    )


def test_a_note_distance_refusal_says_which_field_stated_it():
    """«the value says 70 km» and «the value names an object the note places at
    70 km» are different statements, and the reviewer is reading the one the
    cell makes."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    envelope = {
        'patches': [
            {
                'field_key': 'geotizer_object.v1.r084.a01',
                'value': 'ж/д ветка Обская – Бованенково',
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['doc'],
                'retrieval_note': 'Прямая оценка из лицензии: ж/д ветка в 70 км.',
                'source_locator': {'relation_to_object': 'direct'},
            }
        ]
    }
    repaired, notes = refuse_out_of_radius_infrastructure(envelope)
    patch = repaired['patches'][0]
    refused = patch['source_locator']['candidates'][0]

    assert patch['status'] == 'requires_expert_review'
    assert refused['locator']['stated_distance_km'] == 70.0
    assert refused['locator']['stated_distance_read_from'] == 'retrieval_note'
    assert 'расстояния не называет' in patch['source_locator']['selection_trace']
    assert notes


def test_only_the_two_radius_rows_are_governed():
    """r078 asks for the nearest settlement and states its distance as the
    answer. Refusing that for being far away would delete the answer."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_out_of_radius_infrastructure,
    )

    envelope = {'patches': [_radius_patch('geotizer_object.v1.r078.a01', '130 км')]}

    repaired, notes = refuse_out_of_radius_infrastructure(envelope)

    assert repaired['patches'][0]['status'] == 'filled'
    assert notes == []


def _unanswerable_envelope(code, labels):
    return (
        {
            'patches': [
                {
                    'field_key': 'geotizer_object.v1.r086.a01',
                    'value': 'СЛХ 025834 ТП',
                    'unit': None,
                    'status': 'filled',
                    'value_origin': 'direct',
                    'source_refs': ['doc-1'],
                    'source_locator': {'page': 4},
                }
            ]
        },
        [
            {
                'field_key': 'geotizer_object.v1.r086.a01',
                'roles': ['licence'],
                'role_labels': labels,
                'code': code,
            }
        ],
    )


def test_a_layer_with_unnamed_features_is_not_reported_as_a_missing_layer():
    """Stage 2. `gis_service` reports two absences and only one used to reach
    this side: run `08330f72` produced 18 `layer_not_found` and 4
    `no_labelled_feature_in_layer`, and the second was on the trace entry and
    nowhere a rule could read it. §4.2 says a missing layer is a technical
    absence; a layer that is there whose features carry no name is a defect in
    the project data, which the reviewer can fix and should be told about."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
    )

    envelope, unanswerable = _unanswerable_envelope('no_labelled_feature_in_layer', ['лицензия'])

    repaired, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)
    patch = repaired['patches'][0]

    assert patch['status'] == 'requires_expert_review'
    assert patch['source_locator']['absence_code'] == 'no_labelled_feature_in_layer'
    assert 'нет названия' in patch['source_locator']['selection_trace']
    assert 'дефект данных' in patch['source_locator']['selection_trace']
    assert notes == [
        '1 ячеек: слой в проекте есть, но объекты в нём без названий — измерение '
        "не приписано, значение отклонено правилом "
        "'spatial_question_needs_a_spatial_answer' и передано эксперту "
        '(geotizer_object.v1.r086.a01).'
    ]


def test_a_missing_layer_still_reads_as_a_missing_layer():
    """The other half, unchanged. A rule that renamed this absence while adding
    the second would move a sentence the card has printed for three runs."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
    )

    envelope, unanswerable = _unanswerable_envelope('layer_not_found', ['лицензия'])

    repaired, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)

    assert repaired['patches'][0]['source_locator']['absence_code'] == 'layer_not_found'
    assert 'нет слоя' in repaired['patches'][0]['source_locator']['selection_trace']
    assert 'инфраструктурных ячеек' in notes[0]


def test_the_two_absences_are_counted_separately():
    """One note apiece. A single count would put a data-quality problem and a
    coverage gap behind the same number, which is what hid four of run
    `08330f72`'s twenty-two failures inside the other eighteen."""
    from open_webui.services.artifacts.geotizer.owner_envelope import (
        refuse_unanswerable_spatial_rows,
    )

    envelope = {
        'patches': [
            {
                'field_key': key,
                'value': 'что-то',
                'status': 'filled',
                'value_origin': 'direct',
                'source_refs': ['doc-1'],
                'source_locator': {},
            }
            for key in ('geotizer_object.v1.r086.a01', 'geotizer_object.v1.r078.a01')
        ]
    }
    unanswerable = [
        {
            'field_key': 'geotizer_object.v1.r086.a01',
            'roles': ['licence'],
            'role_labels': ['лицензия'],
            'code': 'no_labelled_feature_in_layer',
        },
        {
            'field_key': 'geotizer_object.v1.r078.a01',
            'roles': ['settlement'],
            'role_labels': ['населённый пункт'],
            'code': 'layer_not_found',
        },
    ]

    _, notes = refuse_unanswerable_spatial_rows(envelope, unanswerable)

    assert len(notes) == 2
    assert any('инфраструктурных ячеек' in note for note in notes)
    assert any('без названий' in note for note in notes)
