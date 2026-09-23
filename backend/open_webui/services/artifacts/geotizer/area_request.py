"""Turning what a user said into an area's members, or into a question.

Supplied licence numbers are used as given, with no search and no question. A
name that resolves to several licences produces a question listing them and
the cost of filling all of them; one is never chosen for the user. A supplied
number that resolves to nothing, or to several rows, refuses the whole request.
"""

from __future__ import annotations

import math

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from .area_workflow import (
    DEFAULT_CONCURRENT_MEMBERS,
    PERFORMED,
    run_geotizer_area_workflow,
)
from .terminal import StatusSettings, _emit_status

MEMBER_HOURS = 2.6

DEFAULT_AREA_DEADLINE_SECONDS: float | None = None

RESOLVED = 'resolved'
ASK = 'ask'
REFUSED = 'refused'

NOTHING_TO_RESOLVE = 'nothing_to_resolve'
LICENCE_NOT_FOUND = 'licence_not_found'
LICENCE_AMBIGUOUS = 'licence_ambiguous'
LAYER_NOT_AMONG_CANDIDATES = 'licence_layer_not_among_candidates'
SEARCH_UNREADABLE = 'search_unreadable'
MANIFEST_WITHOUT_MEMBERS = 'manifest_without_members'
PROJECT_NOT_FOUND = 'scope_project_not_found'
SCOPE_NOT_APPLIED = 'scope_not_applied'
SCOPE_UNVERIFIABLE = 'scope_unverifiable'
SCOPE_AMBIGUOUS = 'scope_ambiguous'
POLICY_VERSION_UNKNOWN = 'policy_version_unknown'

GisCall = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


AREA_CONCURRENCY_VALVE = 'GEOMAS_AREA_CONCURRENT_MEMBERS'


def concurrent_members(raw: Any) -> tuple[int, str | None]:
    """How many members fill at once, from the valve's raw string, plus a note.

    Returns `(DEFAULT_CONCURRENT_MEMBERS, None)` when unset, `(count, None)` for a
    positive integer, and `(DEFAULT_CONCURRENT_MEMBERS, note)` when the value is
    not an integer or is not positive. The count bounds load, never the number of
    members.
    """
    if raw in (None, ''):
        return DEFAULT_CONCURRENT_MEMBERS, None
    try:
        count = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_CONCURRENT_MEMBERS, (
            f'{AREA_CONCURRENCY_VALVE}={raw!r} — не целое число; '
            f'участники идут по {DEFAULT_CONCURRENT_MEMBERS} одновременно.'
        )
    if count <= 0:
        return DEFAULT_CONCURRENT_MEMBERS, (
            f'{AREA_CONCURRENCY_VALVE}={raw!r} — не положительное число; '
            f'участники идут по {DEFAULT_CONCURRENT_MEMBERS} одновременно.'
        )
    return count, None


def area_deadline_seconds(raw: Any) -> tuple[float | None, str | None]:
    """The area's deadline from the valve's raw string, and a note when refused.

    Returns `(None, None)` when nothing is configured, `(seconds, None)` for a
    positive number, and `(None, note)` when a value was set that is not a number
    or is not positive.
    """
    if raw in (None, ''):
        return None, None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None, (
            f'GEOMAS_AREA_DEADLINE_SECONDS={raw!r} — не число; '
            'площадь идёт без ограничения по времени.'
        )
    if seconds <= 0:
        return None, (
            f'GEOMAS_AREA_DEADLINE_SECONDS={raw!r} — не положительное число; '
            'площадь идёт без ограничения по времени.'
        )
    return seconds, None


def _members_word(count: int) -> str:
    """«участник», «участника», «участников» by count, always in Russian.

    Delegates to `StatusSettings.members_word`.
    """
    return StatusSettings(language='ru').members_word(count)


def _licences_word(count: int) -> str:
    """«лицензия», «лицензии», «лицензий» by count."""
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
    """«N участников, примерно H часов», at `MEMBER_HOURS` per member."""
    hours = count * MEMBER_HOURS
    return (
        f'{count} {_members_word(count)}, примерно '
        f'{hours:.0f} {_hours_word(hours)}'
    )


def cost_notice(count: int) -> str:
    """What the run will cost, that the browser request will end first, and that members keep filling.

    Not a refusal.
    """
    return (
        f'{cost_phrase(count)}. Запрос браузера прервётся раньше; '
        f'участники продолжат заполняться, и их карточки будут готовы.\n'
        f'Свод по площади соберётся, когда закончится последний.'
    )


def _candidate_line(candidate: Mapping[str, Any]) -> str:
    """One licence as the question lists it: the number, and the object name when known."""
    number = str(candidate.get('licence_id') or candidate.get('project_id') or '').strip()
    name = str(candidate.get('object_name') or '').strip()
    return f'- {number} — {name}' if name else f'- {number}'


def licence_question(query: str, candidates: Sequence[Mapping[str, Any]]) -> str:
    """The question asked when a name search finds several licences.

    Lists the count, each licence with its object name where known, and the cost
    of filling all of them.
    """
    count = len(candidates)
    listed = '\n'.join(_candidate_line(item) for item in candidates)
    return (
        f'По запросу «{query}» найдено {count} {_licences_word(count)}:\n\n'
        f'{listed}\n\n'
        f'Заполнить все как площадь — это {cost_phrase(count)}.\n'
        f'Либо назовите одну лицензию, и она будет заполнена как отдельный объект.'
    )


_LAYER_MEANING_RU = {
    'Licenses_2024_2025': 'действующие',
    'Licenses_annul': 'аннулированные',
    'Juniors': 'юниорская программа',
}


def _candidate_layers(candidates: Sequence[Mapping[str, Any]]) -> list[str]:
    """The layer names, in the order found, de-duplicated."""
    seen: list[str] = []
    for item in candidates:
        name = str(item.get('licence_layer_id') or '').strip()
        if name and name not in seen:
            seen.append(name)
    return seen


_LAYER_UNNAMED_RU = '(слой не назван)'

_LAYER_STATE_UNKNOWN_RU = 'состояние не определено'


def _layer_lines(candidates: Sequence[Mapping[str, Any]]) -> str:
    """The candidates as a reader can act on them: one row per line.

    Each line names the layer (or `_LAYER_UNNAMED_RU`), its gloss from
    `_LAYER_MEANING_RU` (or `_LAYER_STATE_UNKNOWN_RU`), and the project when known.
    """
    lines = []
    for item in candidates:
        name = str(item.get('licence_layer_id') or '').strip()
        project = str(item.get('project_id') or '').strip()
        line = f'  {name or _LAYER_UNNAMED_RU}'
        line += f'    {_LAYER_MEANING_RU.get(name) or _LAYER_STATE_UNKNOWN_RU}'
        if project:
            line += f'    проект {project}'
        lines.append(line)
    return '\n'.join(lines)


def _candidate_projects(candidates: Sequence[Mapping[str, Any]]) -> list[str]:
    """The projects these rows came from, in order found, de-duplicated."""
    seen: list[str] = []
    for item in candidates:
        name = str(item.get('project_id') or '').strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def ambiguous_licence(
    number: str,
    candidates: Sequence[Mapping[str, Any]],
    echo: str = '',
) -> str:
    """The ambiguity refusal, naming what the caller can do about it.

    Rows from several projects: asks for `project_id`. Fewer distinct layers than
    rows: says nothing the caller holds can narrow them. Otherwise, several states
    of one licence: says no argument of this entry point selects a state. `echo`,
    when given, is printed after the rows.
    """
    layers = _candidate_layers(candidates)
    projects = _candidate_projects(candidates)
    head = (
        f'{number} найдена {len(candidates)} раз, в {len(layers)} слоях:\n'
        f'{_layer_lines(candidates)}\n'
        + (f'{echo}\n' if echo else '')
    )
    unnamed = [
        item for item in candidates
        if not str(item.get('licence_layer_id') or '').strip()
    ]
    unnamed_note = (
        f'\n{len(unnamed)} из строк без имени слоя — по слою такую строку '
        'выбрать нельзя.'
    ) if unnamed else ''

    if len(projects) > 1:
        return head + (
            'Строки из разных проектов: ' + ', '.join(projects) + '. '
            'Укажите `project_id` — поиск пойдёт только по нему, и строки из '
            'остальных проектов кандидатами не станут. `GIS_Data_RF` — '
            'общероссийский реестр, он содержит почти любую лицензию, поэтому '
            'совпадение в нём рядом с вашим проектом — это не двусмысленность.'
        ) + unnamed_note

    if len(layers) < len(candidates):
        return head + (
            'Слой их не различает: строки лежат в одном слое либо без имени '
            'слоя, и сузить их нечем — на этой точке входа выбора строки нет. '
            'Площадь не заполнена; сообщите об этих строках.'
        ) + unnamed_note

    return head + (
        'Это состояния одной лицензии — действующая, аннулированная, '
        'юниорская — с разной геометрией и разными датами, и свести их '
        'значило бы выбрать состояние за пользователя. Площадь не заполнена.\n'
        'Выбрать состояние на этой точке входа пока нельзя: параметра для '
        'этого у инструмента нет. Сообщите, какое состояние нужно.'
    ) + unnamed_note


def layer_not_found(
    number: str,
    wanted: str,
    candidates: Sequence[Mapping[str, Any]],
) -> str:
    """The refusal when the requested layer does not hold this licence; lists the layers that do."""
    return (
        f'Для {number} указан слой {wanted}, но лицензия в нём не найдена. '
        f'Она есть в {len(_candidate_layers(candidates))} слоях:\n'
        f'{_layer_lines(candidates)}\n'
        'Укажите один из них.'
    )


def _member(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """A resolved candidate as an area member.

    `entity_id` is the licence number, or the project id when there is none, and
    `entity_id_source` says which. Carries the candidate's centroid, or
    `centroid_unavailable` with gis_service's reason.
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
        'centroid_lon': candidate.get('centroid_lon'),
        'centroid_lat': candidate.get('centroid_lat'),
        'centroid_unavailable': candidate.get('centroid_unavailable'),
    }


ARG_NOT_PASSED = 'not_passed'
ARG_NOT_FOUND = 'not_found'
ARG_ACCEPTED = 'accepted'
ARG_NOT_CONFIRMED = 'not_confirmed'
ARG_NOT_HONOURED = 'not_honoured'

_RECEIVED_RU: dict[str, str] = {
    ARG_NOT_PASSED: '(не передан)',
    ARG_NOT_FOUND: '{value} — не найден среди проектов',
    ARG_ACCEPTED: '{value} — принят',
    ARG_NOT_CONFIRMED: (
        '{value} — передан; сужение по нему сервис не подтвердил, '
        'и строк из других проектов в ответе нет'
    ),
    ARG_NOT_HONOURED: (
        '{value} — передан, но поиск вернул строки из других проектов: '
        'сервис его не применил'
    ),
}


def received_line(name: str, value: Any, state: str) -> str:
    """One line naming an argument a refusal asks for, and how it arrived.

    `state` is one of the `ARG_*` states; any other raises `ValueError`.
    """
    if state not in _RECEIVED_RU:
        raise ValueError(f'unknown received state {state!r} for {name!r}')
    shown = repr(str(value)) if str(value or '').strip() else ''
    return f'{name}: ' + _RECEIVED_RU[state].format(value=shown)


def scope_state(named: str, resolution: Mapping[str, Any]) -> str:
    """How `project_id` fared, as far as the answer says.

    `not_passed` when none was sent; `not_found` when the search refused with
    `PROJECT_NOT_FOUND`; `accepted` when the answer carries `scoped_to_project`;
    `not_confirmed` otherwise. `_confine` still checks an accepted answer's rows.
    """
    if not str(named or '').strip():
        return ARG_NOT_PASSED
    if str(resolution.get('search_error_code') or '') == PROJECT_NOT_FOUND:
        return ARG_NOT_FOUND
    if str(resolution.get('scoped_to_project') or '').strip():
        return ARG_ACCEPTED
    return ARG_NOT_CONFIRMED


def _scope_echo(resolution: Mapping[str, Any]) -> str:
    """The received-value line for `project_id`, off a resolution."""
    return received_line(
        'project_id',
        resolution.get('project_id_received') or '',
        str(resolution.get('project_id_state') or ARG_NOT_PASSED),
    )


def _scope_target(resolution, named: str) -> str:
    """The project id the answer should be confined to.

    The service's `scoped_to_project` when present, otherwise the caller's value.
    """
    return str(resolution.get('scoped_to_project') or '').strip() or str(named).strip()


def _confine(resolution: dict[str, Any], named: str) -> dict[str, Any]:
    """Hold the answer to one project, and record when it had to be done here.

    Compares each row's raw `project_id` with the target, case-insensitively.
    Sets `scope_unverifiable_here` when a row names no project;
    `scope_ambiguous_here` when several distinct ids match the target;
    `scope_applied_here` (keeping only the matching rows) when other projects'
    rows came back beside the target's; `scope_unmatched_here` when no row is from
    the target. The last three set `project_id_state` to `not_honoured`. An answer
    whose rows are all from the one matching id is returned unchanged.
    """
    candidates = list(resolution.get('candidates') or [])
    if not candidates:
        return resolution
    target = _scope_target(resolution, named).casefold()
    blank = [
        item for item in candidates
        if not str(item.get('project_id') or '').strip()
    ]
    if blank:
        unverifiable = dict(resolution)
        unverifiable['scope_unverifiable_here'] = True
        unverifiable['scope_rows_without_project'] = len(blank)
        return unverifiable
    offered = sorted({
        str(item.get('project_id') or '').strip() for item in candidates
    })
    matched_ids = [item for item in offered if item.casefold() == target]
    narrowed = dict(resolution)
    narrowed['scope_projects_offered'] = offered
    if len(matched_ids) > 1:
        narrowed['project_id_state'] = ARG_NOT_HONOURED
        narrowed['scope_ambiguous_here'] = True
        narrowed['scope_matched_ids'] = matched_ids
        return narrowed
    if offered == matched_ids:
        return resolution
    narrowed['project_id_state'] = ARG_NOT_HONOURED
    if matched_ids:
        narrowed['candidates'] = [
            item for item in candidates
            if str(item.get('project_id') or '').strip() == matched_ids[0]
        ]
        narrowed['scope_applied_here'] = True
    else:
        narrowed['scope_unmatched_here'] = True
    return narrowed


def scope_unverifiable(resolution) -> str:
    """A returned row names no project, and a scope was asked for."""
    rows = int(resolution.get('scope_rows_without_project') or 0)
    return '\n'.join([
        _scope_echo(resolution),
        f'Строк без проекта: {rows}. Принадлежат ли они названному проекту, '
        'здесь проверить нечем.',
        'Площадь не заполнена: взять такую строку значило бы заполнить участок '
        'из неизвестного проекта и сообщить об этом как об успехе, а поставить '
        'её рядом с вашей — назвать двумя состояниями одной лицензии строки из '
        'разных проектов. Сообщите об этих строках.',
    ])


def scope_ambiguous(resolution) -> str:
    """The supplied value matches several project ids at once."""
    matched = list(resolution.get('scope_matched_ids') or [])
    return '\n'.join([
        _scope_echo(resolution),
        'Под него подходит несколько проектов сразу: ' + ', '.join(matched) + '.',
        'Они различаются только регистром, и выбрать один из них здесь значило '
        'бы выбрать проект за пользователя. Площадь не заполнена: укажите '
        '`project_id` ровно так, как он записан в нужном проекте.',
    ])


def scope_notice(named: str, numbers: Sequence[str]) -> str:
    """The notice added to a resolved area when this side narrowed the search to `project_id`."""
    listed = ', '.join(numbers)
    return '\n'.join([
        received_line('project_id', named, ARG_NOT_HONOURED),
        f'Сужено на этой стороне: {listed} — взяты строки названного проекта, '
        'строки остальных проектов отброшены.',
        'Это компенсация, а не штатный путь: сужать должен сервис поиска.',
    ])


def scope_not_applied(resolution: Mapping[str, Any]) -> str:
    """The value was sent, the search came back unscoped, and no row carries it."""
    offered = list(resolution.get('scope_projects_offered') or [])
    lines = [_scope_echo(resolution)]
    if offered:
        lines.append('Поиск вернул строки из проектов: ' + ', '.join(offered) + '.')
    lines.append(
        'Ни одна из них не помечена переданным `project_id`, и сузить их здесь '
        'нечем. Причин ровно две, и отсюда они неразличимы: либо значение '
        'записано не так, как идентификатор проекта, либо это его человеческое '
        'название — разрешить название в идентификатор умеет только сервис '
        'поиска, а он этот запрос обработал без сужения. Площадь не заполнена. '
        'Укажите `project_id` ровно так, как он записан в проекте; если он '
        'записан именно так, то сужение не выполняет сервис поиска.'
    )
    return '\n'.join(lines)


def project_not_found(resolution: Mapping[str, Any]) -> str:
    """The refusal for a `project_id` that matched no project, listing the known projects."""
    named = str(resolution.get('requested_project_id') or '').strip()
    known = [
        str(item.get('name') or item.get('project_id') or '').strip()
        for item in (resolution.get('known_projects') or [])
    ]
    known = [item for item in known if item]
    lines = [
        _scope_echo(resolution),
        f'Проект «{named}» не найден.' if named else 'Проект не найден.',
    ]
    if known:
        lines.append('Известные проекты: ' + ', '.join(known) + '.')
    lines.append(
        'Лицензии не искались: поиск в названном проекте и поиск по всем '
        'проектам — разные вопросы, и ответить на второй вместо первого '
        'значило бы выдать совпадение из чужого проекта за совпадение из '
        'этого. Укажите один из известных проектов или уберите `project_id`.'
    )
    return '\n'.join(lines)


def _project_refusal(resolution: Mapping[str, Any]) -> dict[str, Any] | None:
    """The scope refusal a resolution calls for, or None.

    In order: a row with no project (`SCOPE_UNVERIFIABLE`), several matching
    project ids (`SCOPE_AMBIGUOUS`), no row from the named project
    (`SCOPE_NOT_APPLIED`), and a `project_id` that matched no project
    (`PROJECT_NOT_FOUND`). Checked before any candidate count.
    """
    if resolution.get('scope_unverifiable_here'):
        return {
            'status': REFUSED,
            'reason': SCOPE_UNVERIFIABLE,
            'project_id': str(resolution.get('project_id_received') or ''),
            'rows_without_project': int(
                resolution.get('scope_rows_without_project') or 0
            ),
            'message': scope_unverifiable(resolution),
        }
    if resolution.get('scope_ambiguous_here'):
        return {
            'status': REFUSED,
            'reason': SCOPE_AMBIGUOUS,
            'project_id': str(resolution.get('project_id_received') or ''),
            'matched_project_ids': list(resolution.get('scope_matched_ids') or []),
            'message': scope_ambiguous(resolution),
        }
    if resolution.get('scope_unmatched_here'):
        return {
            'status': REFUSED,
            'reason': SCOPE_NOT_APPLIED,
            'project_id': str(resolution.get('project_id_received') or ''),
            'projects_offered': list(resolution.get('scope_projects_offered') or []),
            'message': scope_not_applied(resolution),
        }
    if str(resolution.get('search_error_code') or '') != PROJECT_NOT_FOUND:
        return None
    return {
        'status': REFUSED,
        'reason': PROJECT_NOT_FOUND,
        'project_id': str(resolution.get('requested_project_id') or ''),
        'known_projects': list(resolution.get('known_projects') or []),
        'message': project_not_found(resolution),
    }


async def _search(
    gis_call: GisCall, query: str, project_id: str = ''
) -> dict[str, Any]:
    """The search answer's `scope_resolution`, annotated.

    Sends `resolve_scope` with `query` and, when given, `project_id`. Raises
    `_UnreadableSearch` when the answer carries no `scope_resolution` mapping.
    Moves suggested project names (`candidates_are: known_projects`) from
    `candidates` to `known_projects`, copies the answer's `error` into
    `search_error_code` and `search_error_message`, records `project_id_received`
    and `project_id_state`, and applies `_confine` when that state is `accepted`
    or `not_confirmed`.
    """
    payload: dict[str, Any] = {'action': 'resolve_scope', 'query': query}
    scope = str(project_id or '').strip()
    if scope:
        payload['project_id'] = scope
    answer = await gis_call(payload)
    resolution = (answer or {}).get('scope_resolution') if isinstance(answer, Mapping) else None
    if not isinstance(resolution, Mapping):
        raise _UnreadableSearch(query)
    found = dict(resolution)
    if str(found.get('candidates_are') or '') == 'known_projects':
        found['known_projects'] = list(found.get('candidates') or [])
        found['candidates'] = []
    error = (answer or {}).get('error') if isinstance(answer, Mapping) else None
    if isinstance(error, Mapping):
        found['search_error_code'] = str(error.get('code') or '')
        found['search_error_message'] = str(error.get('message') or '')
    found['project_id_received'] = scope
    found['project_id_state'] = scope_state(scope, found)
    if found['project_id_state'] in (ARG_ACCEPTED, ARG_NOT_CONFIRMED):
        found = _confine(found, scope)
    return found


class _UnreadableSearch(Exception):
    """Raised when a search answer carries no `scope_resolution`."""

    def __init__(self, query: str) -> None:
        super().__init__(query)
        self.query = query


async def resolve_area_members(
    *,
    gis_call: GisCall,
    object_name: str = '',
    licence_ids: Sequence[str] = (),
    licence_layers: Mapping[str, str] | None = None,
    project_id: str = '',
) -> dict[str, Any]:
    """Which licences this area is about, or the question, or the refusal.

        licence_ids given         use them, no search, no question
        none, one licence found   use it
        none, several found       ask
        none, zero found          refuse, naming what was searched

    `project_id` scopes every search. `licence_layers` selects, per licence number,
    the layer a licence is taken from within one project; it is applied before
    the candidates are counted, and a named layer that holds no candidate
    refuses. Layers are never merged. A supplied number that is not found or is
    ambiguous refuses the whole request.
    """
    supplied = [str(item or '').strip() for item in licence_ids]
    supplied = [item for item in supplied if item]

    if supplied:
        members: list[dict[str, Any]] = []
        narrowed_here: list[str] = []
        for number in supplied:
            try:
                resolution = await _search(gis_call, number, project_id)
            except _UnreadableSearch:
                return {
                    'status': REFUSED,
                    'reason': SEARCH_UNREADABLE,
                    'licence_id': number,
                    'message': (
                        f'Поиск по {number} вернул ответ, который не является '
                        'ответом поиска. «Не найдена» о ней не утверждается.'
                    ),
                }
            refused = _project_refusal(resolution)
            if refused is not None:
                return refused
            candidates = list(resolution.get('candidates') or [])
            wanted_layer = str((licence_layers or {}).get(number) or '').strip()
            if wanted_layer:
                narrowed = [
                    item for item in candidates
                    if str(item.get('licence_layer_id') or '') == wanted_layer
                ]
                if not narrowed:
                    return {
                        'status': REFUSED,
                        'reason': LAYER_NOT_AMONG_CANDIDATES,
                        'licence_id': number,
                        'licence_layer_id': wanted_layer,
                        'layers': _candidate_layers(candidates),
                        'message': layer_not_found(number, wanted_layer, candidates),
                    }
                candidates = narrowed
            if len(candidates) == 1:
                members.append(_member(candidates[0]))
                if resolution.get('scope_applied_here'):
                    narrowed_here.append(number)
                continue
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
                'layers': _candidate_layers(candidates),
                'message': ambiguous_licence(number, candidates, _scope_echo(resolution)),
            }
        return {
            'status': RESOLVED,
            'members': members,
            'resolved_from': 'supplied',
            'cost_notice': cost_notice(len(members)),
            **(
                {'scope_notice': scope_notice(project_id, narrowed_here)}
                if narrowed_here
                else {}
            ),
        }

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

    try:
        resolution = await _search(gis_call, query, project_id)
    except _UnreadableSearch:
        return {
            'status': REFUSED,
            'reason': SEARCH_UNREADABLE,
            'message': (
                f'Поиск по «{query}» вернул ответ, который не является ответом '
                'поиска. «Не найдена» о ней не утверждается.'
            ),
        }
    refused = _project_refusal(resolution)
    if refused is not None:
        return refused
    candidates = list(resolution.get('candidates') or [])

    if len(candidates) == 1:
        return {
            'status': RESOLVED,
            'members': [_member(dict(candidates[0]) | {
                'centroid_unavailable': NAME_SEARCH_HAS_NO_POLYGON,
            })],
            'resolved_from': 'search',
            'cost_notice': cost_notice(1),
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
    }


def _not_found_message(
    asked: Sequence[str], missing: str, resolution: Mapping[str, Any]
) -> str:
    """The not-found refusal: which numbers were found, which was not, and what was searched."""
    searched = resolution.get('searched_projects')
    unreadable = list(resolution.get('unreadable_projects') or [])
    lines = [
        f'- {number} — ' + ('не найдена' if number == missing else 'найдена')
        for number in asked
    ]
    lines.insert(0, _scope_echo(resolution))
    scoped = str(resolution.get('scoped_to_project') or '').strip()
    if scoped:
        tail = (
            f'Искали в проекте: {scoped}. '
            'Уберите `project_id`, чтобы искать во всех.'
        )
    else:
        tail = f'Искали в проектах: {searched}.' if searched is not None else ''
    if unreadable:
        tail += (
            f' Не удалось открыть: {len(unreadable)} — '
            '«не найдена» о них не утверждается.'
        )
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

AREA_POLICY_VERSION = 'geotizer_area_aggregation.v1'

SUPPLIED = 'supplied'
RESOLVED_BY_SYSTEM = 'resolved'

NO_CENTROID = 'area_centroid_unavailable'

CRS_NOT_RECOGNISED = 'calculation_crs_not_recognised'

NAME_SEARCH_HAS_NO_POLYGON = 'name_search_has_no_polygon'

_GEOGRAPHIC_CRS = frozenset({'EPSG:4326', 'EPSG:4284', 'EPSG:7683', 'EPSG:4979'})


def utm_zone_for(longitude: float, latitude: float) -> str:
    """The UTM zone containing a point, as an EPSG code.

    The same arithmetic as `gis_service`'s `measurement_crs.utm_zone_for`.
    """
    zone = min(60, max(1, int((float(longitude) + 180) // 6) + 1))
    return f'EPSG:{(32600 if float(latitude) >= 0 else 32700) + zone}'


def _centroid_of(member: Mapping[str, Any]) -> tuple[float, float] | None:
    """A member's centroid as two finite floats, or None."""
    longitude, latitude = member.get('centroid_lon'), member.get('centroid_lat')
    if longitude is None or latitude is None:
        return None
    try:
        longitude, latitude = float(longitude), float(latitude)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(longitude) and math.isfinite(latitude)):
        return None
    return longitude, latitude


def resolve_calculation_crs(members: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """One projected CRS for the whole area: the UTM zone of the members' mean centroid.

    Longitudes are averaged on the circle, latitudes arithmetically. One zone is
    chosen for the whole area, and every zone the members fall in is recorded in
    `zones_spanned`. Returns None when no member has a centroid.
    """
    member_list = list(members)
    points = [
        point for point in (_centroid_of(member) for member in member_list)
        if point is not None
    ]
    if not points:
        return None
    radians = [math.radians(item[0]) for item in points]
    longitude = math.degrees(
        math.atan2(
            sum(math.sin(value) for value in radians) / len(radians),
            sum(math.cos(value) for value in radians) / len(radians),
        )
    )
    latitude = sum(item[1] for item in points) / len(points)
    zones = sorted({utm_zone_for(lon, lat) for lon, lat in points})
    return {
        'crs': utm_zone_for(longitude, latitude),
        'chosen_by': 'centroid_zone',
        'centroid': [round(longitude, 6), round(latitude, 6)],
        'members_with_centroid': len(points),
        'members_total': len(member_list),
        'zones_spanned': zones,
        'spans_several_zones': len(zones) > 1,
    }


def epsg_code(crs: str) -> str | None:
    """`EPSG:NNNN` for `NNNN`, `epsg:NNNN` or `EPSG: NNNN`, or None when this
    tool cannot tell which CRS is meant.
    """
    compact = ''.join(str(crs or '').split()).upper()
    if not compact:
        return None
    if compact.isdigit():
        return f'EPSG:{compact}'
    if compact.startswith('EPSG:') and compact[5:].isdigit():
        return compact
    return None


def is_projected(crs: str) -> bool:
    """Whether `crs` is an EPSG code this tool recognises and that is not geographic.

    False for a geographic CRS and for an unrecognised spelling alike;
    `epsg_code` separates the two.
    """
    code = epsg_code(crs)
    return code is not None and code not in _GEOGRAPHIC_CRS

_SCOPE_FIELDS = ('entity_id', 'entity_type', 'name')


def resolve_contract(
    *,
    policy_version: str,
    calculation_crs: str,
    members: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The two contract values, each with how it was obtained, or a refusal.

        supplied     use it, never override, record 'supplied'
        resolved     use it, name it, record 'resolved'
        neither      refuse, naming which one failed and why

    A supplied `policy_version` other than `AREA_POLICY_VERSION`, a
    `calculation_crs` that is not an EPSG code, and a geographic `calculation_crs`
    are refused, never replaced. An omitted `calculation_crs` is resolved by
    `resolve_calculation_crs`, and refused when no member has a centroid.
    """
    policy = str(policy_version or '').strip()
    crs = str(calculation_crs or '').strip()

    if policy and policy != AREA_POLICY_VERSION:
        return {
            'status': REFUSED,
            'reason': POLICY_VERSION_UNKNOWN,
            'failed': 'policy_version',
            'supplied': policy,
            'known': AREA_POLICY_VERSION,
            'message': (
                f'`policy_version` задан как `{policy}`, а политика сведения '
                f'одна и её версия — `{AREA_POLICY_VERSION}`. Площадь не '
                'заполнена: свод, который называет политику, по которой он не '
                'сворачивался, нельзя воспроизвести — ровно то, ради чего это '
                'поле и требуется.\n'
                'Не указывайте `policy_version` — текущая подставится сама и '
                'будет названа в ответе.'
            ),
        }

    code = epsg_code(crs) if crs else None
    if crs and code is None:
        return {
            'status': REFUSED,
            'reason': CRS_NOT_RECOGNISED,
            'failed': 'calculation_crs',
            'message': (
                f'`calculation_crs` задан как {crs}, и это не код EPSG — '
                'распознаётся только «EPSG:32656» или «32656». Проекционная '
                'она или географическая, здесь установить нельзя, а площадь в '
                'географической измеряется в квадратных градусах. Укажите код '
                'EPSG или не указывайте ничего — тогда система координат будет '
                'определена по центроиду площади.'
            ),
        }
    if crs and not is_projected(crs):
        return {
            'status': REFUSED,
            'reason': MISSING_CONTRACT,
            'failed': 'calculation_crs',
            'message': (
                f'`calculation_crs` задан как {crs}, а это географическая '
                'система координат: площадь в ней измеряется в квадратных '
                'градусах, что площадью не является. Укажите проекционную '
                'систему или не указывайте её вовсе — тогда она будет '
                'определена по центроиду площади.'
            ),
        }

    crs_record: dict[str, Any] = {'value': crs, 'source': SUPPLIED} if crs else {}
    if not crs:
        member_list = list(members)
        resolved = resolve_calculation_crs(member_list)
        if resolved is None:
            return {
                'status': REFUSED,
                'reason': NO_CENTROID,
                'failed': 'calculation_crs',
                'members_total': len(member_list),
                'causes': _centroid_causes(member_list),
                'message': (
                    'Не удалось определить систему координат для измерения: ни '
                    'для одного из участников площади не определено положение '
                    f'({_centroid_causes_ru(member_list)}), поэтому у площади '
                    'нет центроида, а по нему выбирается зона UTM. Площадь не '
                    'заполнена. Укажите `calculation_crs` явно — проекционную '
                    'систему, в которой мерить пересечения.'
                ),
            }
        crs_record = {'value': resolved['crs'], 'source': RESOLVED_BY_SYSTEM, **resolved}

    return {
        'status': RESOLVED,
        'policy_version': {
            'value': policy or AREA_POLICY_VERSION,
            'source': SUPPLIED if policy else RESOLVED_BY_SYSTEM,
        },
        'calculation_crs': crs_record,
    }


_CENTROID_CAUSE_RU = {
    'unreadable': 'строка лицензии не читается',
    'outside_the_world': 'координаты вне мира — проекция не выполнена',
    NAME_SEARCH_HAS_NO_POLYGON: (
        'поиск по названию возвращает проект, а не контур лицензии — '
        'укажите номера лицензий или `calculation_crs`'
    ),
}
_CENTROID_CAUSE_UNKNOWN_RU = 'причина не сообщена'


def _centroid_causes(members: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """How many members lack a centroid, per `centroid_unavailable` reason."""
    counts: dict[str, int] = {}
    for member in members:
        if _centroid_of(member) is not None:
            continue
        cause = str(member.get('centroid_unavailable') or '').strip() or 'unknown'
        counts[cause] = counts.get(cause, 0) + 1
    return counts


def _centroid_causes_ru(members: Sequence[Mapping[str, Any]]) -> str:
    """The same counts as a Russian clause, keeping any exception type after the reason."""
    parts = []
    for cause, count in sorted(_centroid_causes(members).items()):
        head, _, detail = cause.partition(':')
        text = _CENTROID_CAUSE_RU.get(head, _CENTROID_CAUSE_UNKNOWN_RU)
        if detail:
            text = f'{text} ({detail})'
        parts.append(f'{text}: {count}')
    return '; '.join(parts) or 'причина не сообщена'


def contract_line(contract: Mapping[str, Any]) -> str:
    """The sentence stating which policy and CRS the area was folded and measured under, and whether each was supplied
    or resolved.
    """
    policy = contract['policy_version']
    crs = contract['calculation_crs']
    policy_tail = '' if policy['source'] == SUPPLIED else ' (по умолчанию для этой сборки)'
    if crs['source'] == SUPPLIED:
        crs_tail = ' (указана в запросе)'
    else:
        notes = ['зона по центроиду площади']
        with_centroid = crs.get('members_with_centroid')
        total = crs.get('members_total')
        if with_centroid is not None and total is not None and with_centroid != total:
            notes.append(f'центроид по {with_centroid} из {total} участников')
        if crs.get('spans_several_zones'):
            notes.append(
                f'участники попадают в {len(crs["zones_spanned"])} зоны: '
                f'{", ".join(crs["zones_spanned"])}'
            )
        crs_tail = f' ({"; ".join(notes)})'
    return (
        f'Свёрнуто по политике `{policy["value"]}`{policy_tail}, '
        f'измерено в {crs["value"]}{crs_tail}.'
    )


async def fill_area(
    *,
    gis_call: GisCall,
    scope_call: GisCall,
    fold_call: GisCall,
    member_fill: Callable[..., Awaitable[dict[str, Any]]],
    object_name: str = '',
    licence_ids: Sequence[str] = (),
    licence_layers: Mapping[str, str] | None = None,
    project_id: str = '',
    area_scope_id: str = '',
    policy_version: str = '',
    calculation_crs: str = '',
    dossier_run_id: str = '',
    area_deadline_seconds: float | None = None,
    area_deadline_note: str = '',
    area_concurrent_members: int = DEFAULT_CONCURRENT_MEMBERS,
    event_emitter: Any = None,
    status: StatusSettings | None = None,
    area_concurrency_note: str = '',
    member_arguments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve, fill, fold and summarise, or ask, or refuse.

    `gis_call` is the `geotizer_fill` operation (which carries `resolve_scope`),
    `scope_call` is `geotizer_area_scope`, and `fold_call` is `geotizer_area_fold`;
    none defaults to another. Returns a dict carrying `status` and, for a resolved
    area, `result`. Writes no Markdown.
    """
    resolution = await resolve_area_members(
        gis_call=gis_call,
        object_name=object_name,
        licence_ids=licence_ids,
        licence_layers=licence_layers,
        project_id=project_id,
    )
    if resolution['status'] != RESOLVED:
        return resolution

    members = resolution['members']
    contract = resolve_contract(
        policy_version=policy_version,
        calculation_crs=calculation_crs,
        members=members,
    )
    if contract['status'] != RESOLVED:
        return contract
    policy_version = contract['policy_version']['value']
    calculation_crs = contract['calculation_crs']['value']
    area_id = str(area_scope_id or '').strip() or f'area:{object_name or ",".join(licence_ids)}'
    owner_project = str(project_id or '').strip() or str(
        members[0].get('project_id') or ''
    )

    manifest = await scope_call(
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

    fill_fields = {
        member['entity_id']: {
            'object_name': member['object_name'],
            'project_id': member.get('project_id'),
            'licence_id': member.get('licence_id'),
            'licence_layer_id': member.get('licence_layer_id'),
        }
        for member in members
    }
    merged = dict(manifest)
    merged['area_id'] = merged.get('area_id') or area_id
    merged['contract_resolution'] = {
        'policy_version': contract['policy_version'],
        'calculation_crs': contract['calculation_crs'],
    }
    merged['members'] = [
        dict(item) | fill_fields.get(str(item.get('entity_id') or ''), {})
        for item in (manifest.get('entities') or [])
    ]
    if not merged['members']:
        return {
            'status': REFUSED,
            'reason': MANIFEST_WITHOUT_MEMBERS,
            'members_total': len(members),
            'message': (
                f'Манифест площади вернулся без участников, хотя их {len(members)}. '
                'Область не заполнена: заполнять по пустому манифесту значило бы '
                'сообщить о площади из нуля объектов как об успешной.'
            ),
        }

    outcome = await run_geotizer_area_workflow(
        manifest=merged,
        member_fill=member_fill,
        member_arguments=member_arguments,
        area_deadline_seconds=area_deadline_seconds,
        concurrent_members=area_concurrent_members,
        fold_call=fold_call,
        policy_version=policy_version,
        dossier_run_id=str(dossier_run_id or '').strip() or area_id,
        on_progress=area_progress_reporter(event_emitter, status),
        project_id=owner_project,
        calculation_crs=calculation_crs,
        area_display_name=str(object_name or '').strip() or area_id,
    )
    return {
        'status': RESOLVED,
        'resolved_from': resolution['resolved_from'],
        'cost_notice': resolution.get('cost_notice'),
        **(
            {'scope_notice': resolution['scope_notice']}
            if resolution.get('scope_notice')
            else {}
        ),
        **(
            {'area_deadline_note': area_deadline_note.strip()}
            if area_deadline_note.strip()
            else {}
        ),
        **(
            {'area_concurrency_note': area_concurrency_note.strip()}
            if area_concurrency_note.strip()
            else {}
        ),
        'contract': contract,
        'result': outcome,
    }


def _member_line(item: Mapping[str, Any]) -> str:
    """One member as the answer lists it: what happened, and its `run_id` when it has one."""
    name = str(item.get('object_name') or item.get('entity_id') or '')
    state = str(item.get('state') or '')
    if state == 'filled':
        completeness = item.get('completeness') or {}
        filled = completeness.get('filled')
        of = completeness.get('of')
        figure = f' — {filled} из {of}' if filled is not None and of else ''
        return f'- {name} — заполнен{figure} (`{item.get("run_id")}`)'
    if state == 'failed':
        run_id = item.get('run_id')
        handle = f' (`{run_id}`)' if run_id else ''
        return f'- {name} — не заполнен: {item.get("error")}{handle}'
    return f'- {name} — не начинался: {item.get("reason")}'


def area_progress_line(
    counts: Mapping[str, int], status: StatusSettings | None = None
) -> str:
    """The area's one status line, from the counts the loop keeps.

    The failed and not-started terms appear only when non-zero; waiting is the
    member count less every other state.
    """
    say = status or StatusSettings()
    total = int(counts.get('members') or 0)
    running = int(counts.get('running') or 0)
    filled = int(counts.get('filled') or 0)
    failed = int(counts.get('failed') or 0)
    not_attempted = int(counts.get('not_attempted') or 0)
    waiting = max(0, total - running - filled - failed - not_attempted)
    parts = [
        say.say(
            'area_progress',
            total=total,
            members=say.members_word(total),
            running=running,
            filled=filled,
            waiting=waiting,
        )
    ]
    if failed:
        parts.append(say.say('area_progress_failed', failed=failed))
    if not_attempted:
        parts.append(say.say('area_progress_not_attempted', missed=not_attempted))
    return ' · '.join(parts)


def area_progress_reporter(
    event_emitter: Any, status: StatusSettings | None = None
) -> Any:
    """`on_progress` for the area loop, or `None` when there is no emitter.

    Every line is emitted with `done=False`.
    """
    if event_emitter is None:
        return None

    async def report(counts: Mapping[str, int]) -> None:
        await _emit_status(
            event_emitter, area_progress_line(counts, status), done=False
        )

    return report


AREA_ARTEFACT_LABELS = (
    ('geotizer.xlsx', 'Карточка площади (Excel)'),
    ('geotizer.docx', 'Карточка площади (CPR, Word)'),
    ('summary.md', 'Как свёрнуто: решения свёртки (Markdown)'),
    ('source_report.md', 'Где источники: отчёты участников (Markdown)'),
    ('source_report.pdf', 'Где источники: отчёты участников (PDF)'),
    ('state.json', 'Состояние площади'),
    ('run_log.json', 'Журнал свёртки'),
)

SOURCE_REPORT_NOT_RENDERED = 'source_report'

AREA_ARTEFACT_LIMITS = (
    'Отчёт об источниках по площади не собирается: свёртка несёт, какой '
    'участник дал значение, но не его локатор. Отчёты по каждому участнику '
    'есть — они открываются по `run_id` участника из «Состояния площади».',
)

ARTEFACT_PATH_PREFIX = '/geotizer/files/'
ARTEFACT_PROXY_PREFIX = '/api/v1'


def area_artifact_lines(artifacts: Mapping[str, Any] | None) -> list[str]:
    """The area's download links, or one line saying why there are none.

    A path is linked only when it starts with `ARTEFACT_PATH_PREFIX` and ends in
    its artefact's name, and is proxied under `ARTEFACT_PROXY_PREFIX`.
    """
    if not isinstance(artifacts, Mapping):
        return [
            'Файлы площади: сервис их не вернул — вероятно, версия GIS-сервиса '
            'старше этой возможности. Карточки участников доступны по их '
            'собственным идентификаторам выше.'
        ]
    if not artifacts.get('written') and not artifacts.get('partial'):
        missing = ', '.join(str(item) for item in (artifacts.get('missing_inputs') or []))
        detail = f' Не передано: {missing}.' if missing else ''
        return [
            f'Файлы площади не сохранены: у свёртки не было того, из чего '
            f'строится её идентификатор.{detail}'
        ]

    lines = ['**Файлы площади**', '']
    if artifacts.get('partial'):
        survived = ', '.join(
            str(name) for name in (artifacts.get('written_before_failure') or [])
        )
        error = str(artifacts.get('error') or '').strip()
        lines.extend([
            'Часть файлов площади не записана. Свёртка при этом посчиталась: '
            + (f'уцелели {survived}. ' if survived else 'ни один файл не уцелел. ')
            + (f'Отказ записи: {error}' if error else 'Класс отказа не назван.'),
            '',
        ])
    files = artifacts.get('files') or {}
    for name, label in AREA_ARTEFACT_LABELS:
        record = files.get(name)
        if not isinstance(record, Mapping):
            continue
        path = str(record.get('download_path') or '')
        if not path.startswith(ARTEFACT_PATH_PREFIX) or not path.endswith(f'/{name}'):
            continue
        lines.append(f'- [{label}]({ARTEFACT_PROXY_PREFIX}{path})')
    if len(lines) == 2:
        return [
            'Файлы площади: сервис сообщил, что записал их, но ни одного '
            'пригодного пути в ответе нет.'
        ]
    not_rendered = artifacts.get('not_rendered')
    if isinstance(not_rendered, Mapping) and not_rendered:
        lines.extend(
            [
                '',
                'Чего у площади нет: '
                + ', '.join(sorted(str(name) for name in not_rendered))
                + '. Причина — в `run_log.json`, ключ `not_rendered`.',
            ]
        )
    if _source_report_is_still_open(artifacts):
        lines.extend(['', *AREA_ARTEFACT_LIMITS])
    return lines


def _source_report_is_still_open(artifacts: Mapping[str, Any]) -> bool:
    """Whether the service reports that it cannot build an area source report.

    True when `not_rendered` is absent or not a mapping, or names
    `SOURCE_REPORT_NOT_RENDERED`; an empty mapping means the gap is closed.
    """
    not_rendered = artifacts.get('not_rendered')
    if not isinstance(not_rendered, Mapping):
        return True
    return any(
        SOURCE_REPORT_NOT_RENDERED in str(name) for name in not_rendered
    )


def render_area_answer(payload: Mapping[str, Any]) -> str:
    """The Markdown a user reads, for every outcome of `fill_area`."""
    status = payload.get('status')
    if status == ASK:
        return str(payload.get('question') or '')
    if status == REFUSED:
        return str(payload.get('message') or '')

    result = payload.get('result') or {}
    members = list(result.get('members') or [])
    notice = str(payload.get('cost_notice') or '').strip()
    deadline_note = str(payload.get('area_deadline_note') or '').strip()
    concurrency_note = str(payload.get('area_concurrency_note') or '').strip()
    scope_line = str(payload.get('scope_notice') or '').strip()
    counts = result.get('counts') or {}
    aggregation = result.get('aggregation') or {}

    lines = [
        *([notice, ''] if notice else []),
        *([deadline_note, ''] if deadline_note else []),
        *([concurrency_note, ''] if concurrency_note else []),
        *([scope_line, ''] if scope_line else []),
        f'Площадь `{result.get("area_id")}`: '
        f'{counts.get("members", 0)} {_members_word(int(counts.get("members", 0)))}, '
        f'заполнено {counts.get("filled", 0)}, '
        f'не заполнено {counts.get("failed", 0)}, '
        f'не начиналось {counts.get("not_attempted", 0)}.',
        '',
        *[_member_line(item) for item in members],
        '',
    ]

    contract = payload.get('contract')
    if isinstance(contract, Mapping) and contract.get('status') == RESOLVED:
        lines.extend([contract_line(contract), ''])

    if aggregation.get('state') == PERFORMED:
        markdown = str(result.get('summary_markdown') or '').strip()
        lines.append(markdown or 'Свод построен, но пуст.')
        lines.extend(['', *area_artifact_lines(result.get('artifacts'))])
    else:
        reason = aggregation.get('reason')
        if reason == 'nothing_filled':
            total = int(aggregation.get('members_total') or 0)
            lines.append(
                f'Свод не построен: ни один участник не заполнен '
                f'(0 из {total}).\nПричины по участникам — выше.'
            )
        else:
            detail = aggregation.get('error') or aggregation.get('missing')
            lines.append(
                f'Свод не построен: {reason}' + (f' ({detail})' if detail else '')
            )

    return '\n'.join(lines)
