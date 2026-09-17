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

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

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
LAYER_NOT_AMONG_CANDIDATES = 'licence_layer_not_among_candidates'
TOO_MANY_MEMBERS = 'too_many_members'
#: The search answered with something that is not a search answer. Not
#: «not found»: `resolve_scope` always carries `scope_resolution`, so its
#: absence means the reply was never one -- an error body surfaced as data,
#: most likely. Saying «не найдена» about a licence nobody looked up is a
#: specific false claim, which is worse than admitting the reply was unread.
SEARCH_UNREADABLE = 'search_unreadable'
#: The manifest came back without the members that went into it.
MANIFEST_WITHOUT_MEMBERS = 'manifest_without_members'

GisCall = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def member_ceiling(area_deadline_seconds: float | None = None) -> int:
    """How many members fit inside the deadline, at the measured cost.

    Derived, not chosen: the ceiling is whatever the deadline divided by a
    member comes to, so moving the valve moves the limit and no second number
    has to be kept in step with it.
    """
    if area_deadline_seconds in (None, ''):
        seconds = float(DEFAULT_AREA_DEADLINE_SECONDS)
    else:
        try:
            seconds = float(area_deadline_seconds)
        except (TypeError, ValueError):
            # The valve arrives as a raw environment string. Garbage is not a
            # deadline of zero, and raising here would take down every area
            # call before it could search, ask or refuse -- the failure this
            # module exists to replace. `resolve_fill_deadline` makes the same
            # choice for the sibling valve; only the default differs.
            seconds = float(DEFAULT_AREA_DEADLINE_SECONDS)
    if seconds <= 0:
        # Zero means «no deadline» on the object path. Here it would mean a
        # ceiling of zero members, which refuses every area including the one
        # the deadline was raised for.
        seconds = float(DEFAULT_AREA_DEADLINE_SECONDS)
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


def _layer_lines(candidates: Sequence[Mapping[str, Any]]) -> str:
    """The layers as a reader can act on them: one per line, glossed."""
    lines = []
    for name in _candidate_layers(candidates):
        gloss = _LAYER_MEANING_RU.get(name)
        lines.append(f'  {name}' + (f'    {gloss}' if gloss else ''))
    return '\n'.join(lines)


def ambiguous_licence(number: str, candidates: Sequence[Mapping[str, Any]]) -> str:
    """The multi-layer refusal, naming the layers it found.

    It used to COUNT them -- «найдена в нескольких слоях (5)» -- which is a
    dead end where a next step would fit, the same defect as `candidates: []`.
    A count cannot be acted on; five names can, and the object tool's own
    refusal has named its layers since it gained `licence_layer_id`.

    The layers are not merged and never will be here. `Licenses_2024_2025`,
    `Licenses_annul` and `Juniors` are states of a licence -- current,
    annulled, junior-programme -- with possibly different geometries and dates.
    Folding them produces a member in a state nobody chose, which is precisely
    what this refusal says.
    """
    layers = _candidate_layers(candidates)
    return (
        f'{number} найдена в {len(layers)} слоях:\n'
        f'{_layer_lines(candidates)}\n'
        'Укажите, какой слой использовать для этой лицензии '
        '(`licence_layers`). Слои не объединяются: это состояния лицензии — '
        'действующая, аннулированная, юниорская — с разной геометрией и '
        'разными датами, и свести их значило бы выбрать состояние за '
        'пользователя.'
    )


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
    }


async def _search(gis_call: GisCall, query: str) -> dict[str, Any]:
    """The search answer's `scope_resolution`, or a refusal that it was not one.

    `resolve_scope` always returns `scope_resolution`, on every branch
    including the empty query. Its absence therefore does not mean «nothing
    matched»; it means what came back was not a search answer at all.
    """
    answer = await gis_call({'action': 'resolve_scope', 'query': query})
    resolution = (answer or {}).get('scope_resolution') if isinstance(answer, Mapping) else None
    if not isinstance(resolution, Mapping):
        raise _UnreadableSearch(query)
    return dict(resolution)


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
    area_deadline_seconds: float | None = None,
) -> dict[str, Any]:
    """Which licences this area is about — or the question, or the refusal.

    One shape for both tools, and the first row is the case a user is most
    likely in:

        licence_ids given         use them — no search, no question
        none, one licence found   use it, say which
        none, several found       ask
        none, zero found          refuse, naming what was searched

    `licence_layers` qualifies a licence that lives in several layers, keyed by
    the licence number. Per licence and never shared: five layers for
    `МАГ03395БЭ` says nothing about where `МАГ03400БЭ` lives, and one
    licence's choice silently applied to another's is a member in a state
    nobody chose -- which is what the ambiguity refusal exists to prevent.

    The layers are NOT merged. A licence in `Licenses_2024_2025`,
    `Licenses_annul` and `Juniors` is not one polygon listed three times: those
    are states, with possibly different geometries and dates.
    """
    ceiling = member_ceiling(area_deadline_seconds)
    supplied = [str(item or '').strip() for item in licence_ids]
    supplied = [item for item in supplied if item]

    if supplied:
        if len(supplied) > ceiling:
            # Before the searches, not after them. Every supplied number that
            # resolves becomes exactly one member, so the count is known now --
            # and `too_many_members` promises a refusal that costs a second
            # rather than a day. Twenty-one sequential lookups before saying no
            # is not that promise kept.
            return {
                'status': REFUSED,
                'reason': TOO_MANY_MEMBERS,
                'members_total': len(supplied),
                'ceiling': ceiling,
                'message': too_many_members(len(supplied), ceiling),
            }
        members: list[dict[str, Any]] = []
        for number in supplied:
            try:
                resolution = await _search(gis_call, number)
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
            candidates = list(resolution.get('candidates') or [])
            # The qualifier is applied BEFORE the count is judged, which is the
            # whole point of having one. A check that refuses «found in 5
            # layers» and only then consults the argument meant to answer it is
            # indistinguishable from having no argument -- this project has met
            # that shape twice, and the task names it as the cause to rule out
            # first.
            wanted_layer = str((licence_layers or {}).get(number) or '').strip()
            if wanted_layer and len(candidates) > 1:
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
                'message': ambiguous_licence(number, candidates),
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

    try:
        resolution = await _search(gis_call, query)
    except _UnreadableSearch:
        return {
            'status': REFUSED,
            'reason': SEARCH_UNREADABLE,
            'message': (
                f'Поиск по «{query}» вернул ответ, который не является ответом '
                'поиска. «Не найдена» о ней не утверждается.'
            ),
        }
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

#: The geographic CRSs a length may not be measured in. Mirrors
#: `gis_service`'s `measurement_crs._GEOGRAPHIC`; a value in any of them is in
#: degrees, and a supplied one has to be refused rather than used.
_GEOGRAPHIC_CRS = frozenset({'EPSG:4326', 'EPSG:4284', 'EPSG:7683', 'EPSG:4979'})


def utm_zone_for(longitude: float, latitude: float) -> str:
    """The UTM zone containing a point, as an EPSG code.

    The same arithmetic as `gis_service.geotizer.measurement_crs.utm_zone_for`
    and `infrastructure.py`, which is three copies of six characters of
    arithmetic in two repositories. Restated rather than imported for the usual
    reason, and pinned by `test_the_area_call_resolves_what_nobody_can_supply`
    against the worked examples the task supplies: Магаданская область is
    EPSG:32656, the Лекын area EPSG:32642, the demo package EPSG:32653.
    """
    zone = min(60, max(1, int((float(longitude) + 180) // 6) + 1))
    return f'EPSG:{(32600 if float(latitude) >= 0 else 32700) + zone}'


def resolve_calculation_crs(members: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """One projected CRS for the whole area, from where the members are.

    Step two of the fallback `measurement_crs.py` records: the zone of the
    area's centroid. Step one -- the target polygon's own CRS when it is
    projected -- has no input here, because a licence search returns a number
    and a layer and the polygons this system meets are stored in geographic
    CRSs anyway.

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
    points = [
        (float(member['centroid_lon']), float(member['centroid_lat']))
        for member in members
        if member.get('centroid_lon') is not None
        and member.get('centroid_lat') is not None
    ]
    if not points:
        return None
    longitude = sum(item[0] for item in points) / len(points)
    latitude = sum(item[1] for item in points) / len(points)
    zones = sorted({utm_zone_for(lon, lat) for lon, lat in points})
    return {
        'crs': utm_zone_for(longitude, latitude),
        'chosen_by': 'centroid_zone',
        'centroid': [round(longitude, 6), round(latitude, 6)],
        'members_with_centroid': len(points),
        'members_total': len(list(members)),
        # Both, always. One zone is the usual case and says so; several is the
        # case a reader has to know about, and a field that appears only then
        # is a field nobody builds a habit of reading.
        'zones_spanned': zones,
        'spans_several_zones': len(zones) > 1,
    }


def is_projected(crs: str) -> bool:
    """Whether a length measured in this CRS is a length."""
    text = str(crs or '').strip()
    return bool(text) and text.upper() not in _GEOGRAPHIC_CRS

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
        resolved = resolve_calculation_crs(members)
        if resolved is None:
            return {
                'status': REFUSED,
                'reason': NO_CENTROID,
                'failed': 'calculation_crs',
                'members_total': len(list(members)),
                'message': (
                    'Не удалось определить систему координат для измерения: ни '
                    'у одного из участников площади не читается геометрия, '
                    'поэтому у площади нет центроида, а по нему выбирается '
                    'зона UTM. Площадь не заполнена. Укажите '
                    '`calculation_crs` явно — проекционную систему, в которой '
                    'мерить пересечения.'
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
        crs_tail = ' (зона по центроиду площади)'
        if crs.get('spans_several_zones'):
            crs_tail = (
                f' (зона по центроиду площади; участники попадают в '
                f'{len(crs["zones_spanned"])} зоны: '
                f'{", ".join(crs["zones_spanned"])})'
            )
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
        area_deadline_seconds=area_deadline_seconds,
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
        fold_call=fold_call,
        policy_version=policy_version,
        dossier_run_id=str(dossier_run_id or '').strip() or area_id,
    )
    return {
        'status': RESOLVED,
        'resolved_from': resolution['resolved_from'],
        'contract': contract,
        'result': outcome,
    }


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
        detail = aggregation.get('error') or aggregation.get('missing')
        lines.append(f'Свод не построен: {reason}' + (f' ({detail})' if detail else ''))

    return '\n'.join(lines)
