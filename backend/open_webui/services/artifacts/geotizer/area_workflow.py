"""An area fill is the object fill run per member, and nothing new per member.

`geotizer_area_scope` resolves an area into members with a hierarchy between
them. Filling one is a separate question, and this module is the composition
that answers it — deliberately *not* a mode inside `run_geotizer_workflow`.

**Why composition and not `if area:`.** The single-object path is the measured
one: four clean runs of one build filled 207, 191, 219 and 137 of 351 cells, and
three pairs since have measured status agreement at 202, 183 and 193. Every
refusal in that path is tuned against that behaviour. A branch inside it puts
the measured path one step from an unmeasured one and makes the band describe
«a run in one of two modes», with the second mode instrumented by nothing.

The inventory behind this split is
`GMM/operations/design/2026-09-04__what-in-the-fill-assumes-one-object.md`. Its
short form: identity, the batch loop, the owner calls, carry-forward and every
run-level record are already per object and are reused untouched. Four things
assume there is only one — the object-scope binding over four cells, the licence
polygon as source geometry, the envelope's expected object name, and the 351-cell
`completeness` denominator — and this module supplies its own for the first
three and refuses the fourth.

**It does not aggregate, and the absence is a value.** GTA-04 stays held: the
operators over the 351 fields are undecided, and 202 of 351 cells are a draw
across four runs of one build. Summing quantities that appear in two runs of
four, over twenty-one objects, produces a total whose variance nobody can
bound. So the result carries `aggregation` with a state and a reason rather
than a missing key or a zero — the same discipline as the four band states and
the four absence codes.

`link_status` is UNENFORCED and recorded as such in the dossier contract. A
`candidate` link must not enter a sum, and the component that would refuse one
is the aggregator, which does not exist. Nothing today enforces the
double-count guard, and this module says so rather than letting a later reader
infer from `link_status`'s presence that it works.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, Awaitable, Callable

#: The single-object fill, injected rather than imported, for the same reason
#: `gis_call` is: this module composes an effect and performs none. It also
#: makes the composition testable without a GIS service, which is what lets the
#: ordering and the refusals be checked at all.
MemberFill = Callable[..., Awaitable[dict[str, Any]]]

NOT_PERFORMED = 'not_performed'
AGGREGATOR_HELD = 'aggregator_held_pending_operators_and_variance'

#: Terminal states a member fill can end in, as this module distinguishes them.
#: `failed` is not `blocked`: one is an exception that escaped and the other is
#: a run that finished and refused to publish.
FILLED = 'filled'
FAILED = 'failed'
NOT_ATTEMPTED = 'not_attempted'

#: Why a member was never attempted. An unattempted member with no reason is
#: indistinguishable from one that was attempted and produced nothing.
NO_OBJECT_NAME = 'member_has_no_object_name'
AREA_DEADLINE_REACHED = 'area_deadline_reached'


def _member_order(members: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The order members are filled in, named rather than inherited.

    It matters as soon as anything stops the run part-way: whichever members
    come last are the ones that do not get filled. Sorting by `rank` and then
    by `entity_id` makes that deterministic and re-runnable; dictionary order
    would make it an accident of how the manifest was built.

    Rank first because a parent that fails is more informative than a child
    that fails — if the area's root cannot be filled, the run has a different
    problem from a single member missing.
    """
    return sorted(
        members,
        key=lambda member: (int(member.get('rank') or 0), str(member.get('entity_id') or '')),
    )


async def run_geotizer_area_workflow(
    *,
    manifest: Mapping[str, Any],
    member_fill: MemberFill,
    member_arguments: Mapping[str, Any] | None = None,
    area_deadline_seconds: float | None = None,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Fill every member of a resolved area, and refuse to roll the answers up.

    `manifest` is an `AreaScopeManifest` as `geotizer_area_scope` returns it.
    `member_fill` is `run_geotizer_workflow`, unchanged: this module passes each
    member's `object_name` and `project_id` and nothing else about the area, so
    a member fill is indistinguishable from a single-object fill of that member.

    `area_deadline_seconds` bounds the *area*, not a member. A member keeps its
    own deadline, which the object path already has; without an area-level one,
    twenty-one members can spend twenty-one member deadlines. When it expires
    the remaining members are recorded as `not_attempted` with the reason,
    because a member absent from the result reads as a member that succeeded and
    returned nothing.
    """
    clock = clock or asyncio.get_event_loop().time
    started = clock()
    members = _member_order(list(manifest.get('members') or []))
    arguments = dict(member_arguments or {})

    results: list[dict[str, Any]] = []
    for member in members:
        entity_id = str(member.get('entity_id') or '')
        object_name = str(member.get('object_name') or '').strip()
        if not object_name:
            # A member the dossier knows by id and the fill cannot name. Not an
            # error for the area: it is one member that cannot be filled, and
            # the area says which and why.
            results.append(
                {
                    'entity_id': entity_id,
                    'state': NOT_ATTEMPTED,
                    'reason': NO_OBJECT_NAME,
                }
            )
            continue
        if (
            area_deadline_seconds is not None
            and clock() - started >= float(area_deadline_seconds)
        ):
            results.append(
                {
                    'entity_id': entity_id,
                    'object_name': object_name,
                    'state': NOT_ATTEMPTED,
                    'reason': AREA_DEADLINE_REACHED,
                }
            )
            continue
        try:
            outcome = await member_fill(
                object_name=object_name,
                project_id=str(member.get('project_id') or '') or None,
                **arguments,
            )
        except Exception as error:  # noqa: BLE001 - one member, not the area
            # One member's failure is not the area's. The object path already
            # hands back a `run_id` so a failed fill stays resumable; losing it
            # here would cost more than the failure did.
            results.append(
                {
                    'entity_id': entity_id,
                    'object_name': object_name,
                    'state': FAILED,
                    'error': f'{type(error).__name__}: {error}',
                }
            )
            continue
        results.append(
            {
                'entity_id': entity_id,
                'object_name': object_name,
                'state': FILLED,
                'run_id': outcome.get('run_id'),
                'status': outcome.get('status'),
                # The member's own completeness, unaltered. There is no area
                # completeness here and there must not appear to be one.
                'completeness': (outcome.get('audit') or {}).get('completeness'),
            }
        )

    return {
        'schema_version': 1,
        'area_id': manifest.get('area_id'),
        'members': results,
        'counts': {
            'members': len(members),
            FILLED: sum(1 for item in results if item['state'] == FILLED),
            FAILED: sum(1 for item in results if item['state'] == FAILED),
            NOT_ATTEMPTED: sum(1 for item in results if item['state'] == NOT_ATTEMPTED),
        },
        # A state and a reason, never a missing key and never a zero. GTA-04 is
        # held on two grounds that have not moved: the 351 operators are
        # undecided, and 202 of 351 cells are a draw across four runs of one
        # build.
        'aggregation': {
            'state': NOT_PERFORMED,
            'reason': AGGREGATOR_HELD,
            'double_count_guard': 'unenforced',
            'double_count_guard_note': (
                '`link_status` is UNENFORCED in the dossier contract. A '
                '`candidate` link must not enter a sum, and the component that '
                'would refuse one is the aggregator, which does not exist.'
            ),
        },
    }
