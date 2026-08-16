"""The producer names are `gis_service`'s, and this is what happens when they move.

`PRODUCER_AGENT_KIND` maps four strings this repository does not own. They are
written in `assignment_policy.json` -- a hash-pinned contract asset under
`policy_version: geotizer_assignments.v1` -- and arrive as the `producer` field
of every batch and evidence route. The chain they sit in is
`assignment_policy.json -> producer -> PRODUCER_AGENT_KIND -> valves.GIS_MODEL`,
so the lookup decides which model serves a specialist call.

Two things follow, and they are the two halves of this file. The `_yulong`
suffix is contract vocabulary and renaming it here renames nothing upstream --
it only stops the match, which is why the table is asserted verbatim. And a
table this repository cannot keep in step with its source needs the inference
behind it, or the first producer the service adds ends a run at its first batch
having retrieved nothing.
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
    PRODUCER_AGENT_KIND,
    infer_agent_kind,
)
from open_webui.services.geotizer.errors import (  # noqa: E402
    GeotizerOrchestrationError,
)


def test_the_table_is_the_services_vocabulary_verbatim():
    """Every run in evidence names these four producers in `applied_batches`.

    Asserted as literals rather than derived from anything, because the point is
    that they cannot be derived: they are somebody else's strings, and a test
    that computed them from this repository would agree with itself while the
    contract moved.
    """
    assert PRODUCER_AGENT_KIND == {
        'GISagent_yulong': 'gis',
        'KBagent_yulong': 'kb',
        'WEBagent_yulong': 'web',
        'SkilledAgent': 'skilled',
    }


@pytest.mark.parametrize(
    ('producer', 'kind'),
    [
        ('GISagent_yulong', 'gis'),
        ('KBagent_yulong', 'kb'),
        ('WEBagent_yulong', 'web'),
        ('SkilledAgent', 'skilled'),
    ],
)
def test_the_mapped_producers_resolve_without_inference(producer, kind):
    assert agent_kind_for_producer(producer) == kind


@pytest.mark.parametrize(
    ('producer', 'kind'),
    [
        ('GISagent_v2', 'gis'),
        ('KB Agent', 'kb'),
        ('knowledge_specialist', 'kb'),
        ('WEBagent_someone_else', 'web'),
        ('Skilled Agent', 'skilled'),
    ],
)
def test_an_unmapped_producer_is_inferred_rather_than_fatal(producer, kind):
    """The fallback the deployed Tool has had all along.

    A strict lookup turns a rename anywhere upstream into a run that dies at its
    first batch, on a string, with nothing retrieved. Inferring costs a log line
    and the run continues.
    """
    assert agent_kind_for_producer(producer) == kind


def test_the_inference_reports_the_kind_it_found():
    assert infer_agent_kind('GISagent_yulong') == 'gis'
    assert infer_agent_kind('totally_unrelated') is None


def test_an_ambiguous_name_is_not_guessed():
    """Ambiguity is not a tie to be broken.

    A producer containing both 'kb' and 'web' could be either, and a guess
    routes a whole batch to the wrong model silently -- which is worse than the
    failure it avoids, because the run completes and the card looks filled.
    """
    assert infer_agent_kind('kb_web_hybrid') is None

    with pytest.raises(GeotizerOrchestrationError) as excinfo:
        agent_kind_for_producer('kb_web_hybrid')

    assert 'kb_web_hybrid' in str(excinfo.value)


def test_a_name_matching_nothing_still_raises():
    with pytest.raises(GeotizerOrchestrationError):
        agent_kind_for_producer('Пример')


def test_the_inference_reaches_the_route_producers_not_only_the_owner():
    """Routes carry their own producer, and it is a different string.

    `DATACUBE-EVIDENCE` names `DataCube Reviewer` and `OCR-INGEST` names
    `OCR pipeline` -- neither is in the table, and neither is inferable. A batch
    whose owner resolves cleanly can still fail on a route, so both paths
    through `build_batch_tasks` need the same treatment.
    """
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

    tasks = build_batch_tasks(batch)

    assert [task.kind for task in tasks] == ['gis', 'kb']
    assert [task.role for task in tasks] == ['contributor', 'owner']


def test_a_datacube_route_is_not_called_as_a_contributor():
    """`satisfied_by` is checked before the producer is, which is what keeps an
    unmappable name like `DataCube Reviewer` from ever reaching the lookup."""
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

    assert [task.producer for task in build_batch_tasks(batch)] == ['KBagent_yulong']
