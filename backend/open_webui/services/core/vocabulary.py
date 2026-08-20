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
        # A cell nobody asked a geologist about: the run never got an answer,
        # so there is no value to judge. Kept apart from
        # `requires_expert_review`, which is a question for a person with the
        # domain. The deterministic check here has to accept it or this
        # repository rejects its own fallback envelope before the service ever
        # sees it.
        'agent_contract_failed',
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


#: "This source looked and found nothing", which is not the same statement as
#: `NEGATIVE_VALUE_MARKERS` above.
#:
#: Those mean the retrieval failed, and a cell carrying one is coerced to
#: `not_found` because nothing was ever established. These mean a search
#: completed and came back empty -- which can be the object's answer. Run
#: `6af7479f` filled six `KB-STUDY` cells with «отсутствуют» and the note
#: «Согласованные данные GIS и KB: разведка не проводилась»: exploration was
#: never carried out, two sources agreed, and that is a fact about the object.
#: Coercing those to `not_found` would delete six answers to fix sixteen.
#:
#: So this list is used for one decision only, in
#: `_apply_structured_field_proposals`: a source that found nothing never
#: competes with a source that found something, and never fills a cell on its
#: own. The discriminator that makes it safe is the one the coercion does not
#: have -- whether anybody else answered the same cell.
#:
#: A union with the list above rather than a copy of it: a phrasing added there
#: is a phrasing here, and there is no second place to keep in step.
EMPTY_FINDING_MARKERS = NEGATIVE_VALUE_MARKERS | frozenset(
    {
        'none',
        'none found',
        'none identified',
        'not detected',
        'not established',
        'not identified',
        '—',
        '–',
        'нет сведений',
        'не выявлен',
        'не выявлена',
        'не выявлено',
        'не выявлены',
        'не обнаружен',
        'не обнаружена',
        'не обнаружено',
        'не обнаружены',
        'не установлен',
        'не установлена',
        'не установлено',
        'не установлены',
        'отсутствуют',
    }
)


def _normalized_marker_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return ' '.join(value.casefold().replace('ё', 'е').split()).strip(' .;:-')


def _matches_marker(normalized: str, markers: frozenset[str]) -> bool:
    if not normalized or normalized in markers:
        return True
    for marker in markers:
        if not normalized.startswith(marker):
            continue
        suffix = normalized[len(marker) :]
        if suffix and suffix[0] not in ' .;,:-—':
            continue
        qualifier = suffix.lstrip(' .;,:-—')
        if any(qualifier.startswith(prefix) for prefix in NEGATIVE_VALUE_QUALIFIERS):
            return True
    return False


def _is_negative_value_marker(value: Any) -> bool:
    """The retrieval failed: no value was ever established for this cell."""
    normalized = _normalized_marker_text(value)
    if normalized is None:
        return False
    return _matches_marker(normalized, NEGATIVE_VALUE_MARKERS)


def _is_empty_finding(value: Any) -> bool:
    """This source searched and came back with nothing to report."""
    normalized = _normalized_marker_text(value)
    if normalized is None:
        return False
    return _matches_marker(normalized, EMPTY_FINDING_MARKERS)


# Every source_inventory entry must carry these, and the GIS request model
# refuses one that does not. Named here rather than inline so the caller-side
# check and the server contract can be compared by reading one line.
REQUIRED_SOURCE_FIELDS = ('source_type', 'title')
