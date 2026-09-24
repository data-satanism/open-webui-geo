"""`resolve_owner_fields_per_call` takes a chunk size that is a multiple of the row
width and refuses any other with a note."""

from __future__ import annotations

import pytest
from open_webui.services.artifacts.geotizer.workflow import (
    MAX_OWNER_FIELDS_PER_CALL,
    OWNER_ROW_WIDTH,
    resolve_owner_fields_per_call,
)


@pytest.mark.parametrize('requested', [None, ''])
def test_an_unset_value_leaves_the_default_and_says_nothing(requested):
    """An unset value gives the default with no note."""
    assert resolve_owner_fields_per_call(requested) == (MAX_OWNER_FIELDS_PER_CALL, None)


@pytest.mark.parametrize('requested', [12, '12', 18, 6, 24])
def test_a_size_that_divides_the_row_is_taken(requested):
    size, note = resolve_owner_fields_per_call(requested)

    assert size == int(requested)
    assert note is None


def test_a_size_that_would_split_a_resource_row_is_refused():
    """A size that is not a multiple of `OWNER_ROW_WIDTH` is refused with a note."""
    size, note = resolve_owner_fields_per_call(8)

    assert size == MAX_OWNER_FIELDS_PER_CALL
    assert note and 'straddle' in note
    assert str(OWNER_ROW_WIDTH) in note


@pytest.mark.parametrize('requested', ['twelve', '12.5', object(), 0, -6])
def test_a_value_that_is_not_a_usable_size_is_refused_not_clamped(requested):
    """A value that is not a positive integer is refused with a note rather than
    clamped."""
    size, note = resolve_owner_fields_per_call(requested)

    assert size == MAX_OWNER_FIELDS_PER_CALL
    assert note


def test_every_refusal_names_the_value_it_refused():
    """Every refusal note names the requested value and the default."""
    for requested in (8, 0, 'twelve'):
        _, note = resolve_owner_fields_per_call(requested)
        assert str(requested) in note
        assert str(MAX_OWNER_FIELDS_PER_CALL) in note


def test_the_default_divides_the_row_width():
    """`MAX_OWNER_FIELDS_PER_CALL` is a multiple of `OWNER_ROW_WIDTH` and passes the
    guard."""
    assert MAX_OWNER_FIELDS_PER_CALL % OWNER_ROW_WIDTH == 0
    assert resolve_owner_fields_per_call(MAX_OWNER_FIELDS_PER_CALL)[1] is None
