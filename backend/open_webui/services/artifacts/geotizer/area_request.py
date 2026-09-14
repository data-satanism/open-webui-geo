"""Turning what a user said into an area's members, or into a question.

`fill_geoteaser` takes one object and one licence. `fill_geoteaser_area` takes
several, and the difference is not a flag: the first thing an area has to do is
decide which licences it is about, and that decision has four outcomes where
the object tool has two.

**Supplied beats searched.** «заполни область из лицензий МАГ03394БЭ,
СЛХ025834ТП, АНД01313БП» is three numbers and no ambiguity. A tool that
searched anyway would turn an unambiguous request into a question, which is the
same discourtesy as guessing, pointed the other way.

**A name that resolves to several is ambiguous by nature.** «Лекын-Тальбейская
площадь» is both an area and a registry project holding the whole country.
Guessing produces either a run nobody asked for or one object where several
were wanted, so the question is asked and never inferred -- and it carries what
it costs, because a user choosing «all of them» is choosing days.

**A number that resolves to nothing refuses the whole request.** Filling two of
three gives an area whose `members_total` is 2 when three were asked for, and
every folded figure is then honest about a membership the user did not choose.
The fold would be right and the answer would be wrong.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Awaitable, Callable

from .area_workflow import PERFORMED, run_geotizer_area_workflow

#: Hours one member costs, measured rather than estimated. A-169: two runs of
#: one object at 2 h 32 m and 2 h 48 m, from `started_at` to `finalized_at`.
#: A-164's «four to seven minutes» was an estimate and was thirty times out, so
#: this figure is the one the refusal and the question are both written from.
MEMBER_HOURS = 2.6

#: The smallest thing worth calling an area, at the measured per-member cost:
#: three members, 7.8 hours. Not a round number and not the object path's six
#: hours -- an area of one is an object, and an area of two cannot show a fold
#: doing anything a pair could not.
#:
#: This is the valve. §3 is deferred, so the ceiling exists to make the limit
#: visible rather than discovered at hour four; when the job model lands the
#: ceiling is what moves, and nothing else here has to.
DEFAULT_AREA_DEADLINE_SECONDS = 3 * MEMBER_HOURS * 3600

RESOLVED = 'resolved'
ASK = 'ask'
REFUSED = 'refused'

#: Why a resolution refused, in words a caller acts on.
NOTHING_TO_RESOLVE = 'nothing_to_resolve'
LICENCE_NOT_FOUND = 'licence_not_found'
LICENCE_AMBIGUOUS = 'licence_ambiguous'
TOO_MANY_MEMBERS = 'too_many_members'

GisCall = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def member_ceiling(area_deadline_seconds: float | None = None) -> int:
    """How many members fit inside the deadline, at the measured cost.

    Derived, not chosen: the ceiling is whatever the deadline divided by a
    member comes to, so moving the valve moves the limit and no second number
    has to be kept in step with it.
    """
    seconds = float(
        area_deadline_seconds
        if area_deadline_seconds is not None
        else DEFAULT_AREA_DEADLINE_SECONDS
    )
    return max(1, int(seconds // (MEMBER_HOURS * 3600)))


def _members_word(count: int) -> str:
    """«участник», «участника», «участников» -- Russian counts one, few, many.

    Spelled out because the alternative is «21 участников» in a refusal whose
    whole job is to be read and believed. The rule is the ordinary one: 11-14
    take the many form whatever their last digit says.
    """
    tail_two, tail = count % 100, count % 10
    if 11 <= tail_two <= 14:
        return 'участников'
    if tail == 1:
        return 'участник'
    if tail in (2, 3, 4):
        return 'участника'
    return 'участников'


def _licences_word(count: int) -> str:
    """«лицензия», «лицензии», «лицензий».

    Separate from `_members_word` because the question is asked BEFORE anything
    is a member: what the search found is licences, and calling them members in
    the sentence that asks whether to make them members answers its own
    question.
    """
    tail_two, tail = count % 100, count % 10
    if 11 <= tail_two <= 14:
        return 'лицензий'
    if tail == 1:
        return 'лицензия'
    if tail in (2, 3, 4):
        return 'лицензии'
    return 'лицензий'


def _hours_word(hours: float) -> str:
    whole = int(round(hours))
    tail_two, tail = whole % 100, whole % 10
    if 11 <= tail_two <= 14:
        return 'часов'
    if tail == 1:
        return 'час'
    if tail in (2, 3, 4):
        return 'часа'
    return 'часов'


def cost_phrase(count: int) -> str:
    """«N участников, примерно H часов» -- the line the question turns on.

    A user choosing «all of them» should know it is two days rather than two
    hours, and this project measured that instead of estimating it.
    """
    hours = count * MEMBER_HOURS
    return (
        f'{count} {_members_word(count)}, примерно '
        f'{hours:.0f} {_hours_word(hours)}'
    )


def too_many_members(count: int, ceiling: int) -> str:
    """The refusal that costs a second instead of a day.

    §3 is deferred: there is no job model, so the call runs to completion and a
    request larger than the deadline dies partway with nothing to show. A tool
    that accepts twenty-one members and stops at hour four has lost a day and
    produced nothing; one that refuses in a second has cost nothing and said
    why. This is the honest form of «not implemented».
    """
    return (
        f'{cost_phrase(count)}. Это превышает время ожидания запроса; '
        f'областное заполнение такого размера пока не поддерживается '
        f'(предел — {ceiling} {_members_word(ceiling)}).\n'
        f'Заполните меньшую область или отдельные объекты.'
    )


def _candidate_line(candidate: Mapping[str, Any]) -> str:
    """One licence as the question lists it: the number, and a name when known.

    A name is printed only where one exists. «МАГ03394БЭ — »  with nothing
    after the dash reads as a name that failed to load rather than a licence
    the registry never named.
    """
    number = str(candidate.get('licence_id') or candidate.get('project_id') or '').strip()
    name = str(candidate.get('object_name') or '').strip()
    return f'- {number} — {name}' if name else f'- {number}'


def licence_question(query: str, candidates: Sequence[Mapping[str, Any]]) -> str:
    """Everything needed to answer without another lookup.

    How many were found, which ones, the object name for each where one is
    known, and what «all of them» costs. A question a user has to research
    before answering is a question that gets answered by guessing.
    """
    count = len(candidates)
    listed = '\n'.join(_candidate_line(item) for item in candidates)
    return (
        f'По запросу «{query}» найдено {count} {_licences_word(count)}:\n\n'
        f'{listed}\n\n'
        f'Заполнить все как площадь — это {cost_phrase(count)}.\n'
        f'Либо назовите одну лицензию, и она будет заполнена как отдельный объект.'
    )


def _member(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """A resolved candidate as an area member.

    `entity_id` is the licence number and says so. The dossier owns entity
    identity -- a member the dossier does not have is a member this run
    invented -- and the licence search cannot supply a `projectEntity` id: it
    returns a project, a number and a layer. So the identity carried here is
    the one thing that was actually established, and `entity_id_source` is what
    stops a later reader taking it for a dossier row. When a dossier lookup is
    wired, it replaces the value and the source says which is which.
    """
    licence_id = str(candidate.get('licence_id') or '').strip()
    project_id = str(candidate.get('project_id') or '').strip()
    name = str(candidate.get('object_name') or '').strip()
    return {
        'entity_id': licence_id or project_id,
        'entity_id_source': 'licence_id' if licence_id else 'project_id',
        'entity_type': 'licence',
        'object_name': name or licence_id or project_id,
        'project_id': project_id or None,
        'licence_id': licence_id or None,
        'licence_layer_id': str(candidate.get('licence_layer_id') or '') or None,
    }


async def _search(gis_call: GisCall, query: str) -> dict[str, Any]:
    return await gis_call({'action': 'resolve_scope', 'query': query})


async def resolve_area_members(
    *,
    gis_call: GisCall,
    object_name: str = '',
    licence_ids: Sequence[str] = (),
    area_deadline_seconds: float | None = None,
) -> dict[str, Any]:
    """Which licences this area is about — or the question, or the refusal.

    One shape for both tools, and the first row is the case a user is most
    likely in:

        licence_ids given         use them — no search, no question
        none, one licence found   use it, say which
        none, several found       ask
        none, zero found          refuse, naming what was searched
    """
    ceiling = member_ceiling(area_deadline_seconds)
    supplied = [str(item or '').strip() for item in licence_ids]
    supplied = [item for item in supplied if item]

    if supplied:
        members: list[dict[str, Any]] = []
        for number in supplied:
            answer = await _search(gis_call, number)
            resolution = answer.get('scope_resolution') or {}
            candidates = list(resolution.get('candidates') or [])
            if len(candidates) == 1:
                members.append(_member(candidates[0]))
                continue
            # Refuse the whole request, not this member. Filling the rest would
            # produce an area whose membership the user did not choose, and
            # every folded figure would then be honest about the wrong area.
            if not candidates:
                return {
                    'status': REFUSED,
                    'reason': LICENCE_NOT_FOUND,
                    'licence_id': number,
                    'message': _not_found_message(supplied, number, resolution),
                }
            return {
                'status': REFUSED,
                'reason': LICENCE_AMBIGUOUS,
                'licence_id': number,
                'candidates': candidates,
                'message': (
                    f'{number} найдена в нескольких слоях ({len(candidates)}). '
                    'Область не заполнена: пока не ясно, о каком объекте речь, '
                    'членство площади выбрано не пользователем.'
                ),
            }
        if len(members) > ceiling:
            return {
                'status': REFUSED,
                'reason': TOO_MANY_MEMBERS,
                'members_total': len(members),
                'ceiling': ceiling,
                'message': too_many_members(len(members), ceiling),
            }
        return {'status': RESOLVED, 'members': members, 'resolved_from': 'supplied'}

    query = str(object_name or '').strip()
    if not query:
        return {
            'status': REFUSED,
            'reason': NOTHING_TO_RESOLVE,
            'message': (
                'Нужны номера лицензий или название площади: '
                'искать нечего и спрашивать не о чем.'
            ),
        }

    answer = await _search(gis_call, query)
    resolution = answer.get('scope_resolution') or {}
    candidates = list(resolution.get('candidates') or [])

    if len(candidates) == 1:
        return {
            'status': RESOLVED,
            'members': [_member(candidates[0])],
            'resolved_from': 'search',
        }
    if not candidates:
        return {
            'status': REFUSED,
            'reason': LICENCE_NOT_FOUND,
            'message': _not_found_message([query], query, resolution),
        }
    return {
        'status': ASK,
        'question': licence_question(query, candidates),
        'candidates': candidates,
        'members_total': len(candidates),
        'ceiling': ceiling,
    }


def _not_found_message(
    asked: Sequence[str], missing: str, resolution: Mapping[str, Any]
) -> str:
    """A refusal that names what was searched, not just what was not found.

    «не найдена» alone leaves a caller unable to tell a wrong number from an
    unopened registry, which is the distinction `find_licence_across_projects`
    goes out of its way to preserve one layer down.
    """
    searched = resolution.get('searched_projects')
    unreadable = list(resolution.get('unreadable_projects') or [])
    lines = [
        f'- {number} — ' + ('не найдена' if number == missing else 'найдена')
        for number in asked
    ]
    tail = f'Искали в проектах: {searched}.' if searched is not None else ''
    if unreadable:
        tail += (
            f' Не удалось открыть: {len(unreadable)} — '
            '«не найдена» о них не утверждается.'
        )
    # One number asked for and not found is «nothing to fill»; several asked
    # for with one missing is «filling the rest would build an area the user
    # did not choose». The second sentence is false of the first case, and a
    # refusal that explains itself wrongly is worse than one that does not.
    verdict = (
        'Область не заполнена: заполнить остальные значило бы свести площадь, '
        'состав которой выбрал не пользователь.'
        if len(asked) > 1
        else 'Область не заполнена: заполнять нечего.'
    )
    return (
        '\n'.join(lines)
        + f'\n\n{verdict}'
        + (f'\n{tail}' if tail.strip() else '')
    )


MISSING_CONTRACT = 'contract_fields_missing'

#: What `AreaMember` accepts. The resolved member carries more than the scope
#: request will take -- `extra="forbid"` is the point of that request, and a
#: field it does not declare must be dropped here rather than discovered there.
_SCOPE_FIELDS = ('entity_id', 'entity_type', 'name')


def contract_refusal(policy_version: str, calculation_crs: str) -> str | None:
    """Refuse naming both, or None when both are there.

    Neither has a default and neither may be picked. A manifest without
    `policy_version` cannot be replayed, and a manifest replayed under a
    different policy is a different answer wearing the same id. Without
    `calculation_crs` every overlap is measured in square degrees, which is not
    an area and which no constant converts to one.
    """
    missing = [
        name
        for name, value in (
            ('policy_version', policy_version),
            ('calculation_crs', calculation_crs),
        )
        if not str(value or '').strip()
    ]
    if not missing:
        return None
    return (
        'Не заданы обязательные поля: ' + ', '.join(missing) + '.\n'
        'Ни одно из них не подставляется по умолчанию: без `policy_version` '
        'манифест невозможно воспроизвести, а без `calculation_crs` площадь '
        'меряется в квадратных градусах, что площадью не является.'
    )


async def fill_area(
    *,
    gis_call: GisCall,
    member_fill: Callable[..., Awaitable[dict[str, Any]]],
    object_name: str = '',
    licence_ids: Sequence[str] = (),
    project_id: str = '',
    area_scope_id: str = '',
    policy_version: str = '',
    calculation_crs: str = '',
    dossier_run_id: str = '',
    area_deadline_seconds: float | None = None,
    member_arguments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve, fill, fold and summarise — or ask, or refuse.

    Returns a dict carrying `status` and, when there is one, `result`. The
    caller renders; nothing here writes Markdown, for the same reason the
    object path's wording lives in `terminal.py`.
    """
    refusal = contract_refusal(policy_version, calculation_crs)
    if refusal:
        return {'status': REFUSED, 'reason': MISSING_CONTRACT, 'message': refusal}

    resolution = await resolve_area_members(
        gis_call=gis_call,
        object_name=object_name,
        licence_ids=licence_ids,
        area_deadline_seconds=area_deadline_seconds,
    )
    if resolution['status'] != RESOLVED:
        return resolution

    members = resolution['members']
    area_id = str(area_scope_id or '').strip() or f'area:{object_name or ",".join(licence_ids)}'
    owner_project = str(project_id or '').strip() or str(
        members[0].get('project_id') or ''
    )

    manifest = await gis_call(
        {
            'action': 'resolve_area_scope',
            'project_id': owner_project,
            'area_scope_id': area_id,
            'policy_version': policy_version,
            'calculation_crs': calculation_crs,
            'members': [
                {key: member[key] for key in _SCOPE_FIELDS if member.get(key)}
                | {'name': member['object_name']}
                for member in members
            ],
        }
    )

    # The manifest is authoritative about membership and says nothing about how
    # to fill a member. Merged by `entity_id` rather than by position: the
    # resolver is free to order members however the hierarchy requires, and a
    # zip would silently pair the wrong card with the wrong licence.
    fill_fields = {
        member['entity_id']: {
            'object_name': member['object_name'],
            'project_id': member.get('project_id'),
        }
        for member in members
    }
    merged = dict(manifest)
    merged['area_id'] = merged.get('area_id') or area_id
    merged['members'] = [
        dict(item) | fill_fields.get(str(item.get('entity_id') or ''), {})
        for item in (manifest.get('members') or [])
    ]

    outcome = await run_geotizer_area_workflow(
        manifest=merged,
        member_fill=member_fill,
        member_arguments=member_arguments,
        area_deadline_seconds=area_deadline_seconds,
        fold_call=gis_call,
        policy_version=policy_version,
        dossier_run_id=str(dossier_run_id or '').strip() or area_id,
    )
    return {'status': RESOLVED, 'resolved_from': resolution['resolved_from'], 'result': outcome}


def _member_line(item: Mapping[str, Any]) -> str:
    """One member as the answer lists it: what happened, and how to reach it.

    A filled member carries its `run_id` because that is what a caller inspects
    it with -- §3 is deferred, so there is no area-level id to poll, and the
    per-member ids are the only handles that exist.
    """
    name = str(item.get('object_name') or item.get('entity_id') or '')
    state = str(item.get('state') or '')
    if state == 'filled':
        completeness = item.get('completeness') or {}
        filled = completeness.get('filled')
        of = completeness.get('of')
        figure = f' — {filled} из {of}' if filled is not None and of else ''
        return f'- {name} — заполнен{figure} (`{item.get("run_id")}`)'
    if state == 'failed':
        return f'- {name} — не заполнен: {item.get("error")}'
    return f'- {name} — не начинался: {item.get("reason")}'


def render_area_answer(payload: Mapping[str, Any]) -> str:
    """The Markdown a user reads, for every outcome this tool has.

    A question and a refusal are answers too, and rendering them here rather
    than at the adapter is the same rule the object path follows: choosing the
    words a user reads is rendering, and rendering belongs in the core.
    """
    status = payload.get('status')
    if status == ASK:
        return str(payload.get('question') or '')
    if status == REFUSED:
        return str(payload.get('message') or '')

    result = payload.get('result') or {}
    members = list(result.get('members') or [])
    counts = result.get('counts') or {}
    aggregation = result.get('aggregation') or {}

    lines = [
        f'Площадь `{result.get("area_id")}`: '
        f'{counts.get("members", 0)} {_members_word(int(counts.get("members", 0)))}, '
        f'заполнено {counts.get("filled", 0)}, '
        f'не заполнено {counts.get("failed", 0)}, '
        f'не начиналось {counts.get("not_attempted", 0)}.',
        '',
        *[_member_line(item) for item in members],
        '',
    ]

    if aggregation.get('state') == PERFORMED:
        markdown = str(result.get('summary_markdown') or '').strip()
        lines.append(markdown or 'Свод построен, но пуст.')
    else:
        # Named, never absent. «Свода нет» with no reason is the shape this
        # whole document is written against.
        reason = aggregation.get('reason')
        detail = aggregation.get('error') or aggregation.get('missing')
        lines.append(f'Свод не построен: {reason}' + (f' ({detail})' if detail else ''))

    return '\n'.join(lines)
