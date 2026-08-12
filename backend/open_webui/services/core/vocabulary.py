"""Controlled vocabularies shared across the layers.

A vocabulary is not a rule: the validation copies read these, and so does the
evidence core, which is why they sit below both.
"""

from __future__ import annotations

from typing import Any


ALLOWED_FIELD_STATUSES = frozenset(
    {
        'filled',
        'not_found',
        'not_applicable',
        'conflicted',
        'requires_expert_review',
    }
)


ALLOWED_VALUE_ORIGINS = frozenset(
    {
        'direct',
        'calculated',
        'analogue',
    }
)


NEGATIVE_VALUE_MARKERS = frozenset(
    {
        'n/a',
        'na',
        'no data',
        'not found',
        'not-found',
        'not_found',
        'not available',
        'unknown',
        'нет данных',
        'данные отсутствуют',
        'данные не найдены',
        'не найден',
        'не найдена',
        'не найдено',
        'не найдены',
        'не найдено данных',
        'не указан',
        'не указана',
        'не указано',
        'не указаны',
        'не указано отдельно',
        'не определен',
        'не определена',
        'не определено',
        'не определены',
        'отсутствует',
    }
)


NEGATIVE_VALUE_QUALIFIERS = (
    'в документ',
    'в доступн',
    'в источник',
    'в материал',
    'в предоставлен',
    'в контекст',
    'отдельно',
    'in available',
    'in document',
    'in provided',
    'in source',
    'separately',
)


def _is_negative_value_marker(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = ' '.join(value.casefold().replace('ё', 'е').split()).strip(' .;:-')
    if not normalized or normalized in NEGATIVE_VALUE_MARKERS:
        return True
    for marker in NEGATIVE_VALUE_MARKERS:
        if not normalized.startswith(marker):
            continue
        suffix = normalized[len(marker) :]
        if suffix and suffix[0] not in ' .;,:-—':
            continue
        qualifier = suffix.lstrip(' .;,:-—')
        if any(qualifier.startswith(prefix) for prefix in NEGATIVE_VALUE_QUALIFIERS):
            return True
    return False
