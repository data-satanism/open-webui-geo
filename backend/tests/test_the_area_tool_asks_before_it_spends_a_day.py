"""The area tool's outcomes, and the one that costs a day if it is wrong.

`fill_geoteaser_area` resolves licences, fills each as its own object, folds
the result and renders it. Three of its outcomes are answers a user reads and
never a run: a question when a name is ambiguous, a refusal when a number
resolves to nothing, and a refusal when the project named does not exist.

A fourth used to be here and is gone: a refusal when the area held more
members than a ceiling allowed. The reasoning was wrong. «A tool that accepts
twenty-one members and dies at hour four has lost a day and produced nothing»
is false in its second half — each member is an ordinary single-object run
with its own `run_id` and its own card, so a call that outlives its request
has produced every member that finished. What the removal owes in exchange is
that those members stay findable, which is why the run id is emitted as each
one starts rather than only named in the final answer.
"""

from __future__ import annotations

import ast
from pathlib import Path
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
    ARG_ACCEPTED,
    ARG_NOT_CONFIRMED,
    ARG_NOT_FOUND,
    ARG_NOT_HONOURED,
    ARG_NOT_PASSED,
    NOTHING_TO_RESOLVE,
    POLICY_VERSION_UNKNOWN,
    PROJECT_NOT_FOUND,
    SCOPE_AMBIGUOUS,
    SCOPE_NOT_APPLIED,
    SCOPE_UNVERIFIABLE,
    SEARCH_UNREADABLE,
    received_line,
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
    ASK,
    ambiguous_licence,
    area_deadline_seconds,
    cost_notice,
    fill_area,
    render_area_answer,
    resolve_contract,
    resolve_area_members,
)
from open_webui.services.artifacts.geotizer.area_request import (
    _member_line,
    _scope_echo,
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

    def __init__(self, projects=None, scopes=True, **entries):
        self.entries = entries
        self._projects = None if projects is None else list(projects)
        # A service older than the scoping accepts `project_id` on
        # `resolve_scope` and ignores it: no error, no 422, the search just
        # widens. Two deployables are released separately, so this is not a
        # hypothetical -- it is what the caller's side meets whenever the fork
        # ships first.
        self.scopes = scopes
        self.fold_payload = None
        self.scope_payload = None
        self.scope_queries: list[dict] = []

    def known_projects(self):
        """The store's projects, shaped as `nearest_projects` returns them.

        Derived from the fixture rows unless a test states them, so the
        default store contains exactly the projects its licences live in.
        """
        if self._projects is not None:
            return [dict(item) for item in self._projects]
        seen: dict[str, dict] = {}
        for rows in self.entries.values():
            for item in rows:
                pid = str(item.get('project_id') or '').strip()
                if pid:
                    seen.setdefault(
                        pid, {'project_id': pid, 'name': pid, 'layers_count': 1}
                    )
        return list(seen.values())

    @staticmethod
    def _named(known, named):
        """`_project_named`, as gis_service implements it.

        Exact id first, then a case-insensitive name or id match, and None for
        «no match» AND for «several». The fake used to compare the raw
        `project_id` to each row's, which meant a caller naming a project by
        its human name — which the real service resolves, and its own suite
        tests — silently matched nothing here.
        """
        for item in known:
            if str(item.get('project_id') or '') == named:
                return item
        folded = named.casefold()
        matches = [
            item for item in known
            if str(item.get('name') or '').casefold() == folded
            or str(item.get('project_id') or '').casefold() == folded
        ]
        return matches[0] if len(matches) == 1 else None

    def _nothing_matched(self, query, scope):
        """The real «none» answer: project SUGGESTIONS under `candidates`.

        Not an empty list. `resolve_scope` fills `candidates` with the nearest
        project names and says so in `candidates_are`, and a fake that returned
        `[]` here hid the defect where the caller's side counted those
        suggestions as licence rows.
        """
        resolution = {
            'query': query,
            'status': 'none',
            'searched_projects': 1 if scope else 49026,
        }
        if scope:
            # Scoped: the other projects are not an answer to «not in this one».
            resolution['scoped_to_project'] = scope
            resolution['candidates'] = []
            resolution['known_project_count'] = len(self.known_projects())
            code = 'scope_not_found_in_project'
        else:
            resolution['candidates'] = self.known_projects()
            resolution['candidates_are'] = 'known_projects'
            resolution['known_project_count'] = len(self.known_projects())
            code = 'scope_not_found'
        return {
            'workflow_status': 'needs_input',
            'scope_resolution': resolution,
            'error': {'code': code, 'message': f'Nothing matched {query!r}.'},
        }

    async def fill(self, payload):
        action = payload['action']
        if action not in FILL_ACTIONS:
            raise AssertionError(f'geotizer_fill has no action {action!r}')
        if action == 'resolve_scope':
            self.scope_queries.append(dict(payload))
            known = self.known_projects()
            scope = str(payload.get('project_id') or '').strip()
            if scope and not self.scopes:
                # Accepted and dropped, exactly as the older service does: the
                # field was already declared on the request model, so an old
                # deployment takes it at the boundary and never forwards it
                # into `resolve_scope`. No error, no 422 -- the search widens.
                found = list(self.entries.get(payload['query'], []))
                if not found:
                    return self._nothing_matched(payload['query'], '')
                resolution = {
                    'candidates': found,
                    # The store's real size, not a fabricated one: this number
                    # is printed verbatim in «Искали в проектах: N».
                    'searched_projects': len(known),
                }
                if len(found) > 1:
                    # What the old service actually says about several rows,
                    # rather than an unqualified «ok». Nothing on the caller's
                    # side reads this code today; a fake that omits it would
                    # stop being harmless the moment something did.
                    resolution['status'] = 'several'
                    return {
                        'workflow_status': 'needs_input',
                        'scope_resolution': resolution,
                        'error': {
                            'code': 'scope_several_candidates',
                            'message': f'{payload["query"]} matched several rows.',
                        },
                    }
                return {'workflow_status': 'ok', 'scope_resolution': resolution}
            if scope:
                matched = self._named(known, scope)
                if matched is None:
                    # The real refusal, shape for shape: the store's project
                    # names go back under `candidates`, marked, and nothing is
                    # searched for. This is the answer the caller's side read
                    # as licence rows.
                    return {
                        'workflow_status': 'needs_input',
                        'scope_resolution': {
                            'query': payload['query'],
                            'status': 'none',
                            'candidates': known,
                            'candidates_are': 'known_projects',
                            'requested_project_id': scope,
                            'searched_projects': 0,
                        },
                        'error': {
                            'code': 'scope_project_not_found',
                            'message': f'No project matches {scope!r}.',
                        },
                    }
                scope = str(matched.get('project_id') or '')
            found = list(self.entries.get(payload['query'], []))
            if scope:
                # The real `resolve_scope` narrows `project_ids` to the named
                # project before it searches, so hits elsewhere are never
                # candidates. A fake that returned them anyway would let the
                # defect under test pass this file.
                found = [
                    item for item in found
                    if str(item.get('project_id') or '') == scope
                ]
            if not found:
                return self._nothing_matched(payload['query'], scope)
            resolution = {
                'candidates': found,
                'searched_projects': 1 if scope else 49026,
            }
            if scope:
                resolution['scoped_to_project'] = scope
            return {'workflow_status': 'ok', 'scope_resolution': resolution}
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


def registry(projects=None, scopes=True, **entries):
    """A store of licence rows, and optionally the projects it holds.

    `projects` is needed whenever a test names a project that owns none of the
    fixture's rows: the store's project list is derived from those rows, so an
    undeclared name is a project that does not exist — which is now its own
    refusal rather than «licence not found».
    """
    return Service(projects=projects, scopes=scopes, **entries)


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


async def fill(*, object_name, project_id=None, licence_id=None, **_):
    """The single-object fill, as a member reaches it.

    Keyed on `licence_id` and not on `object_name`, because that is the
    identity a member now carries: an area member is filled BY its licence and
    arrives with no name, so a fake that recognised members by name would
    recognise all three as the same nameless one — and would have agreed with
    the defect that sent the area's name down to every member.
    """
    assert licence_id or object_name, 'a member fill needs an identity'
    if licence_id == 'СЛХ025834ТП':
        raise RuntimeError('specialist timeout')
    return {
        'run_id': f'run-{licence_id or object_name}',
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


# --- the project the caller named -------------------------------------------
#
# `project_id: Тенгкели-Березовская площадь`, `licence_ids: МАГ04805БЭ, …` —
# and `МАГ04805БЭ` came back twice, once from that project and once from
# `GIS_Data_RF`, as an ambiguity for the caller to resolve. They already had.


@pytest.mark.asyncio
async def test_a_named_project_scopes_the_search():
    """The registry hit is not a candidate when the caller named a project.

    `GIS_Data_RF` is the national registry and holds almost any licence in the
    country; a project a geologist uploaded holds the few they work on. Both
    matching is the ordinary case, not an ambiguous one.
    """
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [
        licence(number, project='GIS_Data_RF', layer='Licenses_2024_2025'),
        licence(number, project='Тенгкели-Березовская площадь',
                layer='Sint_licences_2025exp_clp'),
    ]})

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=[number],
        project_id='Тенгкели-Березовская площадь',
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['project_id'] == 'Тенгкели-Березовская площадь'
    assert answer['members'][0]['licence_layer_id'] == 'Sint_licences_2025exp_clp'


@pytest.mark.asyncio
async def test_the_project_reaches_the_search_and_is_not_merely_recorded():
    """`fill_area` read `project_id` only to name the area's owner on the
    manifest, so a caller who named their project had it honoured everywhere
    except in the search that decides membership. Asserted on the payload
    because that is the thing that was missing."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [licence(number, project='p-named')]})

    await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id='p-named',
    )

    assert gis.scope_queries[0]['project_id'] == 'p-named'


@pytest.mark.asyncio
async def test_without_a_project_the_multi_project_refusal_still_fires():
    """The refusal is correct and stays. It exists for the caller who did not
    scope the search — which is the difference this change draws."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [
        licence(number, project='GIS_Data_RF', layer='Licenses_2024_2025'),
        licence(number, project='Тенгкели-Березовская площадь',
                layer='Sint_licences_2025exp_clp'),
    ]})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=[number])

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_AMBIGUOUS
    assert 'project_id' not in gis.scope_queries[0]


@pytest.mark.asyncio
async def test_the_multi_project_refusal_names_the_argument_that_exists():
    """The message said to pass `licence_layers`. The Workspace tool declares
    no such parameter, so a model following the instruction sends a value Open
    WebUI drops — the third refusal in this project to name an argument the
    caller cannot pass.

    `project_id` it does declare, and for two projects it is the right answer
    anyway: the caller is not choosing a licence STATE, they are saying which
    project they meant.
    """
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [
        licence(number, project='GIS_Data_RF', layer='Licenses_2024_2025'),
        licence(number, project='Тенгкели-Березовская площадь',
                layer='Sint_licences_2025exp_clp'),
    ]})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=[number])
    message = answer['message']

    assert '`project_id`' in message
    assert 'licence_layers' not in message
    # Both projects named, so the caller knows which values are available.
    assert 'GIS_Data_RF' in message
    assert 'Тенгкели-Березовская площадь' in message
    # And why a registry hit beside their own project is not a real ambiguity.
    assert 'общероссийский реестр' in message


@pytest.mark.asyncio
async def test_a_scoped_search_that_finds_nothing_does_not_fall_back_to_all():
    """Scoping must not degrade to a broad search when the project holds
    nothing: a registry hit would then arrive as though it came from the
    project the caller named."""
    number = 'МАГ04805БЭ'
    gis = registry(
        # Both projects exist; only one holds the licence. Without the second
        # declared, this would be «no such project» and would stop testing the
        # thing it is named for.
        projects=[
            {'project_id': 'GIS_Data_RF', 'name': 'GIS_Data_RF'},
            {
                'project_id': 'Тенгкели-Березовская площадь',
                'name': 'Тенгкели-Березовская площадь',
            },
        ],
        **{number: [licence(number, project='GIS_Data_RF')]},
    )

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id='Тенгкели-Березовская площадь',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_NOT_FOUND
    # And the refusal names the project it searched, not just how many.
    assert 'Тенгкели-Березовская площадь' in answer['message']


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
    # What the caller can actually do. `licence_layers` is NOT named: it does
    # not exist on the deployed Workspace tool, so a model following that
    # instruction sends a value Open WebUI drops.
    assert 'licence_layers' not in message
    # And why they are not merged, because «choose one» invites «merge them».
    assert 'состояния одной лицензии' in message
    assert 'параметра для этого у инструмента нет' in message


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
    # Two projects, so the step the caller CAN take is the one offered.
    assert '`project_id`' in message
    assert 'licence_layers' not in message


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
    assert 'выбрать нельзя' in message


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
    # The name-search branch states its cost too. It is the only RESOLVED
    # return that was never asserted, so `cost_notice(1)` could be deleted
    # from it with every test in this file still green.
    assert '1 участник, примерно 3 часа' in answer['cost_notice']


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
    # What «all of them» would cost, as a literal. `cost_phrase(3)` here
    # compared the code to itself: the two agreed by construction and any
    # wording or arithmetic change agreed with them.
    assert '3 участника, примерно 8 часов' in question


@pytest.mark.asyncio
async def test_seven_members_are_accepted_and_the_cost_is_stated():
    """The ceiling refused this and the reasoning was wrong.

    It said: a tool that accepts twenty-one members and dies at hour four has
    lost a day and produced nothing. The second half is false — each member is
    an ordinary single-object run with its own `run_id` and its own card, so a
    call that outlives its request has produced every member that finished.
    Refusing at three converted a partial result into no result at all.
    """
    numbers = [f'X{i:05d}БЭ' for i in range(7)]
    gis = registry(**{number: [licence(number)] for number in numbers})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=numbers)

    assert answer['status'] == RESOLVED
    assert len(answer['members']) == 7
    assert '7 участников, примерно 18 часов' in answer['cost_notice']


@pytest.mark.asyncio
async def test_twenty_one_members_are_accepted_too():
    """The count that motivated the ceiling. There is no number of licences at
    which the tool decides for the caller how long they may wait."""
    numbers = [f'X{i:05d}БЭ' for i in range(21)]
    gis = registry(**{number: [licence(number)] for number in numbers})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=numbers)

    assert answer['status'] == RESOLVED
    assert len(answer['members']) == 21
    # The figure, as a literal. A count is not a test of the sentence that
    # states it: a plural-form bug at double digits, or an arithmetic slip in
    # `MEMBER_HOURS`, ships silently when only the length is asserted.
    assert '21 участник, примерно 55 часов' in answer['cost_notice']


@pytest.mark.asyncio
async def test_the_rendered_answer_opens_with_what_the_run_cost():
    """`cost_notice` was verified and `render_area_answer` was not, which is
    the helper-verified/wiring-unverified trap this file has met twice."""
    number = 'МАГ03394БЭ'
    gis = registry(**{number: [licence(number)]})

    answer = await fill_area(
        gis_call=gis.fill, scope_call=gis.scope, fold_call=gis.fold,
        member_fill=fill, licence_ids=[number], calculation_crs=CRS,
    )
    rendered = render_area_answer(answer)

    assert rendered.startswith('1 участник, примерно 3 часа')
    assert 'продолжат заполняться' in rendered


def test_a_layer_this_tool_has_no_word_for_says_so():
    """`Licenses_2024_2025` printed «действующие» and
    `Sint_licences_2025exp_clp` printed a blank beside it — which reads as «no
    state recorded for this layer» when what it means is «this tool has no word
    for it». Nothing upstream carries a state to read: a layer is classified as
    a licence layer by a token in its name.
    """
    message = ambiguous_licence('МАГ04805БЭ', [
        licence('МАГ04805БЭ', project='GIS_Data_RF', layer='Licenses_2024_2025'),
        licence('МАГ04805БЭ', project='Тенгкели-Березовская площадь',
                layer='Sint_licences_2025exp_clp'),
    ])

    assert 'Licenses_2024_2025' in message and 'действующие' in message
    assert 'Sint_licences_2025exp_clp' in message
    assert 'состояние не определено' in message
    # And the two lines are distinguishable, which is the whole point.
    known, unknown = [
        line for line in message.splitlines() if 'Licenses_2024_2025' in line
    ][0], [
        line for line in message.splitlines() if 'Sint_licences' in line
    ][0]
    assert 'действующие' in known and 'состояние не определено' not in known
    assert 'состояние не определено' in unknown


def test_the_notice_says_the_request_ends_before_the_work_does():
    """Three facts in the order a reader needs them: how long, that their
    request will end first, and that the work does not end with it. Without the
    third the first two read as a refusal."""
    notice = cost_notice(7)

    assert '7 участников, примерно 18 часов' in notice
    assert 'прервётся раньше' in notice
    assert 'продолжат заполняться' in notice
    assert 'Свод по площади соберётся' in notice
    # Not a refusal, and it must not read as one.
    assert 'не поддерживается' not in notice
    assert 'предел' not in notice


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
    """The valve arrives as a raw environment string and the workflow does
    `float()` on it once per member.

    `member_ceiling` held this guard and was the only thing that touched the
    valve before the workflow did. With the ceiling gone the guard had to move
    or `GEOMAS_AREA_DEADLINE_SECONDS=abc` would raise inside the member loop —
    after members had been filled, which is the most expensive moment to find a
    typo in a valve.
    """
    for bad in ('abc', '-5', '0', 'NaN-ish'):
        seconds, note = area_deadline_seconds(bad)
        assert seconds is None, bad

    # A real value still reaches the workflow as a number, with nothing to say.
    assert area_deadline_seconds(str(6 * 2.6 * 3600)) == (6 * 2.6 * 3600, None)
    assert area_deadline_seconds(6 * 2.6 * 3600) == (6 * 2.6 * 3600, None)


def test_a_refused_valve_says_so_and_an_unset_one_stays_quiet():
    """Both end up unbounded, and without the note they are the same answer.

    An operator who set `GEOMAS_AREA_DEADLINE_SECONDS=3600s` believes the area
    is bounded at an hour while nothing bounds it at all. The sibling
    per-member valve has returned a note for this reason since it was written;
    this one returned a bare `None` and the misconfiguration was invisible.
    """
    for bad in ('abc', '-5', '0', 'NaN-ish', '3600s'):
        seconds, note = area_deadline_seconds(bad)
        assert seconds is None, bad
        assert note, bad
        # The value the operator actually typed, so they can find it.
        assert repr(bad) in note, bad
        assert 'GEOMAS_AREA_DEADLINE_SECONDS' in note, bad

    # Unset is not a misconfiguration and must not read as one.
    for quiet in (None, ''):
        assert area_deadline_seconds(quiet) == (None, None), quiet


def test_no_valve_is_no_bound_and_not_a_bound_of_zero():
    """Unset is the default this change makes: how long to wait is the
    caller's. A zero read as a deadline puts every member past it before the
    first one starts, abandoning the area without filling anything."""
    assert area_deadline_seconds(None)[0] is None
    assert area_deadline_seconds('0')[0] is None

# ------------------------------------- the run ids have to leave the process

#: `tools/geotizer.py` cannot be imported here -- it pulls the whole
#: application in -- so its call sites are read the way
#: `test_geotizer_boundary_contract.py` reads them.
TOOL_SOURCE = (
    Path(__file__).resolve().parents[1]
    / 'open_webui'
    / 'tools'
    / 'geotizer.py'
)


def _call_keywords(function_name: str, call_name: str) -> dict[str, str]:
    """Every keyword of `call_name(...)` inside `def function_name`, unparsed."""
    tree = ast.parse(TOOL_SOURCE.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != function_name:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if isinstance(func, ast.Name) and func.id == call_name:
                return {
                    kw.arg: ast.unparse(kw.value)
                    for kw in call.keywords
                    if kw.arg
                }
    raise AssertionError(f'no {call_name}(...) call inside {function_name}')


def test_an_area_member_fill_is_given_the_event_emitter():
    """Without it every member's `run_started` line is built and dropped.

    This is the whole mechanism the ceiling removal rests on. Seven members
    take about eighteen hours, so the browser request ends long before the
    answer that names their run ids; the per-member `run_started` line, emitted
    as each member begins, is the only handle that arrives while anyone is
    still listening. `_emit_status` is `if emitter:`, so an unpassed emitter
    does not fail — it silently emits nothing, and the members are filled and
    unreachable, which is the exact failure the removal promised not to cause.

    Asserted at the call site because that is where it was missing: the
    emission itself, the phrase and the status gate were all built and tested,
    and the one line that connects them to a caller was not passed.
    """
    keywords = _call_keywords('fill_geoteaser_area', 'member_filler')

    assert keywords.get('event_emitter') == '__event_emitter__', keywords

    # The sibling tool has passed it since the beginning; the area path is the
    # one that needs it more, and the two must not drift apart again.
    assert _call_keywords('fill_geotizer', 'run_geotizer_workflow').get(
        'event_emitter'
    ) == '__event_emitter__'


def test_a_refused_deadline_valve_reaches_the_answer_a_user_reads():
    """The note is only worth returning if it is printed somewhere."""
    answer = render_area_answer(
        {
            'status': RESOLVED,
            'cost_notice': 'стоимость',
            'area_deadline_note': 'GEOMAS_AREA_DEADLINE_SECONDS=\'3600s\' — не число;',
            'result': {
                'area_id': 'area:x',
                'counts': {'members': 1, 'filled': 1, 'failed': 0, 'not_attempted': 0},
                'members': [],
                'aggregation': {},
            },
        }
    )

    assert 'GEOMAS_AREA_DEADLINE_SECONDS' in answer
    # Beside the cost notice, not instead of it.
    assert 'стоимость' in answer


def test_an_answer_with_a_usable_valve_says_nothing_about_it():
    """A note that appears when nothing is wrong teaches readers to skip notes."""
    answer = render_area_answer(
        {
            'status': RESOLVED,
            'cost_notice': 'стоимость',
            'result': {
                'area_id': 'area:x',
                'counts': {'members': 1, 'filled': 1, 'failed': 0, 'not_attempted': 0},
                'members': [],
                'aggregation': {},
            },
        }
    )

    assert 'GEOMAS_AREA_DEADLINE_SECONDS' not in answer


def test_a_failed_member_is_listed_with_the_run_that_holds_its_work():
    """The run exists and holds whatever was filled before the failure."""
    line = _member_line(
        {
            'object_name': 'Нявленга',
            'state': 'failed',
            'error': 'RuntimeError: gis refused',
            'run_id': 'run-nyavlenga',
        }
    )

    assert 'run-nyavlenga' in line
    assert 'RuntimeError: gis refused' in line


def test_a_member_that_failed_before_a_run_existed_offers_no_handle():
    """An empty pair of backticks reads as a run id the caller can use."""
    line = _member_line(
        {
            'object_name': 'Нявленга',
            'state': 'failed',
            'error': 'RuntimeError: refused at the door',
        }
    )

    assert '`' not in line
    assert 'RuntimeError: refused at the door' in line


# --------------------- a project_id that matches nothing is its own refusal


@pytest.mark.asyncio
async def test_a_mistyped_project_id_never_becomes_a_filled_member():
    """One known project, one suggestion, one fabricated licence.

    `resolve_scope` answers a `project_id` that matched nothing by putting the
    store's project NAMES under `candidates` — the same key, with the same
    `status: none`, that a real licence hit uses. Counted as licence rows, a
    store holding one project produced exactly one «candidate», the count said
    one, and the area reported RESOLVED over a member built out of a project
    name: `licence_id` null, `entity_id` the project. The licence was never
    searched for anywhere.
    """
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [licence(number, project='OnlyProject')]})

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=[number],
        project_id='TYPO-project-id-that-does-not-exist',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == PROJECT_NOT_FOUND
    # Not a claim about the number, which was never looked up.
    assert 'не найдена' not in answer['message']
    # The name that failed, and the ones that would not have.
    assert 'TYPO-project-id-that-does-not-exist' in answer['message']
    assert 'OnlyProject' in answer['message']


@pytest.mark.asyncio
async def test_a_mistyped_project_id_is_not_reported_as_an_ambiguous_licence():
    """Two known projects became «found in 2 projects, name one».

    The caller had named one — they mistyped it. Telling them to supply
    `project_id` is advice they already took, about an ambiguity between two
    projects neither of which was searched.
    """
    number = 'МАГ04805БЭ'
    gis = registry(
        projects=[
            {'project_id': 'GIS_Data_RF', 'name': 'GIS_Data_RF'},
            {
                'project_id': 'Тенгкели-Березовская площадь',
                'name': 'Тенгкели-Березовская площадь',
            },
        ],
        **{number: [licence(number, project='GIS_Data_RF')]},
    )

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=[number],
        project_id='Совершенно другой проект XYZ 12345',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == PROJECT_NOT_FOUND
    assert answer['reason'] != LICENCE_AMBIGUOUS
    assert 'найдена 2 раз' not in answer['message']
    assert 'Совершенно другой проект XYZ 12345' in answer['message']


@pytest.mark.asyncio
async def test_a_name_search_with_a_mistyped_project_id_refuses_the_same_way():
    """The second search path reads the same polymorphic key."""
    gis = registry(
        projects=[{'project_id': 'p1', 'name': 'Первый проект'}],
        **{'Лекын-Тальбейская площадь': [project_match('p1', 'Лекын-Тальбейское')]},
    )

    answer = await resolve_area_members(
        gis_call=gis.fill,
        object_name='Лекын-Тальбейская площадь',
        project_id='нет такого проекта',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == PROJECT_NOT_FOUND


@pytest.mark.asyncio
async def test_a_licence_that_does_not_exist_anywhere_is_still_not_found():
    """The unscoped miss fills `candidates` with project names too.

    This path predates `project_id` entirely: with one project in the store, a
    number that exists nowhere resolved to one «candidate» and filled it.
    """
    gis = registry(**{'МАГ04805БЭ': [licence('МАГ04805БЭ', project='OnlyProject')]})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['НЕТ00000БЭ'])

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_NOT_FOUND
    assert 'НЕТ00000БЭ' in answer['message']


@pytest.mark.asyncio
async def test_a_project_named_by_its_human_name_scopes_the_search_too():
    """The real service resolves a name to an id before it searches.

    The fake compared the raw string to each row's `project_id`, so a caller
    who named their project the way a person would matched nothing here while
    matching correctly in production — a fake that disagrees with the service
    in the caller's favour hides whichever side is wrong.
    """
    number = 'МАГ04805БЭ'
    gis = registry(
        projects=[
            {'project_id': 'GIS_Data_RF', 'name': 'Единый реестр лицензий РФ'},
        ],
        **{number: [licence(number, project='GIS_Data_RF')]},
    )

    answer = await resolve_area_members(
        gis_call=gis.fill,
        licence_ids=[number],
        project_id='Единый реестр лицензий РФ',
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['project_id'] == 'GIS_Data_RF'


def test_the_area_deadline_valve_is_read_and_judged_before_the_workflow():
    """The helper was tested and the one line that uses it was not.

    `area_deadline_seconds` has its own unit tests, but the adapter could
    return `os.getenv(...)` raw — the pre-fix behaviour — with every test in
    this file green, and `GEOMAS_AREA_DEADLINE_SECONDS=abc` would again raise
    `ValueError` inside the member loop, after members had been filled.
    """
    source = TOOL_SOURCE.read_text(encoding='utf-8')

    # The shim delegates to the core rather than handing the raw string on.
    assert 'return area_deadline_seconds(' in source

    # And the adapter passes both halves of what the shim returns.
    keywords = _call_keywords('fill_geoteaser_area', 'fill_area')
    assert keywords.get('area_deadline_seconds') == 'area_deadline'
    assert keywords.get('area_deadline_note') == "area_deadline_note or ''"

    # Both halves come from one call, so the note cannot describe a different
    # read of the valve than the value does.
    tree = ast.parse(source)
    unpacked = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and 'area_deadline' in ast.unparse(node)
        and '_area_deadline_seconds()' in ast.unparse(node)
    ]
    assert unpacked == [
        'area_deadline, area_deadline_note = _area_deadline_seconds()'
    ], unpacked


# ------------- the gate: a named project is the only one that can be a member

TENGKELI = 'Тенгкели-Березовская площадь'


def _both_projects(number):
    """The row pair the reported run produced: the registry and the caller's."""
    return [
        licence(number, project='GIS_Data_RF', layer='Licenses_2024_2025'),
        licence(number, project=TENGKELI, layer='Sint_licences_2025exp_clp'),
    ]


@pytest.mark.asyncio
async def test_a_named_project_is_honoured_even_when_the_search_ignores_it():
    """The reported run, reproduced: the message came back character for
    character only when the search returned rows from every project.

    The single-object path has had this condition since the beginning -- a
    supplied project short-circuits the cross-project search. The area path had
    none, so it searched everywhere and then reported the ambiguity its own
    message says a `project_id` removes. Two deployables release separately, so
    the caller's side cannot assume the search scoped: it applies the scope it
    was given to the answer it got back.
    """
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: _both_projects(number)})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert len(answer['members']) == 1
    member = answer['members'][0]
    assert member['project_id'] == TENGKELI
    assert member['licence_layer_id'] == 'Sint_licences_2025exp_clp'


@pytest.mark.asyncio
async def test_the_registry_is_never_a_candidate_beside_a_named_project():
    """`GIS_Data_RF` holds almost any licence in the country. The message has
    said this from the start; the code did not act on it."""
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: _both_projects(number)})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert [m['project_id'] for m in answer['members']] == [TENGKELI]
    assert 'GIS_Data_RF' not in [m['project_id'] for m in answer['members']]


@pytest.mark.asyncio
async def test_the_gate_applies_to_every_member_and_not_once_per_call():
    """The area resolves N licences. A caller who names a project has named it
    for all of them, so the condition is per member -- and each member is a
    separate search that can come back unscoped."""
    numbers = ['МАГ04805БЭ', 'МАГ05018БР', 'МАГ05252БР']
    gis = registry(
        scopes=False, **{number: _both_projects(number) for number in numbers}
    )

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=numbers, project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert [m['project_id'] for m in answer['members']] == [TENGKELI] * 3
    assert [m['licence_id'] for m in answer['members']] == numbers
    # Every member was searched, not just the first.
    assert len(gis.scope_queries) == 3
    assert all(q.get('project_id') == TENGKELI for q in gis.scope_queries)


@pytest.mark.asyncio
async def test_two_layers_of_one_project_still_refuses_after_the_gate():
    """The refusal that remains, and it is the right one.

    With the project scoped, two hits in two layers are states of one licence
    -- current, annulled, junior -- and folding them would choose a state for
    the user. Two hits in two projects stops being reachable; this does not.
    """
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: [
        licence(number, project=TENGKELI, layer='Licenses_2024_2025'),
        licence(number, project=TENGKELI, layer='Licenses_annul'),
    ]})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_AMBIGUOUS
    # The within-project refusal, not the cross-project one.
    assert 'Строки из разных проектов' not in answer['message']
    assert 'состояния одной лицензии' in answer['message']


@pytest.mark.asyncio
async def test_without_a_project_the_cross_project_ambiguity_is_unchanged():
    """The gate is a condition on a supplied value, not a new default. A caller
    who named no project still gets the refusal that asks them to."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: _both_projects(number)})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=[number])

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_AMBIGUOUS
    assert 'Строки из разных проектов' in answer['message']


# ------------------------------- what the refusal says it received


def test_the_four_received_states_read_as_the_task_wrote_them():
    """One line per refusal site, and it ends the class rather than this
    instance. Four refusals in this path have asked for something already
    supplied; «не передан» and «принят» are one line apart."""
    assert received_line('project_id', '', ARG_NOT_PASSED) == 'project_id: (не передан)'
    assert received_line('project_id', TENGKELI, ARG_NOT_FOUND) == (
        f"project_id: '{TENGKELI}' — не найден среди проектов"
    )
    assert received_line('project_id', TENGKELI, ARG_ACCEPTED) == (
        f"project_id: '{TENGKELI}' — принят"
    )
    # The fourth, which the other three cannot express: sent and dropped.
    assert 'сервис его не применил' in received_line(
        'project_id', TENGKELI, ARG_NOT_HONOURED
    )


def test_an_unknown_received_state_raises_rather_than_picking_a_wording():
    """A line whose job is to be true about what arrived is the last place to
    guess. A new refusal site inventing a state must fail loudly."""
    with pytest.raises(ValueError):
        received_line('project_id', 'x', 'probably_fine')


@pytest.mark.asyncio
async def test_the_ambiguity_that_asks_for_a_project_says_what_it_received():
    """«Укажите `project_id`» to a caller who supplied one is the whole defect."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: _both_projects(number)})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=[number])

    assert 'project_id: (не передан)' in answer['message']


@pytest.mark.asyncio
async def test_an_accepted_project_is_echoed_on_the_refusal_that_remains():
    """The caller whose scope worked is looking at a different problem, and
    «принят» is what tells them so instead of re-sending what already worked."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: [
        licence(number, project=TENGKELI, layer='Licenses_2024_2025'),
        licence(number, project=TENGKELI, layer='Licenses_annul'),
    ]})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert f"project_id: '{TENGKELI}' — принят" in answer['message']


@pytest.mark.asyncio
async def test_a_project_the_search_dropped_and_no_row_carries_is_its_own_refusal():
    """Sent, answered unscoped, and no returned row carries the value.

    The caller may have named the project the way a person does while the rows
    carry the store's id, and only the service resolves one to the other.
    Dropping every row would fabricate «не найдена»; keeping them would re-ask
    for `project_id`.
    """
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: _both_projects(number)})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number],
        project_id='Единый реестр лицензий РФ',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SCOPE_NOT_APPLIED
    assert 'сервис его не применил' in answer['message']
    assert 'не найдена' not in answer['message']
    assert sorted(answer['projects_offered']) == ['GIS_Data_RF', TENGKELI]


@pytest.mark.asyncio
async def test_one_project_in_the_answer_is_never_narrowed_here():
    """Nothing to narrow is not narrowing. Claiming the scope was applied when
    the answer held one project would put a true-sounding sentence on a run
    that never exercised it."""
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: [
        licence(number, project=TENGKELI, layer='Sint_licences_2025exp_clp'),
    ]})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['project_id'] == TENGKELI


# ------------- the answer is checked against its own claim, not taken on trust


def _fixed(rows, *, claims_scope=False):
    """A search that returns `rows` whatever it is asked, optionally claiming
    it scoped. The claim is the point: a service that says `scoped_to_project`
    and returns rows from elsewhere has not scoped."""
    async def call(payload):
        resolution = {'candidates': list(rows), 'searched_projects': 49026}
        scope = str(payload.get('project_id') or '').strip()
        if scope and claims_scope:
            resolution['scoped_to_project'] = scope
            resolution['searched_projects'] = 1
        return {'workflow_status': 'ok', 'scope_resolution': resolution}
    return call


@pytest.mark.asyncio
async def test_one_row_from_a_project_the_caller_did_not_name_is_refused():
    """The registry substitution, arriving silently instead of loudly.

    The old service ignores `project_id`, searches everywhere, and exactly one
    project holds the licence — not the caller's. One candidate is the
    auto-accept rule, so the area resolved against `GIS_Data_RF` and reported
    success. That is strictly worse than the over-cautious refusal it replaced:
    the guard that skipped the check when the answer offered a single project
    never asked whether that project was the one named.
    """
    rows = [licence('МАГ04805БЭ', project='GIS_Data_RF', layer='Licenses_2024_2025')]

    answer = await resolve_area_members(
        gis_call=_fixed(rows), licence_ids=['МАГ04805БЭ'], project_id=TENGKELI,
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SCOPE_NOT_APPLIED
    assert 'GIS_Data_RF' in answer['message']


@pytest.mark.asyncio
async def test_a_claimed_scope_carrying_foreign_rows_is_not_believed():
    """`scoped_to_project` is a claim, not a proof.

    Reading it alone made «принят» the one state that skipped every check, on
    the say-so of the thing being checked.
    """
    rows = [
        licence('МАГ04805БЭ', project=TENGKELI, layer='Sint_licences_2025exp_clp'),
        licence('МАГ04805БЭ', project='GIS_Data_RF', layer='Licenses_2024_2025'),
    ]

    answer = await resolve_area_members(
        gis_call=_fixed(rows, claims_scope=True),
        licence_ids=['МАГ04805БЭ'], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['project_id'] == TENGKELI
    assert 'принят' not in answer['scope_notice']


@pytest.mark.asyncio
async def test_two_project_ids_differing_only_in_case_are_several_not_one():
    """Case-folding matched both, and passing them on rebuilt the original bug.

    `Project1` and `PROJECT1` are two projects to the store and one string
    here. Merged, the answer became «Строки из разных проектов: Project1,
    PROJECT1. Укажите `project_id`» — asked of a caller who supplied it.
    """
    rows = [
        licence('МАГ04805БЭ', project='Project1', layer='L1'),
        licence('МАГ04805БЭ', project='PROJECT1', layer='L2'),
    ]

    answer = await resolve_area_members(
        gis_call=_fixed(rows), licence_ids=['МАГ04805БЭ'], project_id='project1',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SCOPE_AMBIGUOUS
    assert sorted(answer['matched_project_ids']) == ['PROJECT1', 'Project1']
    assert 'Строки из разных проектов' not in answer['message']


@pytest.mark.asyncio
async def test_a_row_that_names_no_project_is_refused_rather_than_taken():
    """Kept as the only candidate it becomes the member — an area filled from
    an unknown project, reported as success."""
    rows = [{'licence_id': 'МАГ04805БЭ', 'licence_layer_id': 'L1',
             'centroid_lon': 150.8, 'centroid_lat': 61.6}]

    answer = await resolve_area_members(
        gis_call=_fixed(rows), licence_ids=['МАГ04805БЭ'], project_id=TENGKELI,
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SCOPE_UNVERIFIABLE
    assert answer['rows_without_project'] == 1


@pytest.mark.asyncio
async def test_a_blank_project_beside_a_named_one_is_not_two_states_of_one_licence():
    """`_candidate_projects` drops the blank row, so the two «agree» and the
    refusal said «два состояния одной лицензии» about a row that may be from
    another project entirely."""
    rows = [
        licence('МАГ04805БЭ', project=TENGKELI, layer='L1'),
        {'licence_id': 'МАГ04805БЭ', 'licence_layer_id': 'L2',
         'centroid_lon': 150.8, 'centroid_lat': 61.6},
    ]

    answer = await resolve_area_members(
        gis_call=_fixed(rows), licence_ids=['МАГ04805БЭ'], project_id=TENGKELI,
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == SCOPE_UNVERIFIABLE
    assert 'состояния одной лицензии' not in answer['message']


@pytest.mark.asyncio
async def test_nothing_found_anywhere_does_not_claim_rows_from_other_projects():
    """The state said «поиск вернул строки из других проектов» when the search
    returned no rows at all, sending a reader to check projects that hold
    nothing. Only `_confine` may claim that, and only after seeing such a row.

    This also covers the echo at the `licence_not_found` site, which was
    deletable with the whole suite green.
    """
    gis = registry(scopes=False, **{'МАГ04805БЭ': [
        licence('МАГ04805БЭ', project=TENGKELI, layer='L1')]})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=['НЕТ00000БЭ'], project_id=TENGKELI,
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == LICENCE_NOT_FOUND
    assert 'строки из других проектов' not in answer['message']
    assert 'сужение по нему сервис не подтвердил' in answer['message']


@pytest.mark.asyncio
async def test_the_not_found_refusal_carries_the_echo_for_a_caller_with_no_project():
    """The echo at this site was deletable with every test green."""
    gis = registry(**{'МАГ04805БЭ': [licence('МАГ04805БЭ', project='p1')]})

    answer = await resolve_area_members(gis_call=gis.fill, licence_ids=['НЕТ00000БЭ'])

    assert answer['reason'] == LICENCE_NOT_FOUND
    assert 'project_id: (не передан)' in answer['message']


@pytest.mark.asyncio
async def test_a_project_that_does_not_exist_echoes_not_found_at_the_refusal():
    """`ARG_NOT_FOUND` was pinned only in a direct unit test of `received_line`;
    its wording could change at the refusal site with the suite green."""
    gis = registry(**{'МАГ04805БЭ': [licence('МАГ04805БЭ', project='p1')]})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=['МАГ04805БЭ'], project_id='нет такого',
    )

    assert answer['reason'] == PROJECT_NOT_FOUND
    assert "project_id: 'нет такого' — не найден среди проектов" in answer['message']


@pytest.mark.asyncio
async def test_a_name_search_with_a_project_the_service_ignored_is_scoped_too():
    """The second search path reaches the same gate, and no test combined
    `object_name` with `project_id` against a service that does not scope."""
    gis = registry(
        scopes=False,
        **{'Лекын': [project_match('p1', 'Лекын-Тальбейское'),
                     project_match('GIS_Data_RF', 'Реестр')]},
    )

    answer = await resolve_area_members(
        gis_call=gis.fill, object_name='Лекын', project_id='p1',
    )

    assert answer['status'] == RESOLVED
    assert answer['members'][0]['project_id'] == 'p1'


@pytest.mark.asyncio
async def test_a_rescued_run_says_so_on_the_success_it_produces():
    """A refusal carries the state in its own text; a resolved area does not.

    Without this the deployment gap becomes permanently invisible the moment
    the compensation starts working: success looks identical whether the search
    scoped or was silently patched around on every call.
    """
    number = 'МАГ04805БЭ'
    gis = registry(scopes=False, **{number: _both_projects(number)})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert number in answer['scope_notice']
    assert 'компенсация' in answer['scope_notice']
    rendered = render_area_answer({
        'status': RESOLVED, 'cost_notice': answer['cost_notice'],
        'scope_notice': answer['scope_notice'],
        'result': {'area_id': 'a', 'counts': {'members': 1, 'filled': 1,
                   'failed': 0, 'not_attempted': 0}, 'members': [],
                   'aggregation': {}},
    })
    assert 'компенсация' in rendered


@pytest.mark.asyncio
async def test_a_run_the_service_scoped_itself_carries_no_rescue_notice():
    """A notice on a run that never needed one teaches readers to skip it."""
    number = 'МАГ04805БЭ'
    gis = registry(**{number: _both_projects(number)})

    answer = await resolve_area_members(
        gis_call=gis.fill, licence_ids=[number], project_id=TENGKELI,
    )

    assert answer['status'] == RESOLVED
    assert 'scope_notice' not in answer


def test_the_echo_never_raises_for_any_shape_the_search_can_produce():
    """`received_line` raises on an unknown state, which inside a refusal
    builder would replace a Russian refusal with an English exception blob.

    Unreachable today because `_search` sets the state from `scope_state`, and
    that is incidental rather than structural — so it is pinned here.
    """
    for state in (ARG_NOT_PASSED, ARG_NOT_FOUND, ARG_ACCEPTED,
                  ARG_NOT_CONFIRMED, ARG_NOT_HONOURED):
        assert _scope_echo({'project_id_received': 'x', 'project_id_state': state})
    assert _scope_echo({}) == 'project_id: (не передан)'


# ------------------------- the policy is checked, not echoed


def test_a_policy_version_nobody_has_is_refused_and_names_both_values():
    """`2024` was sent, folded and echoed as «Свёрнуто по политике `2024`».

    There is one policy and its version is pinned in four places at once. The
    field is required by the tool and its value is not discoverable from it, so
    a model fills it with a guess — and a fold that names a policy it did not
    use is the reproducibility claim the requirement exists to protect,
    inverted.
    """
    contract = resolve_contract(
        policy_version='2024', calculation_crs=CRS, members=[],
    )

    assert contract['status'] == REFUSED
    assert contract['reason'] == POLICY_VERSION_UNKNOWN
    assert contract['failed'] == 'policy_version'
    # Both values: what was sent, and what is current.
    assert '`2024`' in contract['message']
    assert POLICY in contract['message']
    # And the way out, which is to send nothing.
    assert 'Не указывайте `policy_version`' in contract['message']


def test_the_one_policy_that_exists_is_accepted_as_supplied():
    """Checked, not replaced: a caller who names the right one is not overridden."""
    contract = resolve_contract(
        policy_version=POLICY, calculation_crs=CRS, members=[],
    )

    assert contract['status'] == RESOLVED
    assert contract['policy_version'] == {'value': POLICY, 'source': 'supplied'}


def test_an_absent_policy_still_resolves_to_the_current_one():
    """The field was made optional with a resolved default and stays optional.
    This run shows a caller guessing when it is not."""
    contract = resolve_contract(
        policy_version='', calculation_crs=CRS, members=[],
    )

    assert contract['status'] == RESOLVED
    assert contract['policy_version']['value'] == POLICY
    assert contract['policy_version']['source'] == 'resolved'


@pytest.mark.asyncio
async def test_a_guessed_policy_refuses_the_area_before_anything_is_filled():
    """The refusal has to reach the caller, not just the helper."""
    numbers = ['МАГ04805БЭ']
    gis = registry(**{number: [licence(number)] for number in numbers})

    answer = await fill_area(
        gis_call=gis.fill, scope_call=gis.scope, fold_call=gis.fold,
        member_fill=fill, licence_ids=numbers,
        policy_version='2024', calculation_crs=CRS,
        area_scope_id='area-x', dossier_run_id='dossier-1',
    )

    assert answer['status'] == REFUSED
    assert answer['reason'] == POLICY_VERSION_UNKNOWN
    assert gis.fold_payload is None, 'nothing may be folded under a policy nobody has'


def test_the_zero_member_summary_points_at_the_reasons_above_it():
    """`fold_failed` described the fold answering without an aggregation —
    true, and not what happened. The per-member reasons are already printed
    directly above this line."""
    rendered = render_area_answer({
        'status': RESOLVED,
        'result': {
            'area_id': 'area-x',
            'counts': {'members': 3, 'filled': 0, 'failed': 3, 'not_attempted': 0},
            'members': [],
            'aggregation': {
                'state': 'not_performed',
                'reason': 'nothing_filled',
                'members_total': 3,
                'members_filled': 0,
            },
        },
    })

    assert 'ни один участник не заполнен (0 из 3)' in rendered
    assert 'Причины по участникам — выше.' in rendered
    assert 'fold_failed' not in rendered


@pytest.mark.asyncio
async def test_one_member_fills_end_to_end_with_its_own_licence():
    """The run this task exists to make possible, from the caller's arguments
    to the card: a licence number in, a filled member out, and the fill
    launched with that licence rather than the area's name."""
    seen = {}

    async def member_fill(*, object_name, project_id=None, licence_id=None,
                          licence_layer_id=None, **_):
        seen.update({
            'object_name': object_name, 'project_id': project_id,
            'licence_id': licence_id, 'licence_layer_id': licence_layer_id,
        })
        return {
            'run_id': f'run-{licence_id}', 'status': 'finalized',
            'audit': {'completeness': {'filled': 196, 'of': 351}},
        }

    gis = registry(**{'МАГ04805БЭ': [
        licence('МАГ04805БЭ', project=TENGKELI, layer='Sint_licences_2025exp_clp'),
    ]})

    answer = await fill_area(
        gis_call=gis.fill, scope_call=gis.scope, fold_call=gis.fold,
        member_fill=member_fill, licence_ids=['МАГ04805БЭ'],
        project_id=TENGKELI, calculation_crs=CRS,
        area_scope_id='area-tengkeli', dossier_run_id='dossier-1',
    )

    assert answer['status'] == RESOLVED
    assert seen['licence_id'] == 'МАГ04805БЭ'
    assert seen['licence_layer_id'] == 'Sint_licences_2025exp_clp'
    assert seen['project_id'] == TENGKELI
    assert seen['object_name'] == ''
    result = answer['result']
    assert result['counts'] == {
        'members': 1, 'filled': 1, 'failed': 0, 'not_attempted': 0,
    }
    rendered = render_area_answer(answer)
    assert 'run-МАГ04805БЭ' in rendered
    assert 'МАГ04805БЭ — заполнен' in rendered


@pytest.mark.asyncio
async def test_an_area_where_every_member_fails_says_so_from_end_to_end():
    """Three disjoint pieces that no test joined: the workflow producing the
    reason, the renderer rendering it, and `fill_area` reaching either.

    The renderer test feeds a hand-built aggregation, so it proves only that a
    correctly-shaped dict renders; the workflow test stops at the returned
    value. Between them a wrong reason could reach a right renderer and nothing
    would notice.
    """
    numbers = ['МАГ04805БЭ', 'МАГ05018БР']
    gis = registry(**{number: [licence(number)] for number in numbers})

    async def always_fails(**kwargs):
        raise RuntimeError('specialist timeout')

    answer = await fill_area(
        gis_call=gis.fill, scope_call=gis.scope, fold_call=gis.fold,
        member_fill=always_fails, licence_ids=numbers,
        calculation_crs=CRS, area_scope_id='area-x', dossier_run_id='dossier-1',
    )

    assert answer['status'] == RESOLVED
    aggregation = answer['result']['aggregation']
    assert aggregation['reason'] == 'nothing_filled'
    assert aggregation['members_total'] == 2
    # Nothing was folded, because there was nothing to fold.
    assert gis.fold_payload is None

    rendered = render_area_answer(answer)
    assert 'ни один участник не заполнен (0 из 2)' in rendered
    assert 'Причины по участникам — выше.' in rendered
    # And the per-member reasons really are above it.
    assert rendered.index('МАГ04805БЭ') < rendered.index('Свод не построен')


@pytest.mark.asyncio
async def test_a_member_is_named_by_its_licence_and_not_by_its_dossier_id():
    """The end-to-end test above uses a licence number that is also the
    `entity_id`, so it cannot tell the workflow's own fallback from
    `render_area_answer`'s. This one separates them."""
    rows = [{
        'project_id': 'p1', 'licence_id': 'МАГ04805БЭ',
        'licence_layer_id': 'L1', 'centroid_lon': 150.8, 'centroid_lat': 61.6,
    }]

    async def search(payload):
        return {'workflow_status': 'ok',
                'scope_resolution': {'candidates': rows, 'searched_projects': 1}}

    resolved = await resolve_area_members(gis_call=search, licence_ids=['МАГ04805БЭ'])
    member = resolved['members'][0]

    # `_member` names the row by its licence because a licence candidate
    # carries no `object_name` at all — that is the value the area sends on,
    # and the workflow blanks it precisely because it was never a name.
    assert member['object_name'] == 'МАГ04805БЭ'
    assert member['licence_id'] == 'МАГ04805БЭ'


def test_the_adapter_forwards_the_policy_the_caller_named():
    """`fill_geoteaser_area` cannot be imported here — `open_webui.config`
    deletes tracked files under `backend/open_webui/static` as an import side
    effect, so a test that imported it would damage the tree it tests. Its call
    sites are read instead, the way the rest of this adapter is checked.

    Without this the policy refusal is verified one layer below the entry point
    a model actually calls, and a dropped argument there would restore the old
    unvalidated behaviour with every service-level test still green.
    """
    keywords = _call_keywords('fill_geoteaser_area', 'fill_area')

    assert keywords.get('policy_version') == 'policy_version.strip()'
    assert keywords.get('licence_ids') == 'licence_ids or ()'
    assert keywords.get('calculation_crs') == 'calculation_crs.strip()'
