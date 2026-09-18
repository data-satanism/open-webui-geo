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

import math

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from .area_workflow import (
    DEFAULT_CONCURRENT_MEMBERS,
    PERFORMED,
    run_geotizer_area_workflow,
)

#: Hours one member costs, measured rather than estimated. A-169: two runs of
#: one object at 2 h 32 m and 2 h 48 m, from `started_at` to `finalized_at`.
#: A-164's «four to seven minutes» was an estimate and was thirty times out, so
#: this figure is the one the refusal and the question are both written from.
MEMBER_HOURS = 2.6

#: No default bound on the area's own work, and the reasoning that put one
#: here was wrong.
#:
#: It read: a tool that accepts twenty-one members and dies at hour four has
#: lost a day and produced nothing. The second half is false. A member that
#: finishes is written -- each is an ordinary single-object run with its own
#: `run_id` and its own artefacts -- so a call that outlives its request has
#: produced every member that completed, and the only thing lost is the fold.
#: Refusing at three converted a partial result into no result at all, which
#: is worse than the timeout it was avoiding.
#:
#: How long to wait is the caller's decision. The valve still sets a bound when
#: a contour wants one, and `run_geotizer_area_workflow` records every member
#: past it as `not_attempted` with the reason rather than dropping it.
DEFAULT_AREA_DEADLINE_SECONDS: float | None = None

RESOLVED = 'resolved'
ASK = 'ask'
REFUSED = 'refused'

#: Why a resolution refused, in words a caller acts on.
NOTHING_TO_RESOLVE = 'nothing_to_resolve'
LICENCE_NOT_FOUND = 'licence_not_found'
LICENCE_AMBIGUOUS = 'licence_ambiguous'
LAYER_NOT_AMONG_CANDIDATES = 'licence_layer_not_among_candidates'
#: The search answered with something that is not a search answer. Not
#: «not found»: `resolve_scope` always carries `scope_resolution`, so its
#: absence means the reply was never one -- an error body surfaced as data,
#: most likely. Saying «не найдена» about a licence nobody looked up is a
#: specific false claim, which is worse than admitting the reply was unread.
SEARCH_UNREADABLE = 'search_unreadable'
#: The manifest came back without the members that went into it.
MANIFEST_WITHOUT_MEMBERS = 'manifest_without_members'
#: The `project_id` the caller supplied matches no project in the store. Its
#: own reason, and gis_service's own code for it: «лицензия не найдена» about a
#: licence that was never searched for is a false sentence, and it points the
#: caller at the one argument they got right.
PROJECT_NOT_FOUND = 'scope_project_not_found'
#: `project_id` was sent, the answer came back unscoped, and no returned row
#: carries the value. Its own reason: «не найдена» would be false of a licence
#: the search did find, and the ambiguity refusal would ask for the argument
#: that was supplied.
SCOPE_NOT_APPLIED = 'scope_not_applied'
#: A returned row names no project, and a scope was asked for. Nothing here can
#: say whether it belongs to the named project, and both silent readings are
#: wrong -- see `_confine`.
SCOPE_UNVERIFIABLE = 'scope_unverifiable'
#: The supplied value matches several distinct project ids at once.
SCOPE_AMBIGUOUS = 'scope_ambiguous'
#: A `policy_version` was supplied and is not the one that exists. Its own
#: reason: the field is required by the tool and its value is not discoverable
#: from it, so a model fills it with a guess — `2024` was folded and echoed as
#: «Свёрнуто по политике `2024`», which is the reproducibility claim the
#: requirement exists to protect, inverted.
POLICY_VERSION_UNKNOWN = 'policy_version_unknown'

GisCall = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


AREA_CONCURRENCY_VALVE = 'GEOMAS_AREA_CONCURRENT_MEMBERS'


def concurrent_members(raw: Any) -> tuple[int, str | None]:
    """How many members fill at once, from the valve's raw string, plus a note.

    The same pair, for the same reason, as the deadline valve below: a value
    that was set and could not be used must not read like a valve nobody set.
    An operator who wrote `GEOMAS_AREA_CONCURRENT_MEMBERS=seven` otherwise
    believes the area runs seven at a time while it runs the default.

    This bounds LOAD and nothing else. It is not a member cap and must not be
    read as one: a cap refuses members, this schedules them. Seven licences
    means seven members at any value of this valve, and the only difference is
    how long they take. `AREA_MAX_MEMBERS` was the other kind and is gone.

    Zero and negatives are refused with a note. Zero here would mean an area
    that schedules nothing and folds an empty result, which is the answer that
    looks like success and is not.
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

    Returns `(None, None)` when nothing is configured, `(seconds, None)` when a
    usable number is, and `(None, note)` when a value was set and could not be
    used. The note is the whole point of the pair: an unset valve and a
    mistyped one both end up unbounded, and without a note those two are the
    same observation — an operator who set `GEOMAS_AREA_DEADLINE_SECONDS=3600s`
    believes an area is bounded at an hour while nothing bounds it at all. The
    sibling per-member valve, `resolve_fill_deadline`, has returned a note for
    exactly this reason since it was written.

    The valve is an environment string and `run_geotizer_area_workflow` does
    `float(...)` on it once per member, so `GEOMAS_AREA_DEADLINE_SECONDS=abc`
    raised a `ValueError` inside the member loop — after members had been
    filled, which is the most expensive moment to find a typo in a valve.
    `member_ceiling` held this guard and was the only thing that touched the
    valve before the workflow did; it is gone with the ceiling, so the guard
    lives here, in the core, where it can be exercised without standing up the
    adapter.

    Zero and negatives are refused with a note too. On the object path zero
    means «no deadline»; here it would put every member past the deadline
    before the first one starts, abandoning the whole area without filling
    anything.
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


def cost_notice(count: int) -> str:
    """What the run will cost and what happens when the request outlives it.

    Not a refusal. The ceiling this replaces turned seven licences into no
    result at all; a member that finishes is written whether or not the browser
    is still listening, so the honest thing is to say the cost and start.

    Says the three facts in the order a reader needs them: how long, that their
    request will end first, and that the work does not end with it.
    """
    return (
        f'{cost_phrase(count)}. Запрос браузера прервётся раньше; '
        f'участники продолжат заполняться, и их карточки будут готовы.\n'
        f'Свод по площади соберётся, когда закончится последний.'
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


#: What a licence layer is called, when the layer name alone does not say.
#: Only the states this registry actually holds; an unrecognised layer is
#: printed with no gloss rather than guessed at, because a wrong gloss on a
#: licence state is worse than none.
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


#: A candidate whose layer the search did not name. Printed rather than
#: dropped: a row missing from the refusal still counts towards the ambiguity,
#: so leaving it out describes a smaller problem than the one being refused --
#: and `licence_layers` can never select it, which the refusal has to say.
_LAYER_UNNAMED_RU = '(слой не назван)'

#: And a layer this tool has no word for. Distinct from «no state»: the three
#: `GIS_Data_RF` layers above are states of a licence and are named as such; a
#: project's own licence layer is classified by a token in its name and carries
#: no state anywhere upstream to read. Printing a blank made those two look the
#: same, and made the second look like a defect in the project's manifest.
_LAYER_STATE_UNKNOWN_RU = 'состояние не определено'


def _layer_lines(candidates: Sequence[Mapping[str, Any]]) -> str:
    """The candidates as a reader can act on them: one ROW per line, glossed.

    Rows and not layers. Two rows for one number in the same layer, from two
    projects, is a shape `find_licence_across_projects` produces by design --
    it searches every project the store holds -- and listing layers instead
    printed «найдена в 1 слоях» above an ambiguity refusal, then told the
    reader to pick a layer that would narrow it to the same two rows.
    """
    lines = []
    for item in candidates:
        name = str(item.get('licence_layer_id') or '').strip()
        project = str(item.get('project_id') or '').strip()
        line = f'  {name or _LAYER_UNNAMED_RU}'
        # A gloss, or the fact that there is none. The registry's three layers
        # are in the table and a project's own licence layer is not, so
        # `Sint_licences_2025exp_clp` printed with a blank where
        # `Licenses_2024_2025` printed «действующие» — and a blank reads as «no
        # state recorded» when what it means is «this tool has no word for this
        # layer». Nothing upstream states a role to read instead: a layer is
        # classified as a licence layer by token match on its name, and the
        # manifest carries no state for it.
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
    """The ambiguity refusal, naming what the caller can actually do about it.

    Three shapes, and they have different next steps because the caller has
    different powers over them.

    **Several projects.** `GIS_Data_RF` is the national registry and holds most
    licences in the country; a project a geologist uploaded holds the few they
    work on. `project_id` scopes the search, the Workspace tool declares it,
    and naming it is a step the caller can take.

    **One project, several layers.** These are states of one licence -- current,
    annulled, junior-programme -- with possibly different geometries and dates,
    and folding them would choose a state for the user. The refusal is right.
    What it cannot do is name `licence_layers`: that parameter exists in this
    repository and not on the deployed Workspace tool, so a model following the
    instruction sends a value Open WebUI drops. This is the third refusal to
    name an argument the caller cannot pass -- `licence_id` before the adapter
    was regenerated, `policy_version` before it was resolved -- and a refusal
    naming an unreachable argument is a dead end wearing the shape of an
    instruction.

    **Several rows the layer does not separate.** Same layer, same project, or
    no layer name: no argument the caller holds narrows these, and saying so is
    the only true thing available.
    """
    layers = _candidate_layers(candidates)
    projects = _candidate_projects(candidates)
    # On every branch, not only the one that asks for `project_id`. A caller
    # whose scope WAS applied and who still gets an ambiguity is looking at a
    # different problem -- two states of one licence inside their own project --
    # and «принят» is what tells them so. Without it they re-send the argument
    # that already worked, which is the loop this line exists to break.
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
        # First, because it is the one the caller can answer. A licence in the
        # registry and in their own project is not ambiguous once they say
        # which project they meant.
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
    """The qualifier named a layer this licence is not in.

    Separate from the ambiguity refusal because the caller's next step is
    different: there, choose one of these; here, you chose one and it is not
    among them, so the choice was about a different licence or a layer that
    does not hold this number.
    """
    return (
        f'Для {number} указан слой {wanted}, но лицензия в нём не найдена. '
        f'Она есть в {len(_candidate_layers(candidates))} слоях:\n'
        f'{_layer_lines(candidates)}\n'
        'Укажите один из них.'
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
        # Where this polygon is, in degrees, for the area's centroid zone.
        # Absent when the row would not read, which is a refusal and not a
        # default -- see `resolve_contract`'s third row.
        'centroid_lon': candidate.get('centroid_lon'),
        'centroid_lat': candidate.get('centroid_lat'),
        # And WHY it is absent, in gis_service's words: `unreadable:<ExcType>`
        # or `outside_the_world`. A refusal that says «геометрия не читается»
        # about a polygon that read and was never reprojected is a sentence
        # that is false of the thing it describes.
        'centroid_unavailable': candidate.get('centroid_unavailable'),
    }


#: How an argument reached the search, as a refusal reports it back.
#:
#: Five states and not three, because «передан», «подтверждён» and «применён»
#: are different facts about the same value and this path has now been wrong
#: about each of them separately.
ARG_NOT_PASSED = 'not_passed'
ARG_NOT_FOUND = 'not_found'
ARG_ACCEPTED = 'accepted'
#: Sent, and the answer neither confirms nor contradicts it. A service older
#: than the scoping accepts `project_id` on `resolve_scope` and ignores it --
#: no error, no 422 -- so the answer arrives without `scoped_to_project`. But
#: an answer with no rows, or with rows only from the named project, is not
#: evidence that anything was ignored: claiming «сервис его не применил» there
#: sends a reader to check other projects that returned nothing.
ARG_NOT_CONFIRMED = 'not_confirmed'
#: Sent, and the answer carried rows from other projects. Only `_confine` sets
#: this, and only after seeing such a row, so the sentence is true of every
#: case that reaches it. Indistinguishable from `ARG_NOT_PASSED` in the message
#: until these states existed.
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
    """One line naming an argument a refusal asks for, and what arrived.

    Four refusals in this path have now asked the caller for something they had
    already supplied -- `licence_id` before the adapter carried it,
    `policy_version` before it was resolved, `licence_layers` which the tool
    does not declare, and `project_id`. Each cost a round to diagnose, and each
    would have ended in the message itself: «не передан» and «принят» are one
    line apart and the caller can read both.

    Stated for the argument the refusal names, not for every argument. A
    refusal that echoes everything it received is a log line, and the point
    here is the one value the reader is about to go and check.
    """
    if state not in _RECEIVED_RU:
        # Not a default. A new refusal site that invents a state would
        # otherwise print whichever wording happened to be first, and a line
        # whose job is to be true about what arrived is the last place to
        # guess.
        raise ValueError(f'unknown received state {state!r} for {name!r}')
    shown = repr(str(value)) if str(value or '').strip() else ''
    return f'{name}: ' + _RECEIVED_RU[state].format(value=shown)


def scope_state(named: str, resolution: Mapping[str, Any]) -> str:
    """How `project_id` fared, as far as this side can tell.

    `scoped_to_project` is the service saying it narrowed before searching. Its
    absence beside a supplied value is not «no opinion»: it is the answer to a
    scoped question arriving unscoped, which is what a deployment carrying the
    old service does.

    Its PRESENCE is a claim and not a proof, which is why nothing stops here.
    `_confine` checks the answer against its own claim: a reply that says it
    scoped to one project and carries rows from another did not scope, whatever
    the key says. Reading the key alone made «принят» the one state that
    disabled every check, on the say-so of the thing being checked.
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
    """The one project the answer should be confined to.

    `scoped_to_project` when the service resolved one, because that is the id
    the rows will carry: a caller may name a project the way a person does
    («Единый реестр лицензий РФ») while the store knows it as `GIS_Data_RF`,
    and only the service resolves one to the other. Comparing the caller's
    string to the rows directly would call that correct resolution a mismatch.
    """
    return str(resolution.get('scoped_to_project') or '').strip() or str(named).strip()


def _confine(resolution: dict[str, Any], named: str) -> dict[str, Any]:
    """Hold the answer to one project, and say when it had to be done here.

    The single-object path has had this condition since the beginning -- a
    supplied project short-circuits the cross-project search -- and the area
    path reported the ambiguity its own message says a `project_id` removes.
    `find_licence_across_projects` already takes a list of project ids, so
    scoping is a narrower input to the same call; here, one hop later, it is a
    narrower candidate list from the same answer. Done per member, because the
    caller who names a project has named it for all of them.

    Rows from the named project win outright. `GIS_Data_RF` is the national
    registry and holds almost any licence in the country, so a match in it
    beside the caller's own project is not an ambiguity and never was.

    Four things can be wrong with the answer and they are not one thing:

    * **A row that names no project.** Nothing here can tell whether it belongs
      to the project the caller named, and both silent readings are wrong. Kept
      as the only candidate it becomes the member -- an area filled from an
      unknown project, reported as success. Kept beside a named row it makes
      two candidates whose projects «agree», so the ambiguity refusal says
      «два состояния одной лицензии в вашем проекте» about a row that may be
      from another project entirely.
    * **One project, and not the one that was named.** The count said one, the
      auto-accept rule took it, and the run resolved against the registry the
      caller scoped away from -- the substitution this whole path exists to
      prevent, arriving silently instead of loudly.
    * **Several ids that differ only in case.** `Project1` and `PROJECT1` are
      two projects to the store and one string to a casefold. Merging them puts
      two projects in one member; passing them on rebuilds «Строки из разных
      проектов: Project1, PROJECT1. Укажите `project_id`», asked of a caller
      who supplied it. `_project_named` answers «several» with None rather than
      the first of them, and so does this.
    * **No row from the target at all.** This side cannot apply the scope;
      dropping every row would fabricate «не найдена» and keeping them would
      re-ask for `project_id`. It refuses, saying what it could not tell apart.
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
    # DISTINCT RAW ids, and the comparison below is between raw ids rather
    # than folded ones. Folding first hides the case that matters: `Project1`
    # and `PROJECT1` both fold to the target, so an answer holding two projects
    # read as «already confined to one» and was passed straight through.
    offered = sorted({
        str(item.get('project_id') or '').strip() for item in candidates
    })
    matched_ids = [item for item in offered if item.casefold() == target]
    narrowed = dict(resolution)
    narrowed['scope_projects_offered'] = offered
    if len(matched_ids) > 1:
        # Whatever the answer claimed. A reply carrying rows from projects it
        # says it excluded did not scope, and the state has to say the true
        # thing or the echo tells the reader it was honoured.
        narrowed['project_id_state'] = ARG_NOT_HONOURED
        narrowed['scope_ambiguous_here'] = True
        narrowed['scope_matched_ids'] = matched_ids
        return narrowed
    if offered == matched_ids:
        # One id, and it is the target. Already confined; claiming otherwise
        # would put a compensation notice on a run that never needed one.
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
    """Said on a SUCCESS, because the success is the answer that hides it.

    A refusal carries the state in its own text. A resolved area does not, and
    without this line an operator cannot tell, from any output the tool
    produces, whether the deployed search applies `project_id` or is being
    compensated for on every call -- so the gap this compensation covers would
    become permanently invisible the moment it started working.
    """
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
    """The `project_id` matched nothing, said as that and not as a licence miss.

    Two facts the caller needs and one they do not. They need the name that
    failed to match, because a typo is invisible in one's own message, and the
    names that would have matched. They do not need «лицензия не найдена»: no
    licence was searched for, and saying it would send them to check a number
    that was never in question.
    """
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
    """The refusal for a `project_id` that matched no project, or None.

    Checked before the candidate count on every path that searches, because
    every one of those counts is a statement about a search that did not run.
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
    """The search answer's `scope_resolution`, or a refusal that it was not one.

    `resolve_scope` always returns `scope_resolution`, on every branch
    including the empty query. Its absence therefore does not mean «nothing
    matched»; it means what came back was not a search answer at all.

    `project_id` scopes the search when the caller named a project. It was
    dropped here: the caller sent `Тенгкели-Березовская площадь`, the search
    read every project in the store, and `МАГ04805БЭ` came back twice -- once
    from the project asked about and once from `GIS_Data_RF`, the national
    registry -- as an ambiguity for the caller to resolve. They already had.
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
    # `candidates` carries two different shapes under one key. A search that
    # matched puts licence rows there; a search that matched nothing puts the
    # store's nearest PROJECT names there as suggestions, and says which it is
    # in `candidates_are`. Read as licence rows they are a licence nobody
    # searched for: a store holding one project produced one «candidate»,
    # `len(candidates) == 1`, and the area reported success over a member
    # fabricated out of a project name -- `entity_id` the project, `licence_id`
    # null. Moved to a key of their own, so that no count downstream can reach
    # them at all. This is not a scoped-search defect: the unscoped miss has
    # filled `candidates` this way since before `project_id` existed.
    if str(found.get('candidates_are') or '') == 'known_projects':
        found['known_projects'] = list(found.get('candidates') or [])
        found['candidates'] = []
    # The refusal's own code, which `scope_resolution` does not carry and this
    # function used to discard with the rest of the envelope. Without it a
    # `project_id` that matched nothing is indistinguishable from a licence
    # that does not exist, and the refusal blames the number the caller got
    # right instead of the project name they mistyped.
    error = (answer or {}).get('error') if isinstance(answer, Mapping) else None
    if isinstance(error, Mapping):
        found['search_error_code'] = str(error.get('code') or '')
        found['search_error_message'] = str(error.get('message') or '')
    # What was sent and how it fared, carried on the resolution so every
    # refusal below can echo it without re-deriving it from three places.
    found['project_id_received'] = scope
    found['project_id_state'] = scope_state(scope, found)
    # Checked whether the answer claimed to scope or not. Reading the claim
    # alone made «принят» the one state that skipped every check, decided by
    # the thing being checked.
    if found['project_id_state'] in (ARG_ACCEPTED, ARG_NOT_CONFIRMED):
        found = _confine(found, scope)
    return found


class _UnreadableSearch(Exception):
    """Raised rather than returned, so no branch can mistake it for «none»."""

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
    """Which licences this area is about — or the question, or the refusal.

    One shape for both tools, and the first row is the case a user is most
    likely in:

        licence_ids given         use them — no search, no question
        none, one licence found   use it, say which
        none, several found       ask
        none, zero found          refuse, naming what was searched

    `project_id` scopes every search. A licence held both by the project the
    caller named and by `GIS_Data_RF` is not ambiguous — they said which — and
    the multi-project refusal fired on exactly that pair.

    `licence_layers` qualifies a licence that lives in several layers WITHIN
    one project, keyed by the licence number. Per licence and never shared:
    five layers for `МАГ03395БЭ` says nothing about where `МАГ03400БЭ` lives, and one
    licence's choice silently applied to another's is a member in a state
    nobody chose -- which is what the ambiguity refusal exists to prevent.

    The layers are NOT merged. A licence in `Licenses_2024_2025`,
    `Licenses_annul` and `Juniors` is not one polygon listed three times: those
    are states, with possibly different geometries and dates.
    """
    supplied = [str(item or '').strip() for item in licence_ids]
    supplied = [item for item in supplied if item]

    if supplied:
        members: list[dict[str, Any]] = []
        # Which numbers this side had to narrow. A refusal carries the state in
        # its own text; a RESOLVED area does not, and without this an operator
        # cannot tell from any output whether the deployed search applies
        # `project_id` or is being compensated for on every call.
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
            # The qualifier is applied BEFORE the count is judged, which is the
            # whole point of having one. A check that refuses «found in 5
            # layers» and only then consults the argument meant to answer it is
            # indistinguishable from having no argument -- this project has met
            # that shape twice, and the task names it as the cause to rule out
            # first.
            #
            # `len(candidates)` is deliberately NOT part of this condition. A
            # qualifier is a statement about WHICH layer, not about how many
            # were offered: one candidate in `Licenses_annul` does not answer a
            # caller who named `Licenses_2024_2025`. Gating the check on «more
            # than one» silently fills the area from the annulled polygon while
            # reporting an ordinary success -- worse than the ambiguity this
            # argument exists to resolve, because nobody chose it and nobody is
            # told.
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
                'layers': _candidate_layers(candidates),
                'message': ambiguous_licence(number, candidates, _scope_echo(resolution)),
            }
        return {
            'status': RESOLVED,
            'members': members,
            'resolved_from': 'supplied',
            # Said, then done. The count is known here and nowhere later
            # is it as cheap to state.
            'cost_notice': cost_notice(len(members)),
            # Present only when this side did the scoping the search did not.
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
        # A name search answers «which project», not «which polygon»:
        # `resolve_project` returns an id, a name and a layer count, and there
        # is no geometry behind it to take a centroid from. So this member has
        # no position, and unless the caller named a `calculation_crs` the area
        # refuses -- correctly, but it has to say WHY, or the refusal blames a
        # registry that was never asked.
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
    # The project by name when the search was scoped to one. «Искали в
    # проектах: 1» is strictly less than the «24» it replaced: the caller who
    # scoped the search is the one this whole path was built for, and the
    # number they get back is the one fact they already knew.
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

#: The aggregation policy this fork folds under.
#:
#: Named here rather than read, because there is nothing here to read it from:
#: the policy ships inside `gis_service` as
#: `arcgis_mcp/geotizer/assets/area_aggregation_policy.v1.json`, the fold loads
#: it there with a pinned digest, and two deployables cannot share a file any
#: more than they can share an import. So the caller must NAME the policy it
#: expects, and this is the fork's answer when the user names none.
#:
#: A constant the answer states is reproducible; that is the whole distinction
#: the refusal this replaces was defending. What it must not become is a
#: constant that drifts from the policy actually shipped, so
#: `GMM/scripts/validate_area_policy_version.py` checks this string against
#: gis_service's asset, GMM's published contract and the generator that writes
#: both -- four sources, one value, one validator.
AREA_POLICY_VERSION = 'geotizer_area_aggregation.v1'

SUPPLIED = 'supplied'
RESOLVED_BY_SYSTEM = 'resolved'

NO_CENTROID = 'area_centroid_unavailable'

#: A `calculation_crs` this tool cannot place. Its own reason, because «not
#: recognised» and «geographic» send a reader to different next steps.
CRS_NOT_RECOGNISED = 'calculation_crs_not_recognised'

#: This module's own, unlike the two `scope.licence_centroid` returns. A name
#: search resolves to a PROJECT -- an id, a name and a layer count -- and there
#: is no polygon behind it to take a centroid from. Without it such a member
#: reaches the refusal as «причина не сообщена», which sends a reader to look
#: for a fault in a registry nobody read.
NAME_SEARCH_HAS_NO_POLYGON = 'name_search_has_no_polygon'

#: The geographic CRSs a length may not be measured in. Mirrors
#: `gis_service`'s `measurement_crs._GEOGRAPHIC`; a value in any of them is in
#: degrees, and a supplied one has to be refused rather than used.
_GEOGRAPHIC_CRS = frozenset({'EPSG:4326', 'EPSG:4284', 'EPSG:7683', 'EPSG:4979'})


def utm_zone_for(longitude: float, latitude: float) -> str:
    """The UTM zone containing a point, as an EPSG code.

    The same arithmetic as `gis_service.geotizer.measurement_crs.utm_zone_for`
    and `infrastructure.py`, which is three copies of six characters of
    arithmetic in two repositories. Restated rather than imported for the usual
    reason: two deployables cannot share a Python import.

    Pinned twice, because a restated formula drifts silently. In this repo,
    `test_the_worked_examples_resolve_to_the_zones_the_task_names` checks the
    worked examples the task supplies -- Магаданская область is EPSG:32656, the
    Лекын area EPSG:32642, the demo package EPSG:32653. Across the boundary,
    `GMM/scripts/validate_utm_zone_arithmetic.py` extracts all three copies and
    runs those same examples through each, so a change to one that the others
    do not follow is reported rather than measured.
    """
    zone = min(60, max(1, int((float(longitude) + 180) // 6) + 1))
    return f'EPSG:{(32600 if float(latitude) >= 0 else 32700) + zone}'


def _centroid_of(member: Mapping[str, Any]) -> tuple[float, float] | None:
    """A member's centroid as two finite floats, or None.

    `gis_service.scope.licence_centroid` already bounds what it returns, so
    nothing reaching here today is NaN, infinite or a string. This function is
    public, independently tested and one `gis_call` implementation away from a
    different caller, and `utm_zone_for` raises rather than refuses on any of
    those: `int(nan)` is a `ValueError`, `int(inf)` an `OverflowError`. An
    unhandled exception out of `fill_area` is not one of the answer shapes this
    module has, so the value is dropped here and counted as a member without a
    centroid -- which it is.
    """
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
    """One projected CRS for the whole area, from where the members are.

    Step two of the fallback `measurement_crs.py` records: the zone of the
    area's centroid. Step one -- the target polygon's own CRS when it is
    projected -- has no input here, because a licence search returns a number
    and a layer and the polygons this system meets are stored in geographic
    CRSs anyway.

    **The longitudes average on a circle.** See the comment at the arithmetic:
    a plain mean is wrong by half the world for an area crossing 180°, and this
    country does.

    **One zone for the area, never one per member.** Members measured in
    different projections cannot be summed, and the fold sums them. An area
    spanning several zones takes the zone of its own centroid and records the
    span, which is what a projected measurement is: bounded distortion, stated.

    The centroid is the mean of the member centroids rather than the centroid
    of their union -- the union needs the geometry, and what crosses the
    service boundary is a point per member. For members inside one region the
    two agree to far less than the 6° a zone is wide; for members that do not,
    the recorded span is what tells a reader so.

    None when no member carried a centroid, which is the refusal case and not
    a default.
    """
    # Materialised once. `members` is declared a `Sequence`, but nothing checks
    # that at runtime, and the counts below iterate it a second time: given a
    # generator, the second pass saw it exhausted and reported
    # `members_with_centroid: 1, members_total: 0` -- a record that contradicts
    # itself, from a function whose whole job is to be reproducible.
    member_list = list(members)
    points = [
        point for point in (_centroid_of(member) for member in member_list)
        if point is not None
    ]
    if not points:
        return None
    # Longitudes average on a circle, not on a line. This country crosses the
    # antimeridian: two Чукотка licences at +179.5 and -179.5 are 1° apart and
    # a plain mean puts their midpoint at 0°, which is EPSG:32631 — the North
    # Sea. The circular mean puts it at 180°, EPSG:32660, where they are.
    #
    # Latitude does not need this. It has no wrap: -90 and +90 are the poles,
    # not neighbours, and no area spans them.
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
        # Both, always. One zone is the usual case and says so; several is the
        # case a reader has to know about, and a field that appears only then
        # is a field nobody builds a habit of reading.
        'zones_spanned': zones,
        'spans_several_zones': len(zones) > 1,
    }


def epsg_code(crs: str) -> str | None:
    """`EPSG:NNNN` for a value spelled any of the ways a caller spells one, or
    None when this tool cannot tell which CRS is meant.

    The comparison this feeds used to be a set membership on the literal string
    `'EPSG:4326'`, and this value arrives from an LLM tool call rather than from
    another program: `4326`, `epsg:4326` and `EPSG: 4326` all mean WGS 84 and
    all passed that test as «projected». The area was then measured in square
    degrees by the very check written to prevent it.

    None is a third answer and not a «no». A proj4 string or a WKT name may well
    be projected; this function simply cannot say, and the caller refuses on
    «cannot tell» rather than guessing either way -- a gap and a guard must not
    look alike.
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
    """Whether a length measured in this CRS is a length.

    False for a geographic CRS AND for a spelling this tool cannot place, so
    never call it where those two need different answers -- `resolve_contract`
    asks `epsg_code` first for exactly that reason.
    """
    code = epsg_code(crs)
    return code is not None and code not in _GEOGRAPHIC_CRS

#: What `AreaMember` accepts. The resolved member carries more than the scope
#: request will take -- `extra="forbid"` is the point of that request, and a
#: field it does not declare must be dropped here rather than discovered there.
_SCOPE_FIELDS = ('entity_id', 'entity_type', 'name')


def resolve_contract(
    *,
    policy_version: str,
    calculation_crs: str,
    members: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The two contract values, each with how it was obtained — or a refusal.

    The refusal this replaces was correct and unworkable: both fields are
    required, neither is defaulted, and a user asking to fill an area holds
    neither, so every area call refused. What the objection forbids is a
    **hidden** default — the policy assumed, nobody recording which — and a
    resolved value is the opposite of that. It is read, used, and stated in the
    answer and on the manifest, so the run reproduces exactly.

    Three rows, in order:

        supplied     use it, never override, record 'supplied'
        resolved     use it, name it, record 'resolved'
        neither      refuse, naming WHICH one failed and why

    The third is not hypothetical and it is the reason this returns a shape
    rather than a string: a member whose polygon would not read has no
    centroid, and the refusal has to say that rather than repeat the old
    sentence about both fields.

    A supplied `calculation_crs` is checked, not trusted: `EPSG:4326` is a CRS
    a caller can name and a square degree is not an area, which is the whole of
    the original objection. Refused rather than replaced -- overriding a value
    the user named is the one thing the precedence forbids.
    """
    policy = str(policy_version or '').strip()
    crs = str(calculation_crs or '').strip()

    if policy and policy != AREA_POLICY_VERSION:
        # Checked, not trusted, for the same reason a supplied `calculation_crs`
        # is checked: a value the caller names is used verbatim, so a wrong one
        # is used verbatim too. There is exactly one policy and its version is
        # pinned in four places at once -- the published document, the
        # generator, the asset the fold loads and this constant -- so a
        # mismatch is not a newer policy this side has not heard of. It is a
        # value nobody has.
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
        # «I cannot tell» is not «yes». A WKT name or a proj4 string may be
        # perfectly projected, but nothing here can say so, and accepting it
        # would measure the area in whatever it turns out to be.
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
        # `is_projected` answers False for «geographic» AND for «cannot tell»,
        # which is why the branch above runs first: by here `crs` is placeable,
        # so False means geographic and this message is true of it.
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
            # `policy` is either empty or equal to the constant by here, so
            # this states which of the two happened rather than which value
            # won -- they are the same value.
            'value': policy or AREA_POLICY_VERSION,
            'source': SUPPLIED if policy else RESOLVED_BY_SYSTEM,
        },
        'calculation_crs': crs_record,
    }


#: What gis_service says when a licence row yielded no centroid, in the words a
#: reader gets. The keys are `scope.CENTROID_UNREADABLE` (which arrives with an
#: exception type appended) and `scope.CENTROID_OUTSIDE_THE_WORLD`.
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
    """How many members failed for each reason, not just how many failed.

    A count alone sends a reader to check a geodatabase that may be fine. The
    refusal below states these, so the sentence is true of the members it is
    about rather than true of the commonest case.
    """
    counts: dict[str, int] = {}
    for member in members:
        # `_centroid_of` and not a None check, so «counted as having no
        # centroid» and «counted in the causes» mean the same set of members.
        # A NaN is dropped there; dropping it here too keeps the totals honest.
        if _centroid_of(member) is not None:
            continue
        cause = str(member.get('centroid_unavailable') or '').strip() or 'unknown'
        counts[cause] = counts.get(cause, 0) + 1
    return counts


def _centroid_causes_ru(members: Sequence[Mapping[str, Any]]) -> str:
    """The same counts as a clause, with the exception type kept when there is
    one: `unreadable:AttributeError` is a bug here, not a missing registry, and
    a reader who is shown the type can tell."""
    parts = []
    for cause, count in sorted(_centroid_causes(members).items()):
        head, _, detail = cause.partition(':')
        text = _CENTROID_CAUSE_RU.get(head, _CENTROID_CAUSE_UNKNOWN_RU)
        if detail:
            text = f'{text} ({detail})'
        parts.append(f'{text}: {count}')
    return '; '.join(parts) or 'причина не сообщена'


def contract_line(contract: Mapping[str, Any]) -> str:
    """The sentence that keeps this from being the silent default it replaces.

    Without it the run picks two values and says nothing, which is exactly what
    the refusal existed to prevent. With it a reader sees which choice was the
    system's and can reproduce the run from the answer alone.
    """
    policy = contract['policy_version']
    crs = contract['calculation_crs']
    policy_tail = '' if policy['source'] == SUPPLIED else ' (по умолчанию для этой сборки)'
    if crs['source'] == SUPPLIED:
        crs_tail = ' (указана в запросе)'
    else:
        notes = ['зона по центроиду площади']
        # How many members that centroid was taken from. One member out of
        # twenty reads exactly like twenty out of twenty without this, and the
        # whole area is then measured from wherever that one licence happens to
        # be. The numbers were already computed and simply never said.
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
    area_concurrency_note: str = '',
    member_arguments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve, fill, fold and summarise — or ask, or refuse.

    Three service calls and three of them, not one. `gis_call` is
    `geotizer_fill`, which carries the state machine and `resolve_scope` with
    it; `scope_call` is `geotizer_area_scope`; `fold_call` is
    `geotizer_area_fold`. They are separate operations on the tool server with
    separate request models, and the first version of this passed `gis_call` to
    all three — every area fill would have sent `resolve_area_scope` and
    `fold_area` to an endpoint whose action set contains neither, and been
    refused whole. No default: a parameter that falls back to `gis_call` is the
    same defect with somewhere to hide.

    Returns a dict carrying `status` and, when there is one, `result`. The
    caller renders; nothing here writes Markdown, for the same reason the
    object path's wording lives in `terminal.py`.
    """
    resolution = await resolve_area_members(
        gis_call=gis_call,
        object_name=object_name,
        licence_ids=licence_ids,
        licence_layers=licence_layers,
        # The same project that names the area's owner below. It was read here
        # only for the manifest, so a caller who named their project had it
        # honoured everywhere except in the search that decides membership.
        project_id=project_id,
    )
    if resolution['status'] != RESOLVED:
        return resolution

    members = resolution['members']
    # AFTER resolution, not before it: the CRS is resolved from where the
    # members are, so there is nothing to resolve from until they exist. The
    # supplied-value check could run earlier and deliberately does not -- one
    # place decides both fields, and a caller who supplied a bad CRS and a
    # licence that does not exist should hear about the licence first, because
    # that is the one that stops the run whatever the CRS says.
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

    # The manifest is authoritative about membership and says nothing about how
    # to fill a member. Merged by `entity_id` rather than by position: the
    # resolver is free to order members however the hierarchy requires, and a
    # zip would silently pair the wrong card with the wrong licence.
    fill_fields = {
        member['entity_id']: {
            'object_name': member['object_name'],
            'project_id': member.get('project_id'),
            # What identifies the member, and what the manifest does not carry.
            # Dropped here, every member fill reached the object path with a
            # project and no licence, met seven licence polygons with nothing
            # to select by, and refused `gis_project_multi_licence` -- three
            # times identically, which is what a shared argument looks like.
            'licence_id': member.get('licence_id'),
            'licence_layer_id': member.get('licence_layer_id'),
        }
        for member in members
    }
    merged = dict(manifest)
    merged['area_id'] = merged.get('area_id') or area_id
    # Both values and their provenance, on the manifest the run is reproduced
    # from. Without this the run picks two values and says nothing, which is
    # the silent default the refusal existed to prevent -- resolution only
    # preserves reproducibility if the resolved value is recorded.
    merged['contract_resolution'] = {
        'policy_version': contract['policy_version'],
        'calculation_crs': contract['calculation_crs'],
    }
    merged['members'] = [
        dict(item) | fill_fields.get(str(item.get('entity_id') or ''), {})
        for item in (manifest.get('entities') or [])
    ]
    if not merged['members']:
        # Resolution already required at least one member to get here, so an
        # empty manifest is the manifest call having failed -- an error body
        # surfaced as data, or a key that moved. Proceeding would fill nothing
        # and report «0 участников» as a successful area, which is the one
        # answer worse than a refusal.
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
    )
    return {
        'status': RESOLVED,
        'resolved_from': resolution['resolved_from'],
        # Carried, not recomputed. The count it states is the resolved
        # membership, and recomputing it here from `outcome` would let the two
        # disagree about the same run.
        'cost_notice': resolution.get('cost_notice'),
        # Carried for the same reason as the cost: the answer reporting a
        # success is the one place a compensated run looks identical to a
        # working one.
        **(
            {'scope_notice': resolution['scope_notice']}
            if resolution.get('scope_notice')
            else {}
        ),
        # Present only when a configured deadline was refused. An operator who
        # believes the area is bounded and an operator who never set a bound
        # are otherwise reading the same answer.
        **(
            {'area_deadline_note': area_deadline_note.strip()}
            if area_deadline_note.strip()
            else {}
        ),
        # Same rule for the concurrency valve: a refused value and an unset
        # one otherwise reach the operator as the same answer.
        **(
            {'area_concurrency_note': area_concurrency_note.strip()}
            if area_concurrency_note.strip()
            else {}
        ),
        'contract': contract,
        'result': outcome,
    }


def _member_line(item: Mapping[str, Any]) -> str:
    """One member as the answer lists it: what happened, and how to reach it.

    A filled member carries its `run_id` because that is what a caller inspects
    it with -- §3 is deferred, so there is no area-level id to poll, and the
    per-member ids are the only handles that exist.

    A *failed* member carries one too, whenever the run got far enough to have
    one. It holds whatever was filled before the failure and is resumable; a
    line that reported only the error left that run in the store with nothing
    naming it.
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
        run_id = item.get('run_id')
        # No parenthesis at all when the fill died before a run existed.
        # «(``)» would read as a handle the reader can use.
        handle = f' (`{run_id}`)' if run_id else ''
        return f'- {name} — не заполнен: {item.get("error")}{handle}'
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
    # What this cost and what happens when the request ends first. Said at the
    # top because the answer that carries it is the one a caller may never see
    # — and the notice is the whole reason the run started instead of refusing.
    notice = str(payload.get('cost_notice') or '').strip()
    # A refused deadline valve, when there was one. Beside the cost notice
    # because it changes what that notice means: «примерно 18 часов» with no
    # bound behind it is a different statement from the same words with one.
    deadline_note = str(payload.get('area_deadline_note') or '').strip()
    # And the concurrency valve's. This was assembled into the payload and
    # read by nothing for one commit: `render_area_answer` had a line for the
    # deadline note and none for this one, so an operator who mistyped
    # GEOMAS_AREA_CONCURRENT_MEMBERS was told nothing and the area ran at the
    # default. A note that reaches no reader is the silence it exists to break.
    concurrency_note = str(payload.get('area_concurrency_note') or '').strip()
    # What this side had to do that the search should have done. Beside the
    # other two because it changes how the result should be read.
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

    # What the run resolved for itself, stated. This line is what separates a
    # resolved value from the hidden default the old refusal existed to
    # prevent: with it a reader sees which of the two choices was the
    # system's and can reproduce the run from the answer alone.
    contract = payload.get('contract')
    if isinstance(contract, Mapping) and contract.get('status') == RESOLVED:
        lines.extend([contract_line(contract), ''])

    if aggregation.get('state') == PERFORMED:
        markdown = str(result.get('summary_markdown') or '').strip()
        lines.append(markdown or 'Свод построен, но пуст.')
    else:
        # Named, never absent. «Свода нет» with no reason is the shape this
        # whole document is written against.
        reason = aggregation.get('reason')
        if reason == 'nothing_filled':
            # The one reason a reader can already see. Every member's own
            # reason is printed a few lines above, so this points at them
            # rather than introducing an internal term nobody can act on:
            # `fold_failed` described the fold answering without an
            # aggregation, which is true and is not what happened.
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
