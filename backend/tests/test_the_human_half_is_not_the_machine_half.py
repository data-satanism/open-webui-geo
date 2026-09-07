"""`user_message` is the human-readable half; it must not be a payload.

The licence-first fill's failure arrived with both halves carrying the same
serialised blob:

    "message":      "{\\"code\\": \\"gis_infrastructure_unavailable\\", ...}"
    "user_message": "{\\"code\\": \\"gis_infrastructure_unavailable\\", ...}"

`GeotizerGisError.__str__` is JSON by design -- structure is what `details`
exists for -- and `_gis_error_user_message` ended in `return fallback`, which
is that same `str(exc)`. A user read the structure twice and the meaning zero
times.
"""

from __future__ import annotations

import json

from open_webui.services.artifacts.geotizer.terminal import _gis_error_user_message


def _blob(**fields) -> str:
    return json.dumps(fields, ensure_ascii=False)


def test_a_serialised_fallback_is_never_handed_to_a_person():
    details = {'code': 'gis_infrastructure_unavailable', 'violations': []}
    out = _gis_error_user_message(details, fallback=_blob(**details))
    assert not out.strip().startswith('{')
    assert 'gis_infrastructure_unavailable' in out, 'the code still belongs in the sentence'
    assert 'details' in out


def test_it_says_a_retry_will_not_help():
    """The orchestrator advised «повторный запуск должен завершиться успешно».

    A deterministic computation over unchanged data reproduces; the sentence
    has to close that reading rather than leave it open.
    """
    out = _gis_error_user_message(
        {'code': 'gis_infrastructure_unavailable'},
        fallback=_blob(code='gis_infrastructure_unavailable'),
    )
    assert 'повторный запуск' in out and 'тот же результат' in out


def test_a_named_licence_refusal_reads_as_a_sentence():
    out = _gis_error_user_message(
        {
            'code': 'licence_not_found_in_layer',
            'identity_field': 'LUID',
            'layer_id': 'Licenses_2024_2025',
            'requested_licence_id': 'МАГ04805БЭ',
        },
        fallback='{}',
    )
    assert 'МАГ04805БЭ' in out and 'LUID' in out and 'Licenses_2024_2025' in out
    assert not out.strip().startswith('{')


def test_a_layer_with_no_identity_column_says_so_rather_than_naming_none():
    out = _gis_error_user_message(
        {'code': 'licence_not_found_in_layer', 'identity_field': None,
         'layer_id': 'Licenses_annul', 'requested_licence_id': 'МАГ04805БЭ'},
        fallback='{}',
    )
    assert 'не объявляет' in out
    assert 'None' not in out, 'a null column must not be printed as a column name'


def test_a_prose_fallback_is_still_passed_through_unchanged():
    """Only payloads are replaced. A sentence that was already a sentence stays."""
    sentence = 'Связанный GIS-проект действительно не найден.'
    assert _gis_error_user_message({}, fallback=sentence) == sentence


def test_the_two_sentences_that_predate_this_are_untouched():
    assert _gis_error_user_message(
        {'project_resolution': {'status': 'not_found'}}, fallback='{}'
    ) == 'Связанный GIS-проект действительно не найден.'
    assert 'несколько подходящих' in _gis_error_user_message(
        {'project_resolution': {'status': 'ambiguous'}}, fallback='{}'
    )
