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
        'not determined',
        'undetermined',
        'unknown',
        # The Russian spelling of the line above. Its absence is what let
        # `191e082d` carry five «неизвестно» cells forward as answers.
        'неизвестно',
        'не известно',
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


#: A sentence whose own text says the value is unknown.
#:
#: `EMPTY_FINDING_MARKERS` cannot express these, and not for want of entries --
#: «не указано» and «не определено» are already in the narrow set above. What
#: stops them matching is `_matches_marker`, which accepts a marker followed
#: only by a `NEGATIVE_VALUE_QUALIFIER` («в документе», «отдельно»). «Не
#: указано точное число профилей» continues into a noun phrase instead, so the
#: value reads as a sentence and the cell stays `filled` on run `af707b17`,
#: with F42 and G43 doing exactly that and six alteration cells holding the
#: bare quality flag «неверифицировано».
#:
#: The distinction the qualifier gate was reaching for is real and is kept: a
#: sentence about the *source* is not a sentence about the *object*. «Не
#: указано число профилей» is about a document. «Разведка не проводилась» is
#: about the deposit, and D33-I33 carry it under «отсутствуют» as six real
#: answers -- which is why this set is read by `_is_empty_finding` and never by
#: `_is_negative_value_marker`. The wide tier decides what may compete and be
#: carried; the narrow one empties cells, and nothing here may reach it.
#:
#: Token prefixes, anchored at the start, and never substrings. `не указан`
#: has to be the first two tokens with the second beginning that stem, so
#: «неопределенность» is untouched (one token, no space) and
#: «неверифицированные данные: 15 профилей» is untouched (the token does not
#: begin with «неверифицировано»). Substring matching is what produced four
#: earlier collisions here -- `скважин`, `изученн`, `reviewed_gap`, and `197`
#: inside a run id -- and this is the fifth place it would have.
ABSENCE_ASSERTION_PREFIXES: tuple[tuple[str, ...], ...] = (
    ('не', 'указан'),
    ('не', 'определен'),
    ('не', 'установлен'),
    ('неверифицировано',),
)


def _asserts_its_own_absence(normalized: str) -> bool:
    """The value's leading tokens say the value is not known."""
    tokens = normalized.split()
    for prefix in ABSENCE_ASSERTION_PREFIXES:
        if len(tokens) < len(prefix):
            continue
        head, stem = prefix[:-1], prefix[-1]
        if list(tokens[: len(head)]) != list(head):
            continue
        if tokens[len(head)].startswith(stem):
            return True
    return False


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
    """This source searched and came back with nothing to report.

    Two ways to say it: one of the catalogued markers, or a sentence whose own
    opening asserts the value is unknown. The second is the wide tier's alone
    -- `_is_negative_value_marker` above does not consult it, so a value that
    says it has no value stops competing and stops filling, and is never
    coerced to `not_found` on the strength of its own prose.
    """
    normalized = _normalized_marker_text(value)
    if normalized is None:
        return False
    if _matches_marker(normalized, EMPTY_FINDING_MARKERS):
        return True
    return _asserts_its_own_absence(normalized)


# Every source_inventory entry must carry these, and the GIS request model
# refuses one that does not. Named here rather than inline so the caller-side
# check and the server contract can be compared by reading one line.
REQUIRED_SOURCE_FIELDS = ('source_type', 'title')
