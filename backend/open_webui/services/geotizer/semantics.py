"""Versioned runtime semantics for high-risk GeoTeaser fields.

`implementation-steps.md` S1.3: the row tables move to GMM as versioned assets
and load with a hash and version check; `semantic_hint` stays here as the
executor. Before this they were transcribed into Python beside GMM's
`geotizer-runtime-semantics.v0.2.json`, which is exactly the two-copies problem
A-08 records -- with the aggravation that nothing could notice the drift, because
the transcription had no digest to check against.

The asset now travels with the runtime and is verified byte-for-byte on load, so
the only way the two disagree is a copy that refuses to load at all. What the
policy says about a row -- its entity scope, its estimate states, its work stage,
its analogue relation, its source priority and its negative cases -- is read from
the document rather than restated here.

Two tables stay in Python because the policy has no home for them: the mapping
from a Russian attribute name to the value kinds a ГРР plan cell may carry, and
the set of GIS proxy value kinds. Both are attribute-level and the policy is
row-level. Recorded as GMM attention register A-50 rather than bolted onto
someone else's contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import GeotizerOrchestrationError

ASSETS = Path(__file__).resolve().parent / 'assets'
POLICY_FILE = 'geotizer-runtime-semantics.v0.2.json'
PROVENANCE_FILE = 'provenance.json'

SEMANTIC_POLICY_VERSION = 'geotizer_runtime_semantics.v0.2'
POLICY_ID = 'geomas-geotizer-runtime-semantics'
POLICY_SCHEMA_VERSION = '0.2.0'


@lru_cache(maxsize=4)
def _load(assets_key: str) -> dict[str, Any]:
    assets = Path(assets_key)
    recorded = json.loads((assets / PROVENANCE_FILE).read_text(encoding='utf-8'))['files'].get(POLICY_FILE)
    if not recorded:
        raise GeotizerOrchestrationError(f'{POLICY_FILE} has no provenance record')
    raw = (assets / POLICY_FILE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != recorded['sha256']:
        raise GeotizerOrchestrationError(
            f'{POLICY_FILE} does not match its recorded digest; the copy has drifted from '
            f'{recorded["source_repository"]}'
        )
    document = json.loads(raw.decode('utf-8'))
    # The version check S1.3 asks for, separate from the digest: a byte-identical
    # copy of the wrong policy version is still the wrong policy.
    if document['policy_id'] != POLICY_ID or document['schema_version'] != POLICY_SCHEMA_VERSION:
        raise GeotizerOrchestrationError(
            f'{POLICY_FILE} is {document["policy_id"]}@{document["schema_version"]}, '
            f'not {POLICY_ID}@{POLICY_SCHEMA_VERSION}'
        )
    if len(document['row_semantics']) != recorded['row_semantics']:
        raise GeotizerOrchestrationError(f'{POLICY_FILE} row_semantics count does not match its provenance record')
    return document


def load_policy(assets: Path | None = None) -> dict[str, Any]:
    return _load(str(assets or ASSETS))


def _rows(entry: Mapping[str, Any]) -> list[int]:
    if 'rows' in entry:
        return [int(row) for row in entry['rows']]
    first, last = entry['row_range']
    return list(range(int(first), int(last) + 1))


@lru_cache(maxsize=4)
def _by_row(assets_key: str) -> dict[int, dict[str, Any]]:
    """One entry per row, with the row's own work stage resolved.

    `grr_plan` is written as a range plus an ordered `work_stages` list, so the
    stage for row 70 is the third of nine rather than a value on the row. The
    positional read is the only place this module interprets the document, and
    it is checked by `test_geotizer_semantics_asset.py`.
    """
    resolved: dict[int, dict[str, Any]] = {}
    for entry in _load(assets_key)['row_semantics']:
        rows = _rows(entry)
        stages = entry.get('work_stages') or ()
        if stages and len(stages) != len(rows):
            raise GeotizerOrchestrationError(
                f'{entry["semantic_family"]} names {len(stages)} work stages for {len(rows)} rows'
            )
        for index, row in enumerate(rows):
            resolved[row] = {**entry, 'work_stage': stages[index] if stages else None}
    return resolved


def row_semantics(row_id: int, assets: Path | None = None) -> dict[str, Any] | None:
    return _by_row(str(assets or ASSETS)).get(int(row_id))


def _scope_table(family: str) -> dict[int, str]:
    return {
        row: entry['entity_scopes'][0]
        for row, entry in _by_row(str(ASSETS)).items()
        if entry['semantic_family'] == family and entry.get('entity_scopes')
    }


def _families(*names: str) -> dict[int, dict[str, Any]]:
    return {row: entry for row, entry in _by_row(str(ASSETS)).items() if entry['semantic_family'] in names}


# Derived from the policy, not transcribed beside it. The names are unchanged so
# `project_evidence/proposals.py` and `artifacts/geotizer/validation.py` keep
# importing what they always did.
GEOLOGY_ENTITY_SCOPE_BY_ROW = _scope_table('geological_hierarchy')
RESOURCE_ENTITY_SCOPE_BY_ROW = {
    row: entry['entity_scopes'][0] for row, entry in _families('resource_estimate', 'resource_analogue').items()
}
RESOURCE_ESTIMATE_STATES_BY_ROW = {
    row: frozenset(entry['estimate_states'])
    for row, entry in _families('resource_estimate', 'resource_analogue').items()
    if entry.get('estimate_states')
}
ANALOGUE_RELATION_BY_ROW = {row: entry['analogue_relation'] for row, entry in _families('resource_analogue').items()}

#: The row families whose attributes describe one estimate, and the locator
#: keys that say which estimate each of their rows is reporting.
#:
#: `_resource_row_consistency_violations` used to carry its own list of five
#: qualifier names and its own `44 <= row_id <= 56`, and both had already
#: drifted from the policy it is enforcing: the contract requires `site_name`
#: on rows 50-53 and `source_document_id` on the analogue rows and the check
#: asked for neither, while it demanded `estimate_state` on analogue rows where
#: the contract does not list it. Read from `required_qualifiers` now, which is
#: the same list `semantic_hint` puts in the owner's prompt, so what the owner
#: is told to supply and what the row is held to are one statement.
#:
#: The family list is here rather than in the contract because the contract has
#: no field for "this family's rows must be internally coherent" --
#: `gis_service` states the same two names for its carry-forward row pass. GMM
#: attention register A-86.
COHERENT_ESTIMATE_ROW_FAMILIES = ('resource_estimate', 'resource_analogue')

#: A `required_qualifier` that names where a value came from rather than what
#: the row is about, and so is not part of the row's identity.
#:
#: The contract lists both kinds under one name. Row 55 of run `92661b9b` is
#: the case: one analogue deposit, `saurey-deposit` / `neighbouring_structure`
#: on every cell, with «название» cited to `viken-2020-pdf` and
#: «геолого-генетический тип» to `expert-ural-2007-article`. Two documents
#: about one deposit is what a row should look like, and holding
#: `source_document_id` to one value would mark it for expert review.
SOURCE_IDENTIFYING_QUALIFIERS = frozenset({'source_document_id'})
ESTIMATE_ROW_IDENTITY_QUALIFIERS = {
    row: tuple(
        str(key)
        for key in entry['required_qualifiers']
        if str(key) not in SOURCE_IDENTIFYING_QUALIFIERS
    )
    for row, entry in _families(*COHERENT_ESTIMATE_ROW_FAMILIES).items()
    if entry.get('required_qualifiers')
}
GRR_WORK_STAGE_BY_ROW = {row: entry['work_stage'] for row, entry in _families('grr_plan').items()}

# Attribute-level, and the row-level policy has no home for either. GMM
# attention register A-50: proposing a place for them is an Ontology Approver
# decision, not something to add to another repository's contract in passing.
GRR_VALUE_KIND_BY_ATTRIBUTE = {
    'вид': frozenset({'planned_work'}),
    'объемы': frozenset({'planned_volume', 'planned_quantity'}),
    'объёмы': frozenset({'planned_volume', 'planned_quantity'}),
    'масштаб': frozenset({'planned_scale', 'sampling_grid'}),
    'стоимость': frozenset({'planned_cost'}),
    'срок': frozenset({'schedule'}),
    'документ': frozenset({'document_reference'}),
}

# Attribute-level, and here for the same reason `GRR_VALUE_KIND_BY_ATTRIBUTE`
# is: the row-level policy has no home for it either. GMM attention register
# A-50 covers both.
#
# The distinction this exists for is r0NN.a01 «значение» against r0NN.a02
# «объем руды». They are different quantities and they share a unit: an
# estimate of 12 млн т of ore and 12 млн т of contained metal are both «млн т»
# and only one of them can be right. A unit check cannot separate them, which
# is why the value kind carries the weight and the unit only rules out the
# families that are plainly wrong -- a grade in tonnes, a depth in г/т.
RESOURCE_VALUE_KIND_BY_ATTRIBUTE = {
    'значение': frozenset({'resource_quantity', 'contained_metal', 'metal_mass'}),
    'объем руды': frozenset({'ore_tonnage', 'ore_volume'}),
    'объём руды': frozenset({'ore_tonnage', 'ore_volume'}),
    'средние содержания': frozenset({'grade'}),
    'глубина прогноза': frozenset({'depth'}),
    'год оценки': frozenset({'year'}),
    'ресурсы': frozenset({'resource_quantity', 'contained_metal', 'metal_mass'}),
    'документ': frozenset({'document_reference'}),
}

#: The dimension each resource value kind is measured in.
RESOURCE_UNIT_FAMILY_BY_VALUE_KIND = {
    'resource_quantity': 'mass',
    'contained_metal': 'mass',
    'metal_mass': 'mass',
    'ore_tonnage': 'mass',
    'ore_volume': 'volume',
    'grade': 'concentration',
    'depth': 'length',
}

#: Units this side recognises, by dimension. Deliberately not exhaustive, and
#: the rule that reads it only refuses a unit it recognises as belonging to
#: the wrong family. An unlisted unit is not evidence of a mismatch, and
#: refusing one would reject a correct value for being spelled unusually.
RESOURCE_UNITS_BY_FAMILY = {
    'mass': frozenset(
        {'т', 'тонн', 'тыс. т', 'тыс.т', 'тыс т', 'млн т', 'млн.т', 'млн. т',
         'кг', 'г', 't', 'kt', 'mt'}
    ),
    'volume': frozenset(
        {'м3', 'м³', 'куб. м', 'тыс. м3', 'млн м3', 'm3', 'm³'}
    ),
    'concentration': frozenset(
        {'г/т', 'g/t', '%', 'ppm', 'ppb', 'кг/т', 'г/м3', 'мг/кг'}
    ),
    'length': frozenset({'м', 'm', 'км', 'km'}),
}

#: A unit to the family it belongs to. `м` is length and `т` is mass, and no
#: unit is listed under two families -- the moment one is, this inversion is
#: the wrong shape and the check that reads it is guessing.
RESOURCE_UNIT_FAMILIES = {
    unit: family
    for family, units in RESOURCE_UNITS_BY_FAMILY.items()
    for unit in units
}

#: Attributes that can only be a number, whatever row they sit on.
#:
#: The template declares no types -- a field entry carries `attribute_name`,
#: `element`, `group`, `row_id` and `excel_cell`, and nothing about what shape
#: an answer takes. So «Энергетическая база отсутствует» landed in the
#: distance-to-energy-node cell on run `af707b17` and every check passed it: a
#: string in a cell that takes strings, as far as anything could tell.
#:
#: Listed by name and kept to the unambiguous ones. «Средние содержания» is a
#: grade and is usually written «Au 1.2 г/т», «масштаб» is «1:200 000», and
#: «стоимость» arrives as «98 млн ₽» -- all of them numbers wearing text, and
#: none of them worth the false refusals a looser list would produce.
NUMERIC_ATTRIBUTES = frozenset(
    {
        'абсолютный возраст',
        'год',
        'год оценки',
        'год последних работ',
        'глубина прогноза',
        'диаметр',
        'максимальная длина',
        'максимальная мощность',
        'общее число',
        'общий объем',
        'объем руды',
        'площадь',
        'расстояние',
        'средняя глубина',
        'средняя длина',
        'средняя мощность',
        'средняя протяженность',
        'число',
        'число месяцев',
        'число проб',
        'число профилей',
        'шаг профилей',
    }
)

#: The numeric cells whose attribute is «значение», which is on 21 fields and
#: means something different on most of them.
#:
#: r077.a01 is «Степень экономической освоенности района» and is prose; the six
#: below it are distances in km; r012 is an area and r104 a count. The
#: attribute name cannot separate them, so these are named by key.
NUMERIC_FIELD_KEYS = frozenset(
    {
        'geotizer_object.v1.r012.a01',   # площадь лицензии
        'geotizer_object.v1.r078.a01',   # до ближайшего населённого пункта
        'geotizer_object.v1.r079.a01',   # до федерального центра
        'geotizer_object.v1.r080.a01',   # до ГОК/ЗИФ
        'geotizer_object.v1.r081.a01',   # до энергетического узла
        'geotizer_object.v1.r082.a01',   # до порта
        'geotizer_object.v1.r083.a01',   # до государственной границы
        'geotizer_object.v1.r104.a01',   # общее число лицензий на юр.лице
    }
)

_DIGIT = re.compile(r'\d')


def expects_a_number(field: Mapping[str, Any]) -> bool:
    """Whether this cell's answer has to contain a quantity."""
    if str(field.get('field_key') or '') in NUMERIC_FIELD_KEYS:
        return True
    return str(field.get('attribute_name') or '').casefold().strip() in NUMERIC_ATTRIBUTES


def states_no_quantity(value: Any) -> bool:
    """A value with no digit anywhere in it.

    Deliberately this and not a parser. «9.471 км», «98 млн ₽» and «1969-1970»
    are all legitimate answers in their rows and none of them is a bare float;
    a parser strict enough to reject prose would reject those too. What the
    defect actually looks like is a sentence -- «Энергетическая база
    отсутствует» -- and a sentence has no digits in it.
    """
    if value is None:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return False
    return _DIGIT.search(str(value)) is None


GIS_PROXY_VALUE_KINDS = frozenset(
    {
        'feature_elevation',
        'geometry_length',
        'geometry_area',
        'gis_feature_count',
    }
)


def semantic_hint(field: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact prompt-facing semantic contract for one field."""
    row_id = int(field.get('row_id') or 0)
    entry = row_semantics(row_id)
    result: dict[str, Any] = {'policy_version': SEMANTIC_POLICY_VERSION}
    if entry is None:
        return result

    family = entry['semantic_family']
    result['semantic_family'] = family
    if entry.get('entity_scopes'):
        result['required_entity_scope'] = entry['entity_scopes'][0]
    result['allowed_value_origins'] = list(entry['allowed_value_origins'])
    result['source_priority'] = list(entry['source_priority'])
    if entry.get('negative_cases'):
        result['rules'] = list(entry['negative_cases'])

    if family in ('resource_estimate', 'resource_analogue'):
        result['allowed_estimate_states'] = sorted(entry['estimate_states'])
        # De-duplicated, order preserved. The asset already lists
        # `resource_estimate_id` on these rows and `site_name` on 50-53, so
        # appending them unconditionally handed the model each qualifier twice.
        # The existing test only asserts membership, which a duplicate passes.
        required = [
            *entry['required_qualifiers'],
            *(['resource_estimate_id'] if family == 'resource_estimate' else []),
            # Rows 50-53 are the teaser's own subdivision into named sites, so
            # the site name is what tells two otherwise identical estimates apart.
            *(['site_name'] if 50 <= row_id <= 53 else []),
        ]
        result['required_qualifiers'] = list(dict.fromkeys(required))
        # The contract has to be stated before it can be enforced. r0NN.a01
        # «значение» and r0NN.a02 «объем руды» are different quantities in the
        # same unit, and until this line the model was never told which kind
        # each cell wants -- so a rule refusing a wrong value_kind would have
        # been refusing an answer to a question nobody asked.
        allowed_kinds = RESOURCE_VALUE_KIND_BY_ATTRIBUTE.get(
            str(field.get('attribute_name') or '').casefold().strip()
        )
        if allowed_kinds:
            result['allowed_value_kinds'] = sorted(allowed_kinds)
            expected_family = {
                RESOURCE_UNIT_FAMILY_BY_VALUE_KIND[kind]
                for kind in allowed_kinds
                if kind in RESOURCE_UNIT_FAMILY_BY_VALUE_KIND
            }
            if len(expected_family) == 1:
                result['expected_unit_family'] = next(iter(expected_family))
        if family == 'resource_analogue':
            result['required_analogue_relation'] = entry['analogue_relation']
    else:
        result['required_qualifiers'] = list(entry['required_qualifiers'])

    if family == 'grr_plan':
        result['required_work_stage'] = entry['work_stage']
        result['allowed_value_kinds'] = sorted(
            GRR_VALUE_KIND_BY_ATTRIBUTE.get(str(field.get('attribute_name') or '').casefold(), ())
        )

    return result


__all__ = [
    'ANALOGUE_RELATION_BY_ROW',
    'COHERENT_ESTIMATE_ROW_FAMILIES',
    'SOURCE_IDENTIFYING_QUALIFIERS',
    'ESTIMATE_ROW_IDENTITY_QUALIFIERS',
    'ASSETS',
    'GEOLOGY_ENTITY_SCOPE_BY_ROW',
    'GIS_PROXY_VALUE_KINDS',
    'NUMERIC_ATTRIBUTES',
    'NUMERIC_FIELD_KEYS',
    'expects_a_number',
    'states_no_quantity',
    'GRR_VALUE_KIND_BY_ATTRIBUTE',
    'GRR_WORK_STAGE_BY_ROW',
    'POLICY_ID',
    'RESOURCE_ENTITY_SCOPE_BY_ROW',
    'RESOURCE_UNIT_FAMILIES',
    'RESOURCE_UNITS_BY_FAMILY',
    'RESOURCE_UNIT_FAMILY_BY_VALUE_KIND',
    'RESOURCE_VALUE_KIND_BY_ATTRIBUTE',
    'RESOURCE_ESTIMATE_STATES_BY_ROW',
    'SEMANTIC_POLICY_VERSION',
    'load_policy',
    'row_semantics',
    'semantic_hint',
]
