"""Making the chunk-size question answerable, and refusing the arm that lies.

The five chunks that failed run `6056e157` are the population the chunk-size
question needs, and the comparison could not be run: the value was a module
constant, the valve lives in the retired monolith, and the deployed shim
exposes no budgets. An operator could not vary it without editing code and
redeploying between arms.

`GEOMAS_OWNER_FIELDS_PER_CALL` makes 18 and 12 runnable. It refuses 8, and the
refusal is the point rather than an obstruction -- see below.
"""

from __future__ import annotations

import pytest
from open_webui.services.artifacts.geotizer.workflow import (
    MAX_OWNER_FIELDS_PER_CALL,
    OWNER_ROW_WIDTH,
    resolve_owner_fields_per_call,
)


@pytest.mark.parametrize('requested', [None, ''])
def test_an_unset_value_leaves_the_default_and_says_nothing(requested):
    """An untouched contour must be unchanged, and must not gain a run note
    saying so -- a note on every card is a note nobody reads."""
    assert resolve_owner_fields_per_call(requested) == (MAX_OWNER_FIELDS_PER_CALL, None)


@pytest.mark.parametrize('requested', [12, '12', 18, 6, 24])
def test_a_size_that_divides_the_row_is_taken(requested):
    size, note = resolve_owner_fields_per_call(requested)

    assert size == int(requested)
    assert note is None


def test_a_size_that_would_split_a_resource_row_is_refused():
    """8 is the value the question most wants to try, and it is the one that
    cannot be measured honestly.

    A resource row is six contiguous fields and
    `_resource_row_consistency_violations` only sees the patches inside one
    chunk, so at 8 a row straddles a boundary and the rule that stops one row
    reporting two different deposits stops running. That arm would report
    fewer contract failures for the wrong reason.
    """
    size, note = resolve_owner_fields_per_call(8)

    assert size == MAX_OWNER_FIELDS_PER_CALL
    assert note and 'straddle' in note
    assert str(OWNER_ROW_WIDTH) in note


@pytest.mark.parametrize('requested', ['twelve', '12.5', object(), 0, -6])
def test_a_value_that_is_not_a_usable_size_is_refused_not_clamped(requested):
    """Silent clamping is how an experiment reports an arm it did not run."""
    size, note = resolve_owner_fields_per_call(requested)

    assert size == MAX_OWNER_FIELDS_PER_CALL
    assert note


def test_every_refusal_names_the_value_it_refused():
    """A note saying the default was used, without saying what was asked for,
    sends the reader to check the environment by hand."""
    for requested in (8, 0, 'twelve'):
        _, note = resolve_owner_fields_per_call(requested)
        assert str(requested) in note
        assert str(MAX_OWNER_FIELDS_PER_CALL) in note


def test_the_default_divides_the_row_width():
    """The guard would be theatre if the shipped value failed it."""
    assert MAX_OWNER_FIELDS_PER_CALL % OWNER_ROW_WIDTH == 0
    assert resolve_owner_fields_per_call(MAX_OWNER_FIELDS_PER_CALL)[1] is None
