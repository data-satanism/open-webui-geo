"""An area fill: the single-object fill run once per member, then a fold.

`run_geotizer_area_workflow` fills every member of a resolved area through an
injected single-object fill, records each member's terminal state, and folds
the filled members through an injected `fold_call`. The returned `aggregation`
always carries a `state`, and a `reason` whenever the state is `not_performed`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

MemberFill = Callable[..., Awaitable[dict[str, Any]]]

FoldCall = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

ProgressCall = Callable[[Mapping[str, int]], Awaitable[None]]


NOT_PERFORMED = 'not_performed'
PERFORMED = 'performed'

FOLD_NOT_REQUESTED = 'fold_not_requested'
FOLD_FAILED = 'fold_failed'
NOTHING_FILLED = 'nothing_filled'

FILLED = 'filled'
FAILED = 'failed'
NOT_ATTEMPTED = 'not_attempted'

_SETTLED = (FILLED, FAILED, NOT_ATTEMPTED)

_UNREACHED = {
    FAILED: 'member_run_failed',
    NOT_ATTEMPTED: 'member_not_attempted',
}

NO_OBJECT_NAME = 'member_has_no_object_name'
AREA_DEADLINE_REACHED = 'area_deadline_reached'

DEFAULT_CONCURRENT_MEMBERS = 3


def _member_order(members: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The order members are filled and reported in: by `rank`, then by `entity_id`."""
    return sorted(
        members,
        key=lambda member: (int(member.get('rank') or 0), str(member.get('entity_id') or '')),
    )


def _crashed(member: Mapping[str, Any], error: BaseException) -> dict[str, Any]:
    """A `failed` entry for a member whose task raised past the fill's own handler.

    Same shape as the handler's own failure entry, with `licence_id` when the
    request carried one.
    """
    entity_id = str(member.get('entity_id') or '')
    crashed = {
        'entity_id': entity_id,
        'object_name': str(member.get('licence_id') or member.get('object_name') or entity_id),
        'state': FAILED,
        'error': f'{type(error).__name__}: {error}',
    }
    if member.get('licence_id'):
        crashed['licence_id'] = member['licence_id']
    return crashed


async def run_geotizer_area_workflow(
    *,
    manifest: Mapping[str, Any],
    member_fill: MemberFill,
    member_arguments: Mapping[str, Any] | None = None,
    area_deadline_seconds: float | None = None,
    concurrent_members: int = DEFAULT_CONCURRENT_MEMBERS,
    clock: Callable[[], float] | None = None,
    fold_call: FoldCall | None = None,
    policy_version: str | None = None,
    dossier_run_id: str | None = None,
    project_id: str | None = None,
    calculation_crs: str | None = None,
    area_display_name: str | None = None,
    on_progress: ProgressCall | None = None,
) -> dict[str, Any]:
    """Fill every member of a resolved area, then fold the filled members.

    `manifest` carries `area_id`, `contract_resolution` and `members`; a member
    supplies `entity_id`, `rank`, `object_name`, `project_id`, `licence_id` and
    `licence_layer_id`. `member_fill` is called once per member with
    `object_name`, `project_id`, `licence_id`, `licence_layer_id`, `started_run`,
    `area_member=True` and `member_arguments`. A member with a licence is filled
    by that licence with an empty `object_name`; a member with neither is recorded
    as `not_attempted` with `member_has_no_object_name`.

    `member_arguments` may not carry a keyword the loop binds itself or one of
    `member_fill.per_member_keys`; such a keyword raises `ValueError`.

    `area_deadline_seconds` bounds the area, not a member. It is checked when a
    member acquires a concurrency slot, and a member that acquires one past it is
    recorded as `not_attempted` with `area_deadline_reached`.

    `concurrent_members` bounds how many members fill at once, never how many are
    filled; it is at least one, and an unusable value means
    `DEFAULT_CONCURRENT_MEMBERS`.

    `on_progress` is awaited with the counts `members`, `running`, `filled`,
    `failed` and `not_attempted` before any member starts and after every member
    transition; an exception from it is recorded, not raised.

    Returns a document with `schema_version`, `area_id`, `contract_resolution`,
    `members` (in `_member_order`), `counts` and `aggregation`; `summary`,
    `summary_markdown`, `artifacts` and `area_run_id` when the fold returned them;
    and `progress_line` only when a progress report failed or a member reported a
    state outside `_SETTLED`. A member whose fill raises is recorded as `failed`,
    with its `run_id` when the run had started; a cancellation of the area is
    re-raised.
    """
    clock = clock or asyncio.get_event_loop().time
    started = clock()
    members = _member_order(list(manifest.get('members') or []))
    arguments = dict(member_arguments or {})
    per_member_names = set(getattr(member_fill, 'per_member_keys', ()) or ())
    collisions = sorted(
        set(arguments)
        & (
            per_member_names
            | {
                'object_name',
                'project_id',
                'started_run',
                'licence_id',
                'licence_layer_id',
                'area_member',
            }
        )
    )
    if collisions:
        raise ValueError(
            f'member_arguments may not carry {", ".join(collisions)}: the member loop binds those itself'
        )

    try:
        bound = max(1, int(concurrent_members))
    except (TypeError, ValueError):
        bound = DEFAULT_CONCURRENT_MEMBERS
    gate = asyncio.Semaphore(bound)

    counts = {
        'members': len(members),
        'running': 0,
        'filled': 0,
        'failed': 0,
        'not_attempted': 0,
    }

    delivery = asyncio.Lock()

    progress: dict[str, Any] = {'attempts': 0, 'failures': 0}
    unaccounted: list[str] = []

    async def report() -> None:
        """The area's own line, after a transition rather than on a timer."""
        if on_progress is None:
            return
        async with delivery:
            progress['attempts'] += 1
            try:
                await on_progress(dict(counts))
            except Exception as error:  # noqa: BLE001
                progress['failures'] += 1
                progress.setdefault('error', f'{type(error).__name__}: {error}')

    def settle(outcome: Mapping[str, Any]) -> None:
        """Count a settled member under the state it reports.

        A state outside `_SETTLED` is appended to `unaccounted` instead.
        """
        state = str(outcome.get('state') or '')
        if state in _SETTLED:
            counts[state] += 1
            return
        unaccounted.append(state)

    async def _fill_member(member: Mapping[str, Any]) -> dict[str, Any]:
        entity_id = str(member.get('entity_id') or '')
        licence_id = str(member.get('licence_id') or '').strip()
        licence_layer_id = str(member.get('licence_layer_id') or '').strip()
        object_name = '' if licence_id else str(member.get('object_name') or '').strip()
        if not object_name and not licence_id:
            return {
                'entity_id': entity_id,
                'state': NOT_ATTEMPTED,
                'reason': NO_OBJECT_NAME,
            }
        async with gate:
            if area_deadline_seconds is not None and clock() - started >= float(area_deadline_seconds):
                return {
                    'entity_id': entity_id,
                    'object_name': object_name or licence_id or entity_id,
                    'state': NOT_ATTEMPTED,
                    'reason': AREA_DEADLINE_REACHED,
                }
            try:
                counts['running'] += 1
                await report()
                started_run: dict[str, Any] = {}
                try:
                    outcome = await member_fill(
                        object_name=object_name,
                        project_id=str(member.get('project_id') or '') or None,
                        licence_id=licence_id or None,
                        licence_layer_id=licence_layer_id or None,
                        started_run=started_run,
                        area_member=True,
                        **arguments,
                    )
                except Exception as error:  # noqa: BLE001
                    failure: dict[str, Any] = {
                        'entity_id': entity_id,
                        'object_name': object_name or licence_id or entity_id,
                        'state': FAILED,
                        'error': f'{type(error).__name__}: {error}',
                    }
                    if started_run.get('run_id'):
                        failure['run_id'] = started_run['run_id']
                    return failure
            finally:
                counts['running'] -= 1
        return {
            'entity_id': entity_id,
            'object_name': object_name or licence_id or entity_id,
            'state': FILLED,
            'run_id': outcome.get('run_id'),
            'status': outcome.get('status'),
            'completeness': (outcome.get('audit') or {}).get('completeness'),
        }

    def _with_licence(
        member: Mapping[str, Any], outcome: dict[str, Any]
    ) -> dict[str, Any]:
        """The outcome with the requested member's `licence_id` stamped on it.

        The request's `licence_id` replaces any the outcome carries; an outcome is
        returned unchanged when the request carried none.
        """
        licence = str(member.get('licence_id') or '').strip()
        return {**outcome, 'licence_id': licence} if licence else outcome

    async def fill_member(member: Mapping[str, Any]) -> dict[str, Any]:
        """`_fill_member`, with its outcome counted and reported.

        An exception counts the member as `failed`, is reported, and is re-raised.
        """
        try:
            outcome = _with_licence(member, await _fill_member(member))
        except Exception:  # noqa: BLE001
            counts['failed'] += 1
            await report()
            raise
        settle(outcome)
        await report()
        return outcome

    await report()

    settled = await asyncio.gather(*(fill_member(member) for member in members), return_exceptions=True)
    results: list[dict[str, Any]] = []
    for member, outcome in zip(members, settled):
        if isinstance(outcome, BaseException) and not isinstance(outcome, Exception):
            raise outcome
        results.append(outcome if isinstance(outcome, dict) else _crashed(member, outcome))

    document: dict[str, Any] = {
        'schema_version': 1,
        'area_id': manifest.get('area_id'),
        'contract_resolution': manifest.get('contract_resolution'),
        'members': results,
        'counts': {
            'members': len(members),
            FILLED: sum(1 for item in results if item['state'] == FILLED),
            FAILED: sum(1 for item in results if item['state'] == FAILED),
            NOT_ATTEMPTED: sum(1 for item in results if item['state'] == NOT_ATTEMPTED),
        },
    }
    aggregation, folded = await _fold(
        fold_call=fold_call,
        policy_version=policy_version,
        dossier_run_id=dossier_run_id,
        manifest=manifest,
        results=results,
        project_id=project_id,
        calculation_crs=calculation_crs,
        area_display_name=area_display_name,
    )
    document['aggregation'] = aggregation
    if folded is not None:
        if folded.get('summary') is not None:
            document['summary'] = folded['summary']
        if folded.get('summary_markdown') is not None:
            document['summary_markdown'] = folded['summary_markdown']
        if folded.get('artifacts') is not None:
            document['artifacts'] = folded['artifacts']
        if folded.get('area_run_id') is not None:
            document['area_run_id'] = folded['area_run_id']
    if progress['failures'] or unaccounted:
        document['progress_line'] = {
            key: value
            for key, value in (
                ('attempts', progress['attempts']),
                ('failures', progress['failures']),
                ('error', progress.get('error')),
                ('unaccounted_states', list(unaccounted) or None),
            )
            if value is not None
        }
    return document


async def _fold(
    *,
    fold_call: FoldCall | None,
    policy_version: str | None,
    dossier_run_id: str | None,
    manifest: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    project_id: str | None = None,
    calculation_crs: str | None = None,
    area_display_name: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """`(aggregation, folded)`; `folded` is None unless a fold returned an aggregation.

    No fold is attempted without all of `fold_call`, `policy_version` and
    `dossier_run_id` (`fold_not_requested`, with the absent ones listed in
    `missing`), or when members exist and none is filled (`nothing_filled`). An
    exception from building or sending the fold, or an answer without
    `aggregation`, gives `fold_failed`. The manifest is always sent as `scope`, and
    a performed fold reports `link_guard: enforced`.
    """
    if fold_call is None or not policy_version or not dossier_run_id:
        missing = [
            name
            for name, value in (
                ('fold_call', fold_call),
                ('policy_version', policy_version),
                ('dossier_run_id', dossier_run_id),
            )
            if not value
        ]
        return {'state': NOT_PERFORMED, 'reason': FOLD_NOT_REQUESTED, 'missing': missing}, None

    if results and not any(item.get('state') == FILLED for item in results):
        return (
            {
                'state': NOT_PERFORMED,
                'reason': NOTHING_FILLED,
                'members_total': len(results),
                'members_filled': 0,
            },
            None,
        )

    try:
        payload = {
            'action': 'fold_area',
            'area_scope_id': str(manifest.get('area_id') or ''),
            'dossier_run_id': dossier_run_id,
            'policy_version': policy_version,
            'members': [_fold_member(item) for item in results],
            'scope': dict(manifest),
            'project_id': project_id,
            'calculation_crs': calculation_crs,
            'area_display_name': area_display_name,
        }
        folded = await fold_call(payload)
    except Exception as error:  # noqa: BLE001
        return (
            {
                'state': NOT_PERFORMED,
                'reason': FOLD_FAILED,
                'error': f'{type(error).__name__}: {error}',
            },
            None,
        )
    if not isinstance(folded, Mapping) or folded.get('aggregation') is None:
        return (
            {
                'state': NOT_PERFORMED,
                'reason': FOLD_FAILED,
                'error': 'the fold answered without an aggregation',
            },
            None,
        )
    return (
        {
            'state': PERFORMED,
            'policy_version': folded.get('policy_version'),
            'result': folded['aggregation'],
            'link_guard': 'enforced',
        },
        folded,
    )


def _fold_member(item: Mapping[str, Any]) -> dict[str, Any]:
    """One member as the fold request references it.

    Carries `entity_id`; `run_id` for a filled member with a run id, otherwise
    `unreached` translated through `_UNREACHED`; and `object_name` and
    `licence_id` when present.
    """
    member: dict[str, Any] = {'entity_id': str(item.get('entity_id') or '')}
    if item.get('state') == FILLED and item.get('run_id'):
        member['run_id'] = item['run_id']
    else:
        member['unreached'] = _UNREACHED.get(str(item.get('state')), 'member_not_attempted')
    if item.get('object_name'):
        member['object_name'] = item['object_name']
    if item.get('licence_id'):
        member['licence_id'] = item['licence_id']
    return member


def member_filler(
    *,
    fill: Callable[..., Awaitable[dict[str, Any]]],
    per_member: Mapping[str, Callable[[], Any]] | None = None,
    **injected: Any,
) -> MemberFill:
    """A `MemberFill` over the single-object workflow, with its effects bound.

    `injected` keyword arguments are passed to every member fill. `per_member`
    maps a keyword to a factory called once per member fill; an effect that must
    not be shared between members, such as `query_drain`, is supplied this way.
    A keyword passed at call time overrides both, and `object_name` and
    `project_id` always come from the member. The returned callable carries
    `per_member_keys`, which `run_geotizer_area_workflow` reads to reject
    colliding `member_arguments`.
    """

    async def call(*, object_name: str, project_id: str | None = None, **overrides: Any):
        arguments = dict(injected)
        for name, build in (per_member or {}).items():
            arguments[name] = build()
        arguments.update(overrides)
        arguments['object_name'] = object_name
        arguments['project_id'] = project_id
        return await fill(**arguments)

    call.per_member_keys = frozenset(per_member or ())
    return call
