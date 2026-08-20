"""What a dossier must contain before either artefact may be projected from it.

Both projections read the frozen dossier directly and neither checked it first.
A claim missing `value_origin` raised `KeyError: 'value_origin'` out of the
middle of the CPR coverage walk; a dossier missing `project_scope` raised
`KeyError: 'project_scope'` before the CPR had built a single row. Dozens of
fields behave that way -- some crash, and the rest are worse, because they change
the answer in silence: drop `state` from every claim and both projections return
a smaller, entirely well-formed result in which nothing is live. The exact set is
not restated here, because it is derived by `_removals` in
`test_project_evidence_dossier.py` and a number written in prose goes stale --
this one already did, at "twenty-one", which was the count over three of the
dossier's eleven array members.

The failure is not that the accesses are unguarded. Replacing them with `.get()`
would turn every one of those crashes into the silent case, which is the wrong
direction: a projection built from a dossier that is missing half its claims is
a document that looks finished and is not. The failure is that nothing said
"this is not a dossier" before the projection started.

So this is a precondition, checked once, naming everything that is wrong rather
than the first thing found -- an operator holding a bad export needs the list,
not a guided tour one `KeyError` at a time.

**One check, applied by both.** The dossier is artefact-independent: the CPR
document and the GeoTeaser workbook are two projections of the same evidence,
and the invariant that holds them together is that they never disagree. A
dossier that only one of them can read breaks that before either runs -- it
would produce a workbook and no CPR, which is divergence by another route. So
the requirement set here is the union of what both read, and `project_scope` is
required for the GeoTeaser projection too, even though GeoTeaser never looks at
it.

**What this is not.** It is a structural precondition, not a schema validator.
It checks that required fields are present and that array members are arrays.
It does not check types of leaf values, controlled vocabularies, formats, or
cross-references -- a claim whose `state` is `"banana"` passes here and is then
simply not live. GMM's `validate_evidence_dossier.py` is where a dossier is
validated; this is where a projection refuses to start on one that would crash
it. Reproducing the schema here would create a second contract to keep in step
with the first.

**Nothing here is invented.** Every field below is `required` in
`GMM/contracts/evidence/project-evidence-dossier.schema.json`, which owns the
contract; this restates the part of it the projections depend on, at the
boundary where its absence would otherwise be a stack trace.
`test_project_evidence_dossier.py` derives the set the other way, by mutation --
it drops each field and asserts that anything which crashes or changes the
answer is named here -- and cross-checks the lists against the schema itself
when a `GMM` checkout is present.

Optional fields are deliberately absent from the lists. `estimate_id`,
`missing_predicates`, `required_expert_action_id` and `supports_claim_ids` all
change the projection when removed, and all four are optional in the schema: a
claim with no estimate is a claim with no estimate, and projecting it differently
is correct. `OPTIONAL_BUT_LOAD_BEARING` in the test file argues each one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# `$.required` of the dossier schema, in full. The projections dereference nine
# of these; the rest are listed because the statement being made is "this is a
# Project Evidence Dossier", not "this happens to satisfy today's readers". A
# projection that starts reading `entities` tomorrow should not have to
# rediscover this.
DOSSIER_REQUIRED = (
    'assumptions',
    'claims',
    'conflicts',
    'dossier_run_id',
    'entities',
    'estimates',
    'expert_actions',
    'figures',
    'frozen_at',
    'frozen_inputs_hash',
    'gaps',
    'project_scope',
    'review_decisions',
    'schema_version',
    'sources',
    'state',
    'uncertainties',
)

# `$defs.evidenceClaim.required`.
CLAIM_REQUIRED = (
    'claim_id',
    'fact_kind',
    'predicate',
    'resolution_outcome',
    'source_locator',
    'source_refs',
    'state',
    'subject_entity_id',
    'temporal_scope',
    'value',
    'value_origin',
)

# `$defs.evidenceGap.required`.
GAP_REQUIRED = ('gap_id', 'if_not_why_not', 'missing_fact', 'subject_entity_id')

# `$defs.conflict.required`.
CONFLICT_REQUIRED = ('claim_ids', 'conflict_id', 'kind', 'resolution', 'statement')

# The nested objects the projections reach into. Each is `required` on its own
# `$def`, and each has already been the whole of a crash: `value_origin.kind` is
# read by the eligibility filter both projections share, `if_not_why_not.state`
# decides which of the three absences a gap is, and `project_scope.lifecycle_stage`
# selects the CPR requirement set.
VALUE_ORIGIN_REQUIRED = ('kind',)
IF_NOT_WHY_NOT_REQUIRED = ('reason', 'reason_kind', 'state')
PROJECT_SCOPE_REQUIRED = ('acl_decision', 'lifecycle_stage', 'project_id')

# Every array member of a dossier, and the fields each of its items must carry.
# `$defs.<name>.required` in each case, reached through
# `properties.<member>.items.$ref`.
#
# The first version of this module listed eleven member names for the
# array-shape check and then walked the items of only three of them -- claims,
# gaps and conflicts. That left the exact failure this module was written to
# close still open in the rest: `cpr/project.py` dereferences
# `estimate['estimate_id']` in `_matching_estimates` and `figure['figure_id']`
# in `_matching_figures`, so a malformed estimate or figure went past the
# precondition and came back out as a bare `KeyError` from inside a projection.
# (An earlier draft of this comment also blamed `_index()` for the same thing
# over sources and entities. `_index` is defined at `cpr/project.py:80` and
# called from nowhere -- the claim was wrong and the sweep below is what should
# have been trusted instead of the reading.)
#
# The mutation test missed all of it for the same reason it was written the way
# it was: it dropped whole top-level members and the keys of a claim, a gap and
# a conflict, and never malformed an item *inside* any other member.
#
# `state_transitions` is here despite being optional in the schema, so that
# "every array member" is true rather than nearly true; the walk skips a member
# that is absent, so listing it costs nothing and closes the one gap a reader
# would have to check by hand.
ITEM_REQUIRED = {
    'assumptions': ('affects_claim_ids', 'assumption_id', 'statement'),
    'claims': CLAIM_REQUIRED,
    'conflicts': CONFLICT_REQUIRED,
    'entities': ('entity_id', 'entity_type', 'name'),
    'estimates': (
        'author',
        'category',
        'commodity',
        'effective_date',
        'entity_id',
        'estimate_id',
        'estimate_kind',
        'method',
        'spatial_domain',
    ),
    'expert_actions': ('action_id', 'priority', 'reviewer_role', 'statement'),
    'figures': ('author', 'content_sha256', 'created_at', 'crs', 'figure_id', 'figure_kind'),
    'gaps': GAP_REQUIRED,
    'review_decisions': ('decided_at', 'decision', 'review_id', 'reviewer_role', 'subject_ids'),
    'state_transitions': ('at', 'cause', 'from_state', 'to_state'),
    'sources': (
        'acl_decision',
        'authority_kind',
        'project_id',
        'source_id',
        'source_version',
        'state',
    ),
    'uncertainties': ('claim_id', 'kind', 'statement', 'uncertainty_id'),
}

# The same names, as the array-shape check. `claims` arriving as a mapping is
# not a missing field and passes every `in` check above, then fails far away as
# `TypeError: string indices must be integers` -- which is how the same shape
# read in GMM's validator.
LIST_MEMBERS = tuple(sorted(ITEM_REQUIRED))

# The nested objects inside an item, by the member that holds them. Kept apart
# from `ITEM_REQUIRED` because these are one level deeper and each has already
# been the whole of a crash on its own.
NESTED_REQUIRED = {
    'claims': {'value_origin': VALUE_ORIGIN_REQUIRED},
    'gaps': {'if_not_why_not': IF_NOT_WHY_NOT_REQUIRED},
}


class DossierNotProjectable(ValueError):
    """The dossier cannot be projected, and `reasons` says why -- all of it.

    Not a `GeotizerOrchestrationError`: this is raised on the way into the CPR
    projection as often as the GeoTeaser one, and an artefact's error type on an
    artefact-neutral failure would be a small lie about where the fault is.
    """

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(reasons)
        count = len(self.reasons)
        super().__init__(
            f'dossier cannot be projected ({count} problem{"" if count == 1 else "s"}): '
            + '; '.join(self.reasons)
        )


def _missing(where: str, item: Any, required: Sequence[str]) -> list[str]:
    if not isinstance(item, Mapping):
        return [f'{where} must be an object, got {type(item).__name__}']
    return [f'{where}.{name} is required' for name in required if name not in item]


def projection_preconditions(dossier: Any) -> tuple[str, ...]:
    """Everything that stops this dossier being projected, in one pass.

    Returns reasons rather than raising, so a caller that wants to report and
    continue -- a batch validator over many exports, say -- is not forced to use
    exceptions for control flow. `require_projectable` is the raising form.
    """
    if not isinstance(dossier, Mapping):
        return (f'dossier must be an object, got {type(dossier).__name__}',)

    reasons = _missing('dossier', dossier, DOSSIER_REQUIRED)

    wrong_type = set()
    for name in LIST_MEMBERS:
        value = dossier.get(name)
        if name in dossier and not isinstance(value, list):
            reasons.append(f'dossier.{name} must be an array, got {type(value).__name__}')
            wrong_type.add(name)

    scope = dossier.get('project_scope')
    if 'project_scope' in dossier:
        reasons.extend(_missing('dossier.project_scope', scope, PROJECT_SCOPE_REQUIRED))

    # Every member, not a chosen three. Items are reported by position rather
    # than by id: an item missing its id cannot be named, and that is exactly the
    # item most likely to be missing other things too.
    for member in LIST_MEMBERS:
        if member in wrong_type:
            # Enumerating a mapping given as `claims` yields its keys, and every
            # key is then reported as a claim that is not an object. Three
            # reasons for one fault reads as three faults.
            continue
        nested = NESTED_REQUIRED.get(member, {})
        for index, item in enumerate(dossier.get(member) or ()):
            where = f'dossier.{member}[{index}]'
            reasons.extend(_missing(where, item, ITEM_REQUIRED[member]))
            if not isinstance(item, Mapping):
                continue
            for name, required in nested.items():
                if name in item:
                    reasons.extend(_missing(f'{where}.{name}', item[name], required))

    return tuple(reasons)


def require_projectable(dossier: Any) -> None:
    """Raise `DossierNotProjectable` unless both artefacts can read this dossier."""
    reasons = projection_preconditions(dossier)
    if reasons:
        raise DossierNotProjectable(reasons)


__all__ = [
    'CLAIM_REQUIRED',
    'CONFLICT_REQUIRED',
    'DOSSIER_REQUIRED',
    'DossierNotProjectable',
    'GAP_REQUIRED',
    'IF_NOT_WHY_NOT_REQUIRED',
    'ITEM_REQUIRED',
    'LIST_MEMBERS',
    'NESTED_REQUIRED',
    'PROJECT_SCOPE_REQUIRED',
    'VALUE_ORIGIN_REQUIRED',
    'projection_preconditions',
    'require_projectable',
]
