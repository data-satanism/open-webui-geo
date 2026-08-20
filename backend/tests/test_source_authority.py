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
