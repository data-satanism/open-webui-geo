"""«Заполнено: 219» is one sample, and printed alone it reads as a result.

Four clean runs of one build, nothing changed between them, filled 207, 191,
219 and 137 of 351 cells. 81 came back in all four, 68 in none, and the 202 in
between depend on the draw. The best figure this project ever recorded and one
of the worst are the same code on the same corpus minutes apart.

So the envelope never prints the count alone. Either the band this build was
measured to have, or the sentence saying no band has been measured for it.
Three outcomes and they are three different facts — a band, an unmeasured
build, and a service too old to have the field at all — and the third prints
nothing, the version-skew rule this module already follows for `card_docx_link`,
`_origin_suffix` and `_stage_scope_lines`.

This module prints what it was sent. Every number here comes from the service;
none is computed, and the deletion check at the bottom is what proves it.
"""

from __future__ import annotations

from open_webui.services.artifacts.geotizer.terminal import completeness_lines

COUNTS = {
    'required': 351,
    'filled': 219,
    'not_found': 105,
    'conflicted': 6,
    'requires_expert_review': 5,
    'agent_contract_failed': 12,
}

MEASURED = {
    'measured': True,
    'build_ref': '0123456789abcdef0123456789abcdef01234567',
    'record': 'operations/geotizer-runs/2026-09-03__four-runs-one-build-and-the-band.md',
    'reference_runs': ['06fec58d', '94124958', 'cf99d798', 'c43d3da1'],
    'filled_range': [137, 219],
    'cells': {'stable_filled': 81, 'unstable': 202, 'never_filled': 68},
    'union': 283,
}

UNMEASURED = {
    'measured': False,
    'build_ref': None,
    'reason': 'band_has_no_build_ref',
    'band_recorded': True,
}


def test_the_band_is_printed_beside_the_count():
    text = completeness_lines({'counts': COUNTS, 'run_variance': MEASURED})

    assert '- Заполнено: 219' in text
    assert '137' in text and '219' in text
    assert 'стабильно 81' in text
    assert 'нестабильно 202' in text
    assert 'недостижимо 68' in text
    assert 'По 4 прогонам этой сборки' in text


def test_the_record_is_named_so_the_band_can_be_recomputed():
    text = completeness_lines({'counts': COUNTS, 'run_variance': MEASURED})

    assert '2026-09-03__four-runs-one-build-and-the-band.md' in text
    assert '0123456789abcdef0123456789abcdef01234567' in text


def test_an_unmeasured_build_says_so_rather_than_going_quiet():
    """Silence would leave 219 standing as a measurement."""
    text = completeness_lines({'counts': COUNTS, 'run_variance': UNMEASURED})

    assert 'не измерен' in text
    assert 'одна выборка, а не измерение' in text
    assert '137' not in text


def test_a_service_too_old_to_have_the_field_prints_the_previous_envelope():
    text = completeness_lines({'counts': COUNTS})

    assert '- Заполнено: 219' in text
    assert 'не измерен' not in text
    assert 'прогонам этой сборки' not in text


def test_the_band_is_also_read_off_the_audit():
    text = completeness_lines({
        'audit': {'completeness': COUNTS, 'run_variance': MEASURED},
    })

    assert 'По 4 прогонам этой сборки' in text


def test_no_number_here_is_this_modules_own():
    """Deletion check: change what the service sent and every figure moves."""
    text = completeness_lines({
        'counts': COUNTS,
        'run_variance': {
            **MEASURED,
            'filled_range': [5, 9],
            'cells': {'stable_filled': 1, 'unstable': 2, 'never_filled': 3},
            'reference_runs': ['aaaaaaaa', 'bbbbbbbb'],
        },
    })

    assert 'По 2 прогонам этой сборки' in text
    assert 'стабильно 1' in text and 'нестабильно 2' in text and 'недостижимо 3' in text
    # `'202' not in text` would be a false failure: the record's filename
    # begins with the year.
    assert '137' not in text and 'нестабильно 202' not in text
