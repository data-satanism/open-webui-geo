"""The run-level failure and the cell-level damage, finally joined.

Run `6d6c11f1`: 184 of 351 cells sat in a chunk whose contributor burned its
whole budget and returned nothing, **82 of them `filled`** — handed to a
geologist as answers, none carrying a marker. `specialist_round_failures` knew;
the cells did not; and the only join anyone could make was a
`<batch>__part_<n>__` prefix mined off a `source_refs` string.

Two things close it. `chunk_marker` gives the chunk one wire shape instead of
two. `stamp_chunk_provenance` puts that chunk, and the contributors that
answered nothing for it, on every patch the chunk produced.

The rule the whole design rests on is that neither refuses anything:
`AStampIsNotARefusal`. The owner had other contributors and its answer may be
sound — «one source was missing» is a different claim from «this is wrong», and
82 cells depend on the difference being kept.
"""

from __future__ import annotations

import pytest

from open_webui.services.artifacts.geotizer.owner_envelope import (
    SpecialistRoundLog,
    chunk_marker,
    specialist_round_record,
    stamp_chunk_provenance,
)


def envelope(patches=None, *, batch_id='KB-STUDY'):
    return {
        'run_id': 'r', 'batch_id': batch_id, 'producer': 'kb',
        'policy_version': 'v', 'template_version': 't',
        'source_inventory': [],
        'patches': patches if patches is not None else [
            {'field_key': 'a', 'status': 'filled', 'value': '120'},
            {'field_key': 'b', 'status': 'not_found', 'value': None},
        ],
    }


class TestOneShapeForAChunk:
    """§5. `{'index': 3, 'total': 4}` in a failure record, `'3/4'` in a
    locator. A reader written against one read 35 records, placed none, and
    reported «neither run recorded a failed round»."""

    def test_the_mapping_shape_a_failure_record_carries(self):
        assert chunk_marker({'index': 3, 'total': 4}) == {'index': 3, 'total': 4}

    def test_the_string_shape_a_locator_carries(self):
        assert chunk_marker('3/4') == {'index': 3, 'total': 4}

    def test_the_two_shapes_agree(self):
        assert chunk_marker('3/4') == chunk_marker({'index': 3, 'total': 4})

    def test_a_bare_index_has_no_known_total(self):
        assert chunk_marker(5) == {'index': 5}

    def test_a_boolean_is_not_chunk_one(self):
        assert chunk_marker(True) is None
        assert chunk_marker({'index': True, 'total': 2}) is None

    @pytest.mark.parametrize('value', [None, '', {}, [], 'three', {'total': 4}, '3/', 'a/b'])
    def test_an_unusable_marker_is_none_rather_than_a_guess(self, value):
        assert chunk_marker(value) is None

    def test_the_batch_is_carried_when_known(self):
        assert chunk_marker('1/2', batch_id='KB-GEO') == {
            'index': 1, 'total': 2, 'batch_id': 'KB-GEO',
        }

    def test_a_marker_naming_its_own_batch_keeps_it(self):
        marker = chunk_marker({'index': 1, 'batch_id': 'GIS-DC'}, batch_id='KB-GEO')
        assert marker['batch_id'] == 'GIS-DC'


class TestTheStampReachesEveryCellOfTheChunk:
    def test_the_chunk_lands_on_every_patch(self):
        stamped = stamp_chunk_provenance(envelope(), chunk={'index': 2, 'total': 5})

        assert all(p['owner_chunk']['index'] == 2 for p in stamped['patches'])
        assert all(p['owner_chunk']['batch_id'] == 'KB-STUDY' for p in stamped['patches'])

    def test_the_missing_contributors_land_on_every_patch(self):
        stamped = stamp_chunk_provenance(
            envelope(), chunk=2,
            failures=[{'agent': 'kb', 'code': 'empty_completion'}],
        )

        assert all(
            p['evidence_incomplete'] == [{'agent': 'kb', 'code': 'empty_completion'}]
            for p in stamped['patches']
        )

    def test_a_chunk_that_lost_nothing_carries_no_marker(self):
        """The marker has to be rare enough to mean something. A card that
        warns on every cell has warned on none."""
        stamped = stamp_chunk_provenance(envelope(), chunk=1)

        assert all('evidence_incomplete' not in p for p in stamped['patches'])
        assert all('owner_chunk' in p for p in stamped['patches'])

    def test_the_order_is_stable_so_two_runs_compare(self):
        """The spread is measured by diffing two states; a marker that
        reordered itself would read as a difference where none exists."""
        one = stamp_chunk_provenance(envelope(), chunk=1, failures=[
            {'agent': 'web', 'code': 'empty_completion'},
            {'agent': 'gis', 'code': 'upstream_error'},
        ])
        other = stamp_chunk_provenance(envelope(), chunk=1, failures=[
            {'agent': 'gis', 'code': 'upstream_error'},
            {'agent': 'web', 'code': 'empty_completion'},
        ])

        assert one['patches'] == other['patches']

    def test_a_repeated_failure_is_recorded_once(self):
        stamped = stamp_chunk_provenance(envelope(), chunk=1, failures=[
            {'agent': 'kb', 'code': 'empty_completion'},
            {'agent': 'kb', 'code': 'empty_completion'},
        ])

        assert len(stamped['patches'][0]['evidence_incomplete']) == 1

    def test_an_envelope_with_no_chunk_and_no_failures_is_untouched(self):
        source = envelope()
        assert stamp_chunk_provenance(source, chunk=None)['patches'] == source['patches']

    def test_the_original_envelope_is_not_mutated(self):
        """The envelope is threaded through a dozen rules that each return a
        new one. A pass that edited in place would have the rules above it
        seeing a value written after they ran."""
        source = envelope()
        stamp_chunk_provenance(source, chunk=1, failures=[{'agent': 'kb', 'code': 'x'}])

        assert 'owner_chunk' not in source['patches'][0]

    def test_a_malformed_patch_list_is_returned_rather_than_crashed_on(self):
        assert stamp_chunk_provenance({'patches': 'not a list'}, chunk=1)['patches'] == 'not a list'


# --- A stamp is not a refusal.


def test_a_filled_cell_keeps_its_value_and_its_status():
    """82 cells depend on this. The owner had other contributors; the claim is
    «one source was missing», not «this is wrong»."""
    stamped = stamp_chunk_provenance(
        envelope(), chunk=1, failures=[{'agent': 'kb', 'code': 'empty_completion'}],
    )
    filled = stamped['patches'][0]

    assert filled['status'] == 'filled'
    assert filled['value'] == '120'
    assert filled['evidence_incomplete']


def test_a_not_found_cell_is_marked_too():
    """«Searched and empty» and «the contributor never reported» read
    identically without this, and they are different claims."""
    stamped = stamp_chunk_provenance(
        envelope(), chunk=1, failures=[{'agent': 'gis', 'code': 'empty_completion'}],
    )
    not_found = stamped['patches'][1]

    assert not_found['status'] == 'not_found'
    assert not_found['evidence_incomplete']


class TestTheLogAnswersPerChunk:
    #: Transcribed from `16c65331`'s first `specialist_round_failures` entry,
    #: minus the prose of `detail`. The artefact, not the writer's signature.
    DELIVERED = {
        'agent': 'kb', 'batch_id': 'GIS-DC', 'chunk': {'index': 2, 'total': 2},
        'code': 'empty_completion', 'reasoning_only': False, 'retryable': True,
        'role': 'contributor',
        'usage': {'completion_tokens': 16384, 'finish_reason': 'length',
                  'prompt_tokens': 17862, 'total_tokens': 34246},
    }

    def test_a_delivered_record_is_placed_on_its_chunk(self):
        log = SpecialistRoundLog()
        log.add(self.DELIVERED)

        assert log.failures_for('GIS-DC', 2) == [
            {'agent': 'kb', 'code': 'empty_completion'},
        ]

    def test_another_chunk_of_the_same_batch_is_unaffected(self):
        log = SpecialistRoundLog()
        log.add(self.DELIVERED)

        assert log.failures_for('GIS-DC', 1) == []

    def test_the_index_is_uncapped_so_a_long_run_still_marks_its_cells(self):
        """The A-186 shape, one level in. The kept list is bounded because a
        person reads it; the index is not, because a dropped record would
        silently un-mark the cells whose evidence never arrived."""
        log = SpecialistRoundLog(cap=1)
        for index in range(1, 21):
            log.add(specialist_round_record(
                {'agent': 'kb', 'code': 'empty_completion'},
                role='contributor', batch_id='KB-STUDY',
                chunk={'index': index, 'total': 20},
            ))

        assert len(log.records) == 1
        assert log.stats()['dropped'] == 19
        # Every chunk still answers, including ones the list never kept.
        assert log.failures_for('KB-STUDY', 20) == [
            {'agent': 'kb', 'code': 'empty_completion'},
        ]

    def test_a_record_naming_no_chunk_is_not_placed_on_chunk_one(self):
        log = SpecialistRoundLog()
        log.add({'agent': 'kb', 'code': 'empty_completion', 'batch_id': 'KB-GEO'})

        assert log.failures_for('KB-GEO', 1) == []

    def test_duplicates_within_a_chunk_collapse(self):
        log = SpecialistRoundLog()
        for _ in range(3):
            log.add(dict(self.DELIVERED))

        assert len(log.failures_for('GIS-DC', 2)) == 1


# --- The other way out of the attempt loop. Every case above stamps through
# the success return, which was the only place wired to `_stamped_with_chunk_
# provenance`. An owner that never satisfies the contract leaves through
# `owner_failure_envelope`, and `_salvage_owner_candidates` promotes valid
# per-field patches out of candidates appended before any stamping -- so a
# salvaged `filled` cell shipped with neither field. That is the path most
# likely to coincide with a burn: a chunk whose contributor returned nothing is
# a plausible reason the owner cannot pass the contract three times running.

import asyncio  # noqa: E402

from open_webui.services.artifacts.geotizer.owner_envelope import (  # noqa: E402
    build_batch_tasks,
)
from open_webui.services.artifacts.geotizer.workflow import (  # noqa: E402
    _produce_valid_owner_envelope,
)

from test_geotizer_orchestration import batch  # noqa: E402


class TestTheFailurePathStampsToo:
    CHUNK = {'index': 2, 'total': 2}

    def failed_run(self, log=None):
        """Three empty owner attempts, so the loop returns the fallback."""
        value = {**batch(), 'owner_chunk': dict(self.CHUNK)}

        async def agent_call(task, prompt, object_name, datacube):
            return ''

        owner = next(t for t in build_batch_tasks(value) if t.role == 'owner')
        return asyncio.run(
            _produce_valid_owner_envelope(
                owner=owner,
                context={
                    'batch': value,
                    'contributor_evidence': [],
                    'accepted_field_summary': [],
                },
                next_batch=value,
                object_name='Лекын-Талбейская площадь',
                run_id='run-failure-path',
                agent_call=agent_call,
                datacube=None,
                specialist_round_log=log,
            )
        )

    def test_the_chunk_reaches_the_cells_the_owner_never_produced(self):
        result = self.failed_run()

        assert result['patches']
        assert all(
            patch['owner_chunk']['index'] == 2 for patch in result['patches']
        )

    def test_the_contributor_that_returned_nothing_reaches_them_too(self):
        log = SpecialistRoundLog()
        log.add({
            'agent': 'kb',
            'batch_id': batch()['batch_id'],
            'chunk': dict(self.CHUNK),
            'code': 'empty_completion',
            'role': 'contributor',
        })

        result = self.failed_run(log)

        assert result['patches']
        assert all(
            {'agent': 'kb', 'code': 'empty_completion'}
            in patch['evidence_incomplete']
            for patch in result['patches']
        )
