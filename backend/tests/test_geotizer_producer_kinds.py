"""The producer names are `gis_service`'s, and this is how they get configured.

They are written in `assignment_policy.json` -- a hash-pinned contract asset
under `policy_version: geotizer_assignments.v1` -- and arrive as the `producer`
field of every batch and evidence route. The chain they sit in is
`assignment_policy.json -> producer -> PRODUCER_KIND_MAP -> valves.GIS_MODEL`,
so the lookup decides which model serves a specialist call.

The middle link used to be a four-entry table compiled into `core/tasks.py`,
with a name-sniffing fallback behind it. Both are gone. A table of somebody
else's strings is a copy that goes stale on the day they rename one, and it goes
stale silently; the fallback made that worse rather than better, because a
producer named conventionally enough to be guessed routed a whole batch on the
guess and said nothing. It is a valve on `multitask_orchestration` now, next to
the four model valves it feeds, and this repository ships no default for it.

Which makes strictness the whole design, and these are its four edges: the valve
parses or it fails at parse; a mapped producer resolves; an unmapped one aborts
the run with a message an operator can act on; and an empty map -- the shipped
state -- fails closed rather than open. Every call below passes the map
explicitly, because there is no default to fall back on and a test that relied
on one would be testing a fallback this file exists to say does not exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_webui.services.artifacts.geotizer.owner_envelope import (  # noqa: E402
    agent_kind_for_producer,
    build_batch_tasks,
)
from open_webui.services.core.tasks import (  # noqa: E402
    AGENT_KINDS,
    parse_producer_kind_map,
)
from open_webui.services.geotizer.errors import (  # noqa: E402
    GeotizerOrchestrationError,
)

# What an operator types into the valve on a contour talking to today's service.
# Written out here rather than imported from anywhere, because the point is that
# no module holds it: it is configuration, and a test that derived it from this
# repository would agree with itself while the contract moved.
DEPLOYED_VALVE = 'GISagent_yulong=gis,KBagent_yulong=kb,WEBagent_yulong=web,SkilledAgent=skilled'


# -- parsing ---------------------------------------------------------------


def test_the_deployed_valve_parses_to_the_four_routes_it_names():
    assert parse_producer_kind_map(DEPLOYED_VALVE) == {
        'GISagent_yulong': 'gis',
        'KBagent_yulong': 'kb',
        'WEBagent_yulong': 'web',
        'SkilledAgent': 'skilled',
    }


def test_the_valve_holds_whatever_names_the_service_sends():
    """No part of the format assumes the four names above.

    That is the property the table did not have: a service that renames a
    producer, adds a fifth, or spells one in Cyrillic is a Workspace edit, not a
    redeploy of this repository.
    """
    parsed = parse_producer_kind_map('ГИСагент=gis,kb-specialist-v4=kb,Assemble=skilled')

    assert parsed == {'ГИСагент': 'gis', 'kb-specialist-v4': 'kb', 'Assemble': 'skilled'}


def test_spacing_around_the_separators_is_not_a_configuration_error():
    """A valve is a text field a human types into. Leading spaces after a comma
    are not a misconfiguration and refusing them would train operators to
    distrust the parser on the errors that matter."""
    assert parse_producer_kind_map(' GISagent_yulong = gis , KBagent_yulong = kb ,') == {
        'GISagent_yulong': 'gis',
        'KBagent_yulong': 'kb',
    }


def test_an_empty_valve_parses_to_an_empty_map_rather_than_raising():
    """The shipped state. It is not a parse error -- there is nothing malformed
    in it -- and turning it into one here would report "the valve is broken"
    when the truth is "nobody has configured this contour yet"."""
    assert parse_producer_kind_map('') == {}
    assert parse_producer_kind_map('   ') == {}


@pytest.mark.parametrize(
    'raw',
    [
        'GISagent_yulong',
        'GISagent_yulong=gis,KBagent_yulong',
        '=gis',
        'GISagent_yulong=',
    ],
)
def test_an_entry_that_is_not_producer_equals_kind_fails_at_parse(raw):
    """Loudly, and at read time.

    The alternative is not "no error" -- it is the same error at the fortieth
    batch of a run that has already spent thirty-nine specialist calls, because
    a dropped entry is only visible when a batch carrying that producer arrives.
    """
    with pytest.raises(GeotizerOrchestrationError) as excinfo:
        parse_producer_kind_map(raw)

    assert 'PRODUCER_KIND_MAP' in str(excinfo.value)


def test_a_kind_outside_the_four_fails_at_parse_and_names_the_four():
    """`gis|kb|web|skilled` are the agent kinds `run_agent_task` accepts. A typo
    reaches the orchestrator as an unknown agent and resolves to the skilled
    model by its `.get(agent, SKILLED_MODEL)` default -- a wrong model with no
    error anywhere, which is the failure mode this whole change is about."""
    with pytest.raises(GeotizerOrchestrationError) as excinfo:
        parse_producer_kind_map('KBagent_yulong=knowledge')

    message = str(excinfo.value)
    assert 'knowledge' in message
    for kind in sorted(AGENT_KINDS):
        assert kind in message


def test_the_same_producer_twice_fails_even_when_both_sides_agree():
    """Two entries for one producer are indistinguishable from a half-finished
    edit, and whichever wins is decided by position in a text field. Rejecting
    the agreeing case too is the point: it is the one an operator would leave in
    place, and the disagreeing case is the same edit a keystroke later."""
    with pytest.raises(GeotizerOrchestrationError) as excinfo:
        parse_producer_kind_map('KBagent_yulong=kb,KBagent_yulong=kb')

    assert 'twice' in str(excinfo.value)

    with pytest.raises(GeotizerOrchestrationError) as excinfo:
        parse_producer_kind_map('KBagent_yulong=kb,KBagent_yulong=web')

    assert "'kb'" in str(excinfo.value) and "'web'" in str(excinfo.value)


# -- lookup ----------------------------------------------------------------


@pytest.mark.parametrize(
    ('producer', 'kind'),
    [
        ('GISagent_yulong', 'gis'),
        ('KBagent_yulong', 'kb'),
        ('WEBagent_yulong', 'web'),
        ('SkilledAgent', 'skilled'),
    ],
)
def test_a_configured_producer_resolves_to_its_kind(producer, kind):
    assert agent_kind_for_producer(producer, parse_producer_kind_map(DEPLOYED_VALVE)) == kind


def test_an_unmapped_producer_is_fatal_and_the_message_says_what_to_do():
    """`GeotizerOrchestrationError` is a `ValueError` and nothing between
    `build_batch_tasks` and `fill_geotizer` catches it, so this ends the run at
    its first batch. That is intended -- a guess spends a specialist call and
    fills a card with provenance nobody can trace afterwards -- which makes the
    message the only thing standing between an operator and a dead contour. It
    has to carry the producer that arrived, what is configured now, and where to
    put the fix.
    """
    mapping = parse_producer_kind_map(DEPLOYED_VALVE)

    with pytest.raises(GeotizerOrchestrationError) as excinfo:
        agent_kind_for_producer('GISagent_v2', mapping)

    message = str(excinfo.value)
    assert 'GISagent_v2' in message
    assert 'KBagent_yulong' in message, 'the configured keys are not shown'
    assert 'PRODUCER_KIND_MAP' in message
    assert 'multitask_orchestration' in message


@pytest.mark.parametrize('producer', ['GISagent_v2', 'KB Agent', 'knowledge_specialist', 'Skilled Agent'])
def test_a_conventionally_named_producer_is_still_not_guessed(producer):
    """The fallback that stood here for one round, stated as its inverse.

    `infer_agent_kind` read the kind out of the producer's spelling, so all four
    of these resolved without being configured. That is precisely the harm: an
    unconfigured contour whose producers happen to be named the expected way
    runs green while routing every batch on an assumption about somebody else's
    naming convention, and nothing in the run says so. It is not coming back.
    """
    with pytest.raises(GeotizerOrchestrationError):
        agent_kind_for_producer(producer, parse_producer_kind_map(DEPLOYED_VALVE))


def test_an_empty_map_fails_closed_on_the_very_first_producer():
    """The repository default, exercised as the deployment state it is.

    An unconfigured contour must not run. It must stop on its first batch and
    say the map is empty, so the failure is one Workspace edit from fixed rather
    than 351 fields of wrong-model output that looks like a bad retrieval day.
    """
    with pytest.raises(GeotizerOrchestrationError) as excinfo:
        agent_kind_for_producer('KBagent_yulong', parse_producer_kind_map(''))

    message = str(excinfo.value)
    assert 'KBagent_yulong' in message
    assert '(none)' in message, 'an empty map must say it is empty, not print []'


# -- the two production callers -------------------------------------------


def test_both_the_routes_and_the_owner_are_resolved_through_the_same_map():
    """Routes carry their own producer, and it is a different string from the
    owner's. A batch whose owner resolves cleanly can still fail on a route, so
    both paths through `build_batch_tasks` take the valve."""
    batch = {
        'batch_id': 'KB-GEO',
        'producer': 'KBagent_yulong',
        'evidence_routes': [
            {
                'route_id': 'GIS-EVIDENCE',
                'producer': 'GISagent_yulong',
                'satisfied_by': 'contributor_call',
            },
        ],
    }

    tasks = build_batch_tasks(batch, producer_kind_map=parse_producer_kind_map(DEPLOYED_VALVE))

    assert [task.kind for task in tasks] == ['gis', 'kb']
    assert [task.role for task in tasks] == ['contributor', 'owner']


def test_an_unmapped_route_producer_stops_the_batch_even_when_the_owner_resolves():
    batch = {
        'batch_id': 'KB-GEO',
        'producer': 'KBagent_yulong',
        'evidence_routes': [
            {
                'route_id': 'GIS-EVIDENCE',
                'producer': 'GISagent_v2',
                'satisfied_by': 'contributor_call',
            },
        ],
    }

    with pytest.raises(GeotizerOrchestrationError, match='GISagent_v2'):
        build_batch_tasks(batch, producer_kind_map=parse_producer_kind_map(DEPLOYED_VALVE))


def test_the_map_is_required_with_no_default_to_fall_back_on():
    """A default would be the routing table growing a second home in the one
    place nobody configures. An empty default would be worse: a caller that
    forgot to thread the valve through would be indistinguishable from a contour
    nobody has configured, and both would abort with the same message."""
    with pytest.raises(TypeError):
        build_batch_tasks({'batch_id': 'KB-GEO', 'producer': 'KBagent_yulong'})


def test_a_datacube_route_is_not_called_as_a_contributor():
    """`satisfied_by` is checked before the producer is, which is what keeps an
    unmappable name like `DataCube Reviewer` -- a route the GIS service answers
    itself and no valve should ever have to name -- from reaching the lookup."""
    batch = {
        'batch_id': 'KB-GEO',
        'producer': 'KBagent_yulong',
        'evidence_routes': [
            {
                'route_id': 'DATACUBE-EVIDENCE',
                'producer': 'DataCube Reviewer',
                'satisfied_by': 'start.datacube',
            },
        ],
    }

    tasks = build_batch_tasks(batch, producer_kind_map=parse_producer_kind_map(DEPLOYED_VALVE))

    assert [task.producer for task in tasks] == ['KBagent_yulong']
