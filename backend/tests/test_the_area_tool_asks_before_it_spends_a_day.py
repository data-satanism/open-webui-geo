"""The area tool's four outcomes, and the one that costs a day if it is wrong.

`fill_geoteaser_area` resolves licences, fills each as its own object, folds
the result and renders it. Three of its outcomes are answers a user reads and
never a run: a question when a name is ambiguous, a refusal when a number
resolves to nothing, and a refusal when the area is larger than the deadline.

That third one is the whole of §3 until the job model exists. A tool that
accepts twenty-one members and dies at hour four has lost a day and produced
nothing; one that refuses in a second has cost nothing and said why.
"""

from __future__ import annotations

from unittest import mock

import pytest

from open_webui.services.artifacts.geotizer.area_workflow import (
    run_geotizer_area_workflow,
)
from open_webui.services.artifacts.geotizer.area_request import (
    LICENCE_AMBIGUOUS,
    LICENCE_NOT_FOUND,
    MANIFEST_WITHOUT_MEMBERS,
    MISSING_CONTRACT,
    NOTHING_TO_RESOLVE,
    SEARCH_UNREADABLE,
    LAYER_NOT_AMONG_CANDIDATES,
    CRS_NOT_RECOGNISED,
    NAME_SEARCH_HAS_NO_POLYGON,
    NO_CENTROID,
    REFUSED,
    RESOLVED,
    contract_line,
    epsg_code,
    is_projected,
    resolve_calculation_crs,
    utm_zone_for,
    TOO_MANY_MEMBERS,
    ASK,
    cost_phrase,
    fill_area,
    member_ceiling,
    render_area_answer,
    resolve_contract,
    resolve_area_members,
)

POLICY = 'geotizer_area_aggregation.v1'
CRS = 'EPSG:32642'


#: The actions `geotizer_fill` actually declares, copied from
#: `gis_service/arcgis_mcp/geotizer/api.py::GeotizerFillRequest`. The area
#: actions are deliberately absent, because they are absent there.
FILL_ACTIONS = frozenset({
    'start',
    'resolve_scope',
    'infrastructure_proposals',
    'grr_schedule_proposals',
    'validate_batch',
    'submit_batch',
    'finalize',
    'get',
    'list_runs',
})


class Service:
    """Three operations on the tool server, each refusing what the real one does.

    The first version of this fake was one callable that answered any action,
    which let `fill_area` send `resolve_area_scope` and `fold_area` to
    `geotizer_fill` and be answered. In production that is a 422 at the second
    call of every area fill: those are separate operations with separate
    request models, and `geotizer_fill`'s action set contains neither.

    A fake that accepts what the real endpoint refuses is not a stand-in for
    it; it is a second bug agreeing with the first. So each call here refuses
    an action that does not belong to it, and the original defect fails this
    file rather than passing it.
    """

    def __init__(self, **entries):
        self.entries = entries
        self.fold_payload = None
        self.scope_payload = None

    async def fill(self, payload):
        action = payload['action']
        if action not in FILL_ACTIONS:
            raise AssertionError(f'geotizer_fill has no action {action!r}')
        if action == 'resolve_scope':
            return {
                'workflow_status': 'ok',
                'scope_resolution': {
                    'candidates': self.entries.get(payload['query'], []),
                    'searched_projects': 49026,
                },
            }
        raise AssertionError(f'unexpected fill action {action!r}')

    async def scope(self, payload):
        """The manifest `resolve_area_scope` really returns.

        Its member list is keyed `entities`, and there is no `area_id` -- the
        id is `area_scope_id`. The first version of this fake invented
        `members`, so `fill_area` read a key the service never sends, merged
        an empty list, and filled zero members while reporting success. The
        fake agreed with the bug, which is the whole failure mode this file
        was rewritten once already to stop repeating.
        """
        assert payload['action'] == 'resolve_area_scope', payload['action']
        self.scope_payload = payload
        return {
            'schema_version': 1,
            'area_scope_id': payload['area_scope_id'],
            'project_id': payload['project_id'],
            'policy_version': payload['policy_version'],
            'entities': [
                {
                    'entity_id': m['entity_id'],
                    'entity_type': m['entity_type'],
                    'name': m['name'],
                    'reality_status': 'real',
                    'geometry_ref': None,
                    'source_refs': [],
                }
                for m in payload['members']
            ],
            'relations': [],
            'root_entity_ids': [],
            'unresolved_entities': [],
            'totals': {'entities': len(payload['members']), 'relations': 0},
        }

    async def fold(self, payload):
        assert payload['action'] == 'fold_area', payload['action']
        self.fold_payload = payload
        return {
            'policy_version': POLICY,
            'aggregation': {'counts': {'aggregated': 7}},
            'summary': {'members': payload['members']},
            'summary_markdown': '## Свод площади\n\n7 строк сведено.',
        }


def registry(**entries):
    return Service(**entries)


#: Магаданская область, where the first real area call lives. `licence_centroid`
#: returns degrees in EPSG:4326, and these are the coordinates the worked
#: example in the task resolves to EPSG:32656.
MAGADAN = (150.8, 61.6)


def licence(number, project='p1', name='', layer='L1', centroid=MAGADAN):
    """A candidate as `find_licence_across_projects` returns one.

    `centroid_lon`/`centroid_lat` are there because the real candidate now
    carries them: the area path resolves `calculation_crs` from the zone of the
    members' centroid, and a fixture without them would exercise only the
    refusal. `centroid=None` is the licence whose row would not read.
    """
    record = {'project_id': project, 'licence_id': number, 'licence_layer_id': layer}
    if name:
        record['object_name'] = name
    if centroid is not None:
        record['centroid_lon'], record['centroid_lat'] = centroid
    return record


def project_match(project_id, name, layers=1):
    """A candidate as a NAME search returns one — and it has no licence number.

    `looks_like_licence_number` is false for «Лекын-Тальбейская площадь», so
    the real `resolve_scope` goes through `resolve_project` and yields
    `{project_id, object_name, layers_count}`. `licence_id` never appears on
    that branch. Using licence-shaped candidates for a name search left the
    `project_id` fallback in `_candidate_line` and `_member` untested — the
    exact shape a real ambiguous area name produces.
    """
    return {'project_id': project_id, 'object_name': name, 'layers_count': layers}


async def fill(*, object_name, project_id=None, **_):
    if object_name == 'СЛХ025834ТП':
        raise RuntimeError('specialist timeout')
    return {
        'run_id': f'run-{object_name}',
        'status': 'finalized',
        'audit': {'completeness': {'filled': 190, 'of': 351}},
    }


@pytest.mark.asyncio
async def test_supplied_numbers_are_not_searched_for_and_not_asked_about():
    """«заполни область из лицензий А, Б, В» is three numbers and no ambiguity.

    A tool that searched anyway would turn an unambiguous request into a
    question, which is the same discourtesy as guessing pointed the other way.
    """
    gis = registry(МАГ03394БЭ=[licence('МАГ03394БЭ')], СЛХ025834ТП=[licence('СЛХ025834ТП')])

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=['МАГ03394БЭ', 'СЛХ025834ТП']
    )

    assert answer['status'] == RESOLVED
    assert answer['resolved_from'] == 'supplied'
    assert [m['entity_id'] for m in answer['members']] == ['МАГ03394БЭ', 'СЛХ025834ТП']


@pytest.mark.asyncio
async def test_one_number_that_resolves_to_nothing_refuses_the_whole_area():
    """Filling two of three gives an area whose `members_total` is 2 when three
    were asked for, and every folded figure is then honest about a membership
    the user did not choose. The fold would be right and the answer wrong."""
    gis = registry(МАГ03394БЭ=[licence('МАГ03394БЭ')], АНД99999БЭ=[])

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=['МАГ03394БЭ', 'АНД99999БЭ']
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_NOT_FOUND
    assert answer['licence_id'] == 'АНД99999БЭ'
    # Both are named, so a reader can see which of the two failed.
    assert 'МАГ03394БЭ — найдена' in answer['message']
    assert 'АНД99999БЭ — не найдена' in answer['message']


@pytest.mark.asyncio
async def test_a_number_in_several_layers_refuses_rather_than_picking():
    gis = registry(ДВА00000БЭ=[
        licence('ДВА00000БЭ', layer='Licenses_2024_2025'),
        licence('ДВА00000БЭ', layer='Licenses_annul'),
    ])

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['ДВА00000БЭ'])

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_AMBIGUOUS


@pytest.mark.asyncio
async def test_the_multi_layer_refusal_names_its_layers():
    """It used to COUNT them — «найдена в нескольких слоях (5)».

    A count is a dead end where a next step would fit, the same defect as
    `candidates: []`. Five names can be acted on; five cannot. The object tool's
    own refusal has named its layers since it gained `licence_layer_id`.
    """
    gis = registry(МАГ03395БЭ=[
        licence('МАГ03395БЭ', layer='Licenses_2024_2025'),
        licence('МАГ03395БЭ', layer='Licenses_annul'),
        licence('МАГ03395БЭ', layer='Juniors'),
    ])

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['МАГ03395БЭ'])
    message = answer['message']

    assert answer['layers'] == ['Licenses_2024_2025', 'Licenses_annul', 'Juniors']
    for layer in answer['layers']:
        assert layer in message
    # And what each of them means, where this registry's states are known.
    assert 'действующие' in message and 'аннулированные' in message
    # The argument that answers it, named where the reader is.
    assert 'licence_layers' in message
    # And why they are not merged, because «choose one» invites «merge them».
    assert 'не объединяются' in message


@pytest.mark.asyncio
async def test_two_rows_in_one_layer_do_not_get_a_layer_instruction():
    """`find_licence_across_projects` searches every project the store holds,
    so one number in one layer in two projects is a shape it produces by
    design.

    Listing LAYERS rather than rows printed «найдена в 1 слоях» directly above
    an ambiguity refusal, and then told the reader to pick a layer — which
    narrows those two rows to the same two rows and refuses again. An
    instruction whose own outcome is this refusal is a dead end wearing the
    shape of a next step.
    """
    gis = registry(МАГ03395БЭ=[
        licence('МАГ03395БЭ', project='p1', layer='Licenses_2024_2025'),
        licence('МАГ03395БЭ', project='p2', layer='Licenses_2024_2025'),
    ])

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['МАГ03395БЭ'])
    message = answer['message']

    assert answer['reason'] == LICENCE_AMBIGUOUS
    assert 'найдена 2 раз' in message
    assert 'p1' in message and 'p2' in message
    # The instruction that cannot work is not given.
    assert 'Укажите, какой слой' not in message
    assert 'Слой их не различает' in message


@pytest.mark.asyncio
async def test_a_row_with_no_layer_name_is_listed_and_said_to_be_unselectable():
    """It counts towards the ambiguity, so leaving it out of the refusal
    describes a smaller problem than the one being refused — and
    `licence_layers` can never select it, because an empty qualifier is not
    read at all."""
    gis = registry(МАГ03395БЭ=[
        licence('МАГ03395БЭ', layer='Licenses_2024_2025'),
        licence('МАГ03395БЭ', layer=''),
    ])

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['МАГ03395БЭ'])
    message = answer['message']

    assert answer['reason'] == LICENCE_AMBIGUOUS
    assert 'слой не назван' in message
    assert 'выбрать не может' in message


@pytest.mark.asyncio
async def test_the_qualifier_is_read_before_the_count_is_judged():
    """The cause this task named as the one to rule out first.

    A refusal that fires before consulting the argument meant to answer it
    looks identical to a missing argument. Reverting the narrowing below the
    `len(candidates) == 1` check makes this test fail and nothing else — which
    is what makes it the test for that ordering rather than for the parameter.
    """
    gis = registry(МАГ03395БЭ=[
        licence('МАГ03395БЭ', layer='Licenses_2024_2025'),
        licence('МАГ03395БЭ', layer='Licenses_annul'),
    ])

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=['МАГ03395БЭ'],
        licence_layers={'МАГ03395БЭ': 'Licenses_annul'},
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['licence_layer_id'] == 'Licenses_annul'


@pytest.mark.asyncio
async def test_one_licences_layer_choice_does_not_reach_another():
    """Five layers for one number says nothing about where another lives.

    A qualifier shared across licences would fill a member in a state nobody
    chose, which is the thing the ambiguity refusal exists to prevent.
    """
    gis = registry(
        МАГ03395БЭ=[
            licence('МАГ03395БЭ', layer='Licenses_2024_2025'),
            licence('МАГ03395БЭ', layer='Licenses_annul'),
        ],
        МАГ03400БЭ=[
            licence('МАГ03400БЭ', layer='Licenses_2024_2025'),
            licence('МАГ03400БЭ', layer='Juniors'),
        ],
    )

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=['МАГ03395БЭ', 'МАГ03400БЭ'],
        licence_layers={'МАГ03395БЭ': 'Licenses_annul'},
    )

    # The first resolved; the second is still ambiguous and still refuses.
    assert answer['status'] == REFUSED
    assert answer['licence_id'] == 'МАГ03400БЭ'
    assert answer['layers'] == ['Licenses_2024_2025', 'Juniors']


@pytest.mark.asyncio
async def test_a_layer_this_licence_is_not_in_says_so_and_names_the_ones_it_is():
    """A different next step from the ambiguity refusal, so a different
    sentence: there, choose one of these; here, the one you chose is not among
    them."""
    gis = registry(МАГ03395БЭ=[
        licence('МАГ03395БЭ', layer='Licenses_2024_2025'),
        licence('МАГ03395БЭ', layer='Licenses_annul'),
    ])

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=['МАГ03395БЭ'],
        licence_layers={'МАГ03395БЭ': 'Juniors'},
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LAYER_NOT_AMONG_CANDIDATES
    assert 'Juniors' in answer['message']
    assert 'Licenses_annul' in answer['message']


@pytest.mark.asyncio
async def test_a_lone_candidate_in_the_wrong_layer_is_still_the_wrong_layer():
    """A qualifier says WHICH layer, not how many were offered.

    The number resolves to exactly one candidate -- and it is the annulled
    state, while the caller named the current one. Judging the qualifier only
    when several candidates came back fills the area from the annulled polygon
    and reports an ordinary success: nobody chose that member and nobody is
    told. That is worse than the ambiguity the argument exists to resolve.
    """
    gis = registry(МАГ03394БЭ=[licence('МАГ03394БЭ', layer='Licenses_annul')])

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=['МАГ03394БЭ'],
        licence_layers={'МАГ03394БЭ': 'Licenses_2024_2025'},
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LAYER_NOT_AMONG_CANDIDATES
    assert answer['layers'] == ['Licenses_annul']
    assert 'Licenses_2024_2025' in answer['message']


# --- the CRS, and what a multi-zone area records --------------------------

def test_the_worked_examples_resolve_to_the_zones_the_task_names():
    """No lookup table and no judgement: three regions, three EPSG codes."""
    assert utm_zone_for(150.8, 61.6) == 'EPSG:32656'   # Магаданская область
    assert utm_zone_for(66.5, 67.2) == 'EPSG:32642'    # Лекын
    assert utm_zone_for(132.0, 47.0) == 'EPSG:32653'   # the demo package
    # Southern hemisphere takes the 327xx band.
    assert utm_zone_for(150.8, -61.6) == 'EPSG:32756'


def test_an_area_spanning_several_zones_takes_one_and_records_the_span():
    """Do not refuse and do not pick per member: members measured in different
    projections cannot be summed, and the fold sums them. The distortion at the
    edges is real and bounded, which is what a projected measurement is — so
    the span is recorded rather than the area refused."""
    members = [
        {'centroid_lon': 148.0, 'centroid_lat': 61.0},
        {'centroid_lon': 160.0, 'centroid_lat': 61.0},
    ]

    resolved = resolve_calculation_crs(members)

    # The members are in zones 55 and 57; the area takes 56, which is neither
    # of them and is the zone its own centre falls in.
    assert resolved['crs'] == 'EPSG:32656'
    assert resolved['spans_several_zones'] is True
    assert resolved['zones_spanned'] == ['EPSG:32655', 'EPSG:32657']
    assert resolved['members_with_centroid'] == 2


def test_an_area_crossing_the_antimeridian_is_not_put_in_the_north_sea():
    """Longitudes average on a circle, and this country crosses 180°.

    Two Чукотка licences at +179.5 and -179.5 are one degree apart. A plain
    mean makes their midpoint 0°, which is EPSG:32631 — the North Sea — and
    every overlap in the area would then be measured half a world from where
    the licences are, without failing.
    """
    resolved = resolve_calculation_crs([
        {'centroid_lon': 179.5, 'centroid_lat': 66.0},
        {'centroid_lon': -179.5, 'centroid_lat': 66.0},
    ])

    assert resolved['crs'] == 'EPSG:32660'
    assert resolved['centroid'][0] in (180.0, -180.0)
    assert resolved['spans_several_zones'] is True


def test_a_single_zone_area_says_so_rather_than_saying_nothing():
    """`spans_several_zones` is present and False rather than absent. A field
    that appears only when something is unusual is a field nobody reads."""
    resolved = resolve_calculation_crs([{'centroid_lon': 150.8, 'centroid_lat': 61.6}])

    assert resolved['spans_several_zones'] is False
    assert resolved['zones_spanned'] == ['EPSG:32656']


def test_a_member_without_a_centroid_is_counted_and_not_guessed():
    """The count is what tells a reader the zone came from two of three."""
    resolved = resolve_calculation_crs([
        {'centroid_lon': 150.8, 'centroid_lat': 61.6},
        {'centroid_lon': 151.2, 'centroid_lat': 61.4},
        {'centroid_lon': None, 'centroid_lat': None},
    ])

    assert resolved['members_with_centroid'] == 2
    assert resolved['members_total'] == 3


def test_no_centroid_at_all_is_none_rather_than_a_zone():
    assert resolve_calculation_crs([{'centroid_lon': None, 'centroid_lat': None}]) is None
    assert resolve_calculation_crs([]) is None


def test_a_centroid_that_is_not_a_number_is_a_member_without_one():
    """`utm_zone_for` raises on these rather than refusing: `int(nan)` is a
    ValueError, `int(inf)` an OverflowError, and `float('x')` never gets that
    far. An unhandled exception out of `fill_area` is not one of this module's
    answer shapes, so they are dropped and counted as members with no centroid,
    which is what they are."""
    resolved = resolve_calculation_crs([
        {'centroid_lon': 150.8, 'centroid_lat': 61.6},
        {'centroid_lon': float('nan'), 'centroid_lat': 61.6},
        {'centroid_lon': float('inf'), 'centroid_lat': 61.6},
        {'centroid_lon': 'not-a-number', 'centroid_lat': 61.6},
    ])

    assert resolved['crs'] == 'EPSG:32656'
    assert resolved['members_with_centroid'] == 1
    assert resolved['members_total'] == 4


def test_a_one_shot_iterable_does_not_produce_a_self_contradicting_record():
    """`members` is declared a Sequence and nothing enforces it. Counting it on
    a second pass saw a generator exhausted and reported one member with a
    centroid out of a total of zero — from the function whose whole job is to
    be reproducible."""
    resolved = resolve_calculation_crs(
        iter([{'centroid_lon': 150.8, 'centroid_lat': 61.6}])
    )

    assert resolved['members_with_centroid'] == 1
    assert resolved['members_total'] == 1


def test_the_no_centroid_refusal_states_a_cause_that_is_true_of_the_members():
    """«Геометрия не читается» was asserted of every member, including the ones
    whose geometry read perfectly and was simply never reprojected.

    A reader sent to check a geodatabase that is fine is a reader sent the
    wrong way by the refusal that exists to tell them where to go.
    """
    answer = resolve_contract(
        policy_version='',
        calculation_crs='',
        members=[
            {'centroid_lon': None, 'centroid_lat': None,
             'centroid_unavailable': 'outside_the_world'},
            {'centroid_lon': None, 'centroid_lat': None,
             'centroid_unavailable': 'unreadable:OSError'},
        ],
    )

    assert answer['status'] == REFUSED
    assert answer['failed'] == 'calculation_crs'
    assert answer['causes'] == {'outside_the_world': 1, 'unreadable:OSError': 1}
    assert 'проекция не выполнена' in answer['message']
    assert 'OSError' in answer['message']
    assert 'не читается' in answer['message']


def test_a_member_that_reported_no_cause_is_not_given_one():
    """A default cause would be a guess wearing the shape of a diagnosis."""
    answer = resolve_contract(
        policy_version='',
        calculation_crs='',
        members=[{'centroid_lon': None, 'centroid_lat': None}],
    )

    assert answer['causes'] == {'unknown': 1}
    assert 'причина не сообщена' in answer['message']


def test_the_answer_states_both_values_and_which_was_the_systems():
    """Without this line the change IS the silent default the refusal existed
    to prevent."""
    line = contract_line({
        'status': RESOLVED,
        'policy_version': {'value': 'geotizer_area_aggregation.v1', 'source': 'resolved'},
        'calculation_crs': {
            'value': 'EPSG:32656', 'source': 'resolved',
            'spans_several_zones': False, 'zones_spanned': ['EPSG:32656'],
        },
    })

    assert 'geotizer_area_aggregation.v1' in line
    assert 'EPSG:32656' in line
    assert 'по центроиду площади' in line
    assert 'по умолчанию для этой сборки' in line


def test_every_geographic_crs_is_refused_however_it_is_spelled():
    """`4326` is WGS 84 and `'4326' != 'EPSG:4326'`.

    The set membership this replaces compared literal strings, and this value
    arrives from an LLM tool call, not from another program. Every spelling
    below passed as «projected» and the area was measured in square degrees by
    the check written to prevent exactly that.
    """
    for spelling in ('4326', 'epsg:4326', 'EPSG: 4326', ' EPSG:4326 ',
                     '4284', '7683', '4979'):
        assert is_projected(spelling) is False, spelling

    for spelling in ('EPSG:32656', '32656', 'epsg:32642', 'EPSG: 32653'):
        assert is_projected(spelling) is True, spelling


def test_a_crs_this_tool_cannot_place_is_its_own_refusal():
    """«I cannot tell» is not «it is geographic», and not «it is projected».

    A WKT name may be perfectly projected. Answering «географическая» about it
    is a sentence false of the value, and answering «projected» measures the
    area in whatever it turns out to be.
    """
    assert epsg_code('WGS 84 / UTM zone 56N') is None

    answer = resolve_contract(
        policy_version='',
        calculation_crs='WGS 84 / UTM zone 56N',
        members=[{'centroid_lon': 150.8, 'centroid_lat': 61.6}],
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == CRS_NOT_RECOGNISED
    assert answer['failed'] == 'calculation_crs'
    # It may say «projected or geographic, I cannot tell». What it must not do
    # is assert that this one IS geographic, which is the other refusal.
    assert 'а это географическая' not in answer['message']
    assert 'не код EPSG' in answer['message']


def test_a_bare_number_reaches_the_geographic_refusal_not_the_unrecognised_one():
    """Two refusals, two next steps: «this one is degrees» and «I cannot tell
    what this is». A number IS placeable, so it gets the first."""
    answer = resolve_contract(
        policy_version='',
        calculation_crs='4326',
        members=[{'centroid_lon': 150.8, 'centroid_lat': 61.6}],
    )

    assert answer['reason'] == MISSING_CONTRACT
    assert 'географическая' in answer['message']


def test_a_recognised_crs_is_recorded_as_the_caller_wrote_it():
    """Judged normalised, recorded verbatim. The string goes on to gis_service,
    which puts it on every relation; this tool does not own it."""
    answer = resolve_contract(
        policy_version='',
        calculation_crs='epsg: 32656',
        members=[{'centroid_lon': 150.8, 'centroid_lat': 61.6}],
    )

    assert answer['status'] == RESOLVED
    assert answer['calculation_crs']['value'] == 'epsg: 32656'


@pytest.mark.asyncio
async def test_filling_by_name_without_a_crs_refuses_and_says_which_way_out():
    """A name search answers «which project», not «which polygon».

    `resolve_project` returns an id, a name and a layer count; there is no
    geometry behind it, so the area has no centroid and no zone. Refusing is
    right. Refusing with «причина не сообщена» sends a reader to hunt a fault in
    a registry nobody read, and leaves them no way forward from a tool whose
    whole promise is to ask before it spends a day.
    """
    async def search(payload):
        assert payload['action'] == 'resolve_scope'
        return {'scope_resolution': {'candidates': [
            project_match('p1', 'Лекын-Тальбейская площадь'),
        ]}}

    answer = await resolve_area_members(gis_call=search, object_name='Лекын')
    assert answer['status'] == RESOLVED
    assert answer['members'][0]['centroid_unavailable'] == NAME_SEARCH_HAS_NO_POLYGON

    refusal = resolve_contract(
        policy_version='', calculation_crs='', members=answer['members'],
    )

    assert refusal['status'] == REFUSED
    assert refusal['reason'] == NO_CENTROID
    assert refusal['causes'] == {NAME_SEARCH_HAS_NO_POLYGON: 1}
    assert 'номера лицензий' in refusal['message']
    assert 'причина не сообщена' not in refusal['message']


@pytest.mark.asyncio
async def test_filling_by_name_with_a_crs_is_not_refused():
    """The refusal above is about the CRS and not about the name. A caller who
    names the projection still gets their area."""
    async def search(payload):
        assert payload['action'] == 'resolve_scope'
        return {'scope_resolution': {'candidates': [
            project_match('p1', 'Лекын-Тальбейская площадь'),
        ]}}

    answer = await resolve_area_members(gis_call=search, object_name='Лекын')
    contract = resolve_contract(
        policy_version='', calculation_crs='EPSG:32642', members=answer['members'],
    )

    assert contract['status'] == RESOLVED
    assert contract['calculation_crs'] == {'value': 'EPSG:32642', 'source': 'supplied'}


def test_a_zone_taken_from_one_member_of_twenty_says_so():
    """The numbers were computed from the first commit and never said.

    One member with a centroid and nineteen without renders identically to
    twenty out of twenty: same wording, same confidence. The whole area is then
    measured from wherever that one licence happens to be, and the answer gives
    a reader nothing to notice it by.
    """
    line = contract_line({
        'status': RESOLVED,
        'policy_version': {'value': 'geotizer_area_aggregation.v1', 'source': 'resolved'},
        'calculation_crs': {
            'value': 'EPSG:32656', 'source': 'resolved',
            'members_with_centroid': 1, 'members_total': 20,
            'spans_several_zones': False, 'zones_spanned': ['EPSG:32656'],
        },
    })

    assert 'центроид по 1 из 20 участников' in line


def test_full_coverage_is_not_announced():
    """Twenty of twenty is the ordinary case and needs no clause. A line that
    states the unremarkable is a line nobody finishes reading."""
    line = contract_line({
        'status': RESOLVED,
        'policy_version': {'value': 'geotizer_area_aggregation.v1', 'source': 'resolved'},
        'calculation_crs': {
            'value': 'EPSG:32656', 'source': 'resolved',
            'members_with_centroid': 20, 'members_total': 20,
            'spans_several_zones': False, 'zones_spanned': ['EPSG:32656'],
        },
    })

    assert 'из 20' not in line


def test_a_supplied_value_is_not_described_as_a_resolved_one():
    line = contract_line({
        'status': RESOLVED,
        'policy_version': {'value': 'p.v1', 'source': 'supplied'},
        'calculation_crs': {'value': 'EPSG:32642', 'source': 'supplied'},
    })

    assert 'указана в запросе' in line
    assert 'по центроиду' not in line
    assert 'по умолчанию' not in line


@pytest.mark.asyncio
async def test_the_rendered_answer_carries_the_line_a_reader_sees():
    """`contract_line` was verified and `render_area_answer` was not, which is
    the helper-verified/wiring-unverified trap: cutting the line out of the
    renderer left every assertion above green."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number, name='Нявленга')]})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
    )
    markdown = render_area_answer(answer)

    assert 'geotizer_area_aggregation.v1' in markdown
    assert 'EPSG:32656' in markdown
    assert 'по центроиду площади' in markdown


@pytest.mark.asyncio
async def test_the_manifest_the_workflow_receives_records_how_each_was_obtained():
    """The manifest is what a run is reproduced from, so it carries the
    provenance and not only the values. Without it the run picks two values and
    says nothing — the silent default the refusal existed to prevent."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})
    seen = {}

    async def spy(*, manifest, **kwargs):
        seen.update(manifest)
        return await run_geotizer_area_workflow(manifest=manifest, **kwargs)

    with mock.patch(
        'open_webui.services.artifacts.geotizer.area_request'
        '.run_geotizer_area_workflow',
        spy,
    ):
        answer = await fill_area(
            gis_call=gis.fill,
            scope_call=gis.scope,
            fold_call=gis.fold,
            member_fill=fill,
            licence_ids=[number],
            calculation_crs='EPSG:32642',
        )

    expected = {
        'policy_version': {
            'value': 'geotizer_area_aggregation.v1', 'source': 'resolved',
        },
        'calculation_crs': {'value': 'EPSG:32642', 'source': 'supplied'},
    }
    assert seen['contract_resolution'] == expected
    # And out the other side. The workflow builds its OWN document and returns
    # that; the incoming manifest is not what a later reader gets. Written onto
    # a dict nobody reads, this record is the silent default it exists to
    # prevent, filed where it cannot be found.
    assert answer['result']['contract_resolution'] == expected


def test_a_multi_zone_answer_says_how_many_zones():
    line = contract_line({
        'status': RESOLVED,
        'policy_version': {'value': 'p.v1', 'source': 'supplied'},
        'calculation_crs': {
            'value': 'EPSG:32656', 'source': 'resolved',
            'spans_several_zones': True,
            'zones_spanned': ['EPSG:32656', 'EPSG:32657'],
        },
    })

    assert '2 зоны' in line
    assert 'EPSG:32657' in line


@pytest.mark.asyncio
async def test_a_name_matching_several_asks_and_says_what_all_of_them_costs():
    """The cost line is load-bearing. A user choosing «all of them» should know
    it is days rather than hours, and this project measured that."""
    gis = registry(**{
        'Лекын-Тальбейская площадь': [
            project_match('p1', 'Лекын-Тальбейское'),
            project_match('p2', 'Восточно-Лекынское'),
            project_match('p3', ''),
        ]
    })

    answer = await resolve_area_members(
        gis_call=gis.fill, object_name='Лекын-Тальбейская площадь'
    )

    assert answer['status'] == ASK
    question = answer['question']
    # Found, and identified by what the search actually returned.
    assert 'найдено 3 лицензии' in question
    for project in ('p1', 'p2', 'p3'):
        assert project in question
    # The object name where one is known, and no dangling dash where none is.
    assert 'p1 — Лекын-Тальбейское' in question
    assert 'p3 — ' not in question
    # What «all of them» would cost.
    assert cost_phrase(3) in question


@pytest.mark.asyncio
async def test_an_area_larger_than_the_deadline_refuses_before_anything_runs():
    numbers = [f'X{i:05d}БЭ' for i in range(21)]
    gis = registry(**{number: [licence(number)] for number in numbers})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=numbers)

    assert answer['status'] == REFUSED
    assert answer['reason'] == TOO_MANY_MEMBERS
    assert answer['members_total'] == 21
    # A literal, not `member_ceiling()` — comparing the production function
    # to itself would agree with any arithmetic, including wrong arithmetic.
    assert answer['ceiling'] == 3
    assert member_ceiling() == 3
    # The figure the user is being spared, in the words they would have read
    # four hours in.
    assert '21 участник, примерно 55 часов' in answer['message']


@pytest.mark.asyncio
async def test_neither_contract_field_has_to_be_supplied_any_more():
    """The refusal this replaces was correct and unworkable.

    Both fields were required, neither was defaulted, and a user asking to fill
    an area holds neither — so every area call refused. What the objection
    forbade is a HIDDEN default: the policy assumed, nobody recording which. A
    resolved value is the opposite, and the two assertions below are what make
    it one — the answer names both, and the manifest records how each was
    obtained.
    """
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
    )

    assert answer['status'] == RESOLVED
    contract = answer['contract']
    assert contract['policy_version'] == {
        'value': 'geotizer_area_aggregation.v1',
        'source': 'resolved',
    }
    assert contract['calculation_crs']['value'] == 'EPSG:32656'
    assert contract['calculation_crs']['source'] == 'resolved'
    # And the scope call was made with them, rather than with the empty
    # strings the caller sent.
    assert gis.scope_payload['policy_version'] == 'geotizer_area_aggregation.v1'
    assert gis.scope_payload['calculation_crs'] == 'EPSG:32656'


@pytest.mark.asyncio
async def test_a_supplied_value_is_used_and_never_overridden():
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
        policy_version='geotizer_area_aggregation.v1',
        calculation_crs='EPSG:32642',
    )

    contract = answer['contract']
    assert contract['calculation_crs'] == {
        'value': 'EPSG:32642',
        'source': 'supplied',
    }
    assert contract['policy_version']['source'] == 'supplied'
    # Supplied beats resolved even when resolution would have said otherwise:
    # these members are in zone 56 and the caller named 42.
    assert gis.scope_payload['calculation_crs'] == 'EPSG:32642'


@pytest.mark.asyncio
async def test_a_member_whose_geometry_will_not_read_refuses_by_name():
    """The third row of the precedence, and it is not hypothetical.

    The refusal must name WHICH value could not be resolved rather than repeat
    the old sentence about both — a caller who supplied a policy and not a CRS
    should not be told the policy is missing too.
    """
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number, centroid=None)]})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
    )

    assert answer['status'] == REFUSED
    assert answer['failed'] == 'calculation_crs'
    assert 'policy_version' not in answer['message']
    assert 'центроид' in answer['message']


@pytest.mark.asyncio
async def test_a_geographic_crs_is_refused_rather_than_replaced():
    """An area in square degrees is not an area — the whole of the original
    objection. Refused and not silently corrected: overriding a value the user
    named is the one thing the precedence forbids."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=[number],
        calculation_crs='EPSG:4326',
    )

    assert answer['status'] == REFUSED
    assert answer['failed'] == 'calculation_crs'
    assert 'EPSG:4326' in answer['message']


@pytest.mark.asyncio
async def test_a_three_member_area_fills_folds_and_summarises():
    """The run this task exists to make possible.

    Three members, one of which fails. The failure does not become an absence:
    it reaches the fold as `member_run_failed`, because a member missing from
    the fold reads as a member that contributed nothing, and those are
    different facts about a 351-row card.
    """
    numbers = ['МАГ03394БЭ', 'СЛХ025834ТП', 'АНД01313БП']
    gis = registry(**{number: [licence(number)] for number in numbers})

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=numbers,
        policy_version=POLICY,
        calculation_crs=CRS,
        area_scope_id='area-lekyn',
        dossier_run_id='dossier-1',
    )

    assert answer['status'] == RESOLVED
    result = answer['result']
    assert result['counts'] == {
        'members': 3,
        'filled': 2,
        'failed': 1,
        'not_attempted': 0,
    }
    assert result['aggregation']['state'] == 'performed'
    assert result['aggregation']['link_guard'] == 'enforced'

    sent = {member['entity_id']: member for member in gis.fold_payload['members']}
    assert sent['МАГ03394БЭ']['run_id'] == 'run-МАГ03394БЭ'
    assert sent['СЛХ025834ТП']['unreached'] == 'member_run_failed'
    # The manifest goes with it, because the one case the double-count guard
    # does not run is the case where nobody sends it.
    assert gis.fold_payload['scope']['area_id'] == 'area-lekyn'
    assert gis.fold_payload['policy_version'] == POLICY

    rendered = render_area_answer(answer)
    assert 'run-МАГ03394БЭ' in rendered
    assert 'не заполнен' in rendered
    assert 'Свод площади' in rendered


@pytest.mark.asyncio
async def test_each_service_call_goes_to_the_operation_that_declares_it():
    """The bug this file did not catch the first time.

    `fill_area` makes three service calls to three operations. The first
    version passed one handle to all of them, so `resolve_area_scope` and
    `fold_area` were sent to `geotizer_fill` — whose action set contains
    neither and whose request forbids the fields they carry. Every area fill
    would have been refused at its second call, and nothing said so, because
    the fake answered any action.

    `Service.fill` now raises on an action `geotizer_fill` does not declare, so
    reverting `fill_area` to one handle fails here instead of shipping.
    """
    numbers = ['МАГ03394БЭ', 'СЛХ025834ТП']
    gis = registry(**{number: [licence(number)] for number in numbers})

    await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=numbers,
        policy_version=POLICY,
        calculation_crs=CRS,
        area_scope_id='area-1',
        dossier_run_id='dossier-1',
    )

    # Each operation saw its own action and no other.
    assert gis.scope_payload['action'] == 'resolve_area_scope'
    assert gis.fold_payload['action'] == 'fold_area'


@pytest.mark.asyncio
async def test_sending_an_area_action_to_the_fill_operation_is_refused():
    """The positive control for the fake itself.

    A guard that has never rejected anything is not evidence of anything, so
    this proves `Service.fill` really does refuse an area action rather than
    passing everything through.
    """
    gis = registry()

    with pytest.raises(AssertionError, match='geotizer_fill has no action'):
        await gis.fill({'action': 'fold_area'})


@pytest.mark.asyncio
async def test_nothing_to_resolve_is_its_own_refusal():
    """Neither a name nor numbers is not «not found» — there was no search."""
    answer = await resolve_area_members(gis_call=registry().fill)

    assert answer['status'] == REFUSED
    assert answer['reason'] == NOTHING_TO_RESOLVE


@pytest.mark.asyncio
async def test_a_search_answer_that_is_not_one_does_not_become_not_found():
    """`resolve_scope` always carries `scope_resolution`, on every branch.

    Its absence means the reply was never a search answer — an error body
    surfaced as data, most likely. Saying «не найдена» about a licence nobody
    looked up is a specific false claim, and worse than admitting the reply
    could not be read.
    """
    class Mute:
        async def fill(self, payload):
            return {'detail': 'Internal Server Error'}

    answer = await resolve_area_members(
        gis_call=Mute().fill, licence_ids=['МАГ03394БЭ']
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SEARCH_UNREADABLE
    assert 'не найдена' not in answer['message'].replace('«Не найдена» о ней не утверждается', '')


@pytest.mark.asyncio
async def test_a_manifest_that_lost_its_members_is_not_an_area_of_none():
    """Resolution already guaranteed at least one member, so an empty manifest
    is the manifest call having failed. Filling nothing and reporting «0
    участников» as success is the one answer worse than a refusal."""
    numbers = ['МАГ03394БЭ']
    gis = registry(**{number: [licence(number)] for number in numbers})

    async def empty_scope(payload):
        return {'area_scope_id': payload['area_scope_id'], 'entities': [], 'relations': []}

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=empty_scope,
        fold_call=gis.fold,
        member_fill=fill,
        licence_ids=numbers,
        policy_version=POLICY,
        calculation_crs=CRS,
        area_scope_id='area-1',
        dossier_run_id='d',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == MANIFEST_WITHOUT_MEMBERS


@pytest.mark.asyncio
async def test_a_fold_that_fails_keeps_every_member_that_was_filled():
    """The roll-up is worth less than the cards. A fold that raises must not
    discard hours of member fills, and the answer says why there is no
    summary rather than omitting one."""
    numbers = ['МАГ03394БЭ', 'АНД01313БП']
    gis = registry(**{number: [licence(number)] for number in numbers})

    async def refusing_fold(payload):
        raise RuntimeError('422: policy_version mismatch')

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=refusing_fold,
        member_fill=fill,
        licence_ids=numbers,
        policy_version=POLICY,
        calculation_crs=CRS,
        area_scope_id='area-1',
        dossier_run_id='d',
    )

    result = answer['result']
    assert result['counts']['filled'] == 2
    assert result['aggregation']['reason'] == 'fold_failed'
    assert 'summary' not in result

    rendered = render_area_answer(answer)
    assert 'Свод не построен: fold_failed' in rendered
    # And the members are still reachable by their own run ids.
    assert 'run-МАГ03394БЭ' in rendered


@pytest.mark.asyncio
async def test_a_fold_that_answers_without_an_aggregation_has_not_folded():
    """Returning without raising is not the same as having folded. `performed`
    carrying `result: None` is indistinguishable from a genuine empty fold."""
    numbers = ['МАГ03394БЭ']
    gis = registry(**{number: [licence(number)] for number in numbers})

    async def hollow_fold(payload):
        return {'policy_version': POLICY}

    answer = await fill_area(
        gis_call=gis.fill,
        scope_call=gis.scope,
        fold_call=hollow_fold,
        member_fill=fill,
        licence_ids=numbers,
        policy_version=POLICY,
        calculation_crs=CRS,
        area_scope_id='area-1',
        dossier_run_id='d',
    )

    assert answer['result']['aggregation']['state'] == 'not_performed'
    assert answer['result']['aggregation']['reason'] == 'fold_failed'


def test_a_bad_deadline_valve_does_not_take_the_tool_down():
    """The valve arrives as a raw environment string. Garbage is not a deadline
    of zero, and raising here would kill every area call before it could
    search, ask or refuse — the failure this module exists to replace."""
    for bad in ('', 'abc', None, '-5', '0'):
        assert member_ceiling(bad) == 3, bad
    # A real value still moves the ceiling.
    assert member_ceiling(6 * 2.6 * 3600) == 6
