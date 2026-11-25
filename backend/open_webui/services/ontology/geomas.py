"""The GeoMAS ontology: `geomas-core` 1.2.0 and `geoteaser` 1.0.0, copied from GMM.

The packages under `assets/` are loaded and verified against `assets/provenance.json`.
The fill annotates its batches with them, and chat retrieval widens its queries with them.
See `docs/ontology.md`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..geotizer.errors import GeotizerOrchestrationError

log = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent / 'assets'
PROVENANCE_FILE = 'provenance.json'
ONTOLOGY_PREFIX = 'geomas-core:'
MAX_TERMS = 12

DASHES = re.compile(r'[‐-―−﹘﹣－-]+')
TOKEN = re.compile(r'[0-9a-zа-я]+', re.IGNORECASE)
CYRILLIC = re.compile(r'[а-я]', re.IGNORECASE)
LATIN = re.compile(r'[a-z]', re.IGNORECASE)
CYRILLIC_WORD = re.compile(r'[а-я]+')
LATIN_TO_CYRILLIC = str.maketrans('abcekmoptxy', 'авсекмортху')
CYRILLIC_TO_LATIN = str.maketrans('авсекмортху', 'abcekmoptxy')
LATIN_LOOKALIKES = frozenset('abcekmoptxy')
CYRILLIC_LOOKALIKES = frozenset('авсекмортху')
ENDINGS = tuple(
    sorted(
        (
            'иями ями ами ого его ому ему ыми ими ией ий ый ой ая яя ое ее ые ие ых их ую юю ом ем ов ев '
            'ам ям ах ях ию ия ии ье ья а я о е ы и у ю ь й'
        ).split(),
        key=len,
        reverse=True,
    )
)
MIN_STEM = 3


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize('NFKC', text).casefold().replace('ё', 'е')
    words = []
    for word in TOKEN.findall(DASHES.sub(' ', normalized)):
        if CYRILLIC.search(word) and LATIN.search(word):
            word = word.translate(LATIN_TO_CYRILLIC)
        words.append(word)
    return ' '.join(words)


def _is_code(word: str, allowed: frozenset[str] = LATIN_LOOKALIKES) -> bool:
    letters = {char for char in word if char.isalpha()}
    return word.isalnum() and bool(letters) and letters != set(word) and letters <= allowed


def _stem(word: str) -> str:
    if CYRILLIC_WORD.fullmatch(word):
        for ending in ENDINGS:
            if word.endswith(ending) and len(word) - len(ending) >= MIN_STEM:
                return word[: -len(ending)]
    return word


def _tokens(text: str) -> tuple[str, ...]:
    """The linker's tokens of a text: codes folded to Latin, Cyrillic words without one ending."""
    return tuple(
        word.translate(CYRILLIC_TO_LATIN) if _is_code(word, LATIN_LOOKALIKES | CYRILLIC_LOOKALIKES) else _stem(word)
        for word in _normalize(text).split()
    )


def _texts(entity: Mapping[str, Any]) -> list[str]:
    """An entity's labels, then its synonyms (`aliases`)."""
    return [
        *entity['labels'].values(),
        *(alias for aliases in entity.get('aliases', {}).values() for alias in aliases),
    ]


def _verified_json(path: Path, digest: str, assets: Path) -> Any:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise GeotizerOrchestrationError(f'{path.relative_to(assets).as_posix()} does not match its recorded sha256')
    return json.loads(raw.decode('utf-8'))


def _counts(package_id: str, files: Mapping[str, Any]) -> dict[str, Any]:
    if package_id == 'geoteaser':
        value_types: dict[str, int] = {}
        for field in files['fields.json']:
            value_types[field['value_type']] = value_types.get(field['value_type'], 0) + 1
        return {
            'rows': len(files['rows.json']),
            'fields': len(files['fields.json']),
            'dependencies': len(files['dependencies.json']),
            'source_roles': len(files['source_roles.json']),
            'notes': len(files['notes.json']),
            'field_attribute_links': sum(len(field['attributes']) for field in files['fields.json']),
            'field_value_types': value_types,
        }
    entities = files['entities.json']
    return {
        'classes': len(files['classes.json']),
        'attributes': len(files['attributes.json']),
        'entities': len(entities),
        'entities_with_synonyms': sum(1 for entity in entities if entity.get('aliases')),
        'entities_in_concept_groups': sum(1 for entity in entities if 'concept' in entity),
        'relation_kinds': len(files['relation_kinds.json']),
        'relations': len(files['relations.json']),
        'qualifiers': len(files['qualifiers.json']),
        'notes': len(files['notes.json']),
        'codelists': sum(1 for name in files if name.startswith('codelists/')),
        'intents': len(files['retrieval.json']['intents']),
    }


@lru_cache(maxsize=4)
def _load(assets_key: str) -> dict[str, Any]:
    """Both packages, verified, with the indexes the hooks read.

    Raises `GeotizerOrchestrationError` naming the file when a manifest digest, a file
    sha256, a package id or version, or a record count differs from `provenance.json`.
    """
    assets = Path(assets_key)
    provenance = json.loads((assets / PROVENANCE_FILE).read_text(encoding='utf-8'))
    packages: dict[str, dict[str, Any]] = {}
    for package in provenance['packages']:
        directory = assets / package['id'] / package['version']
        manifest = _verified_json(directory / 'manifest.json', package['manifest_digest'], assets)
        if (manifest['id'], manifest['version']) != (package['id'], package['version']):
            raise GeotizerOrchestrationError(
                f'{package["id"]}/{package["version"]}/manifest.json names {manifest["id"]}@{manifest["version"]}'
            )
        files = {name: _verified_json(directory / name, digest, assets) for name, digest in manifest['files'].items()}
        counts = _counts(package['id'], files)
        for name, expected in package['counts'].items():
            if counts.get(name) != expected:
                raise GeotizerOrchestrationError(
                    f'{package["id"]}/{package["version"]}: {name} is {counts.get(name)}, '
                    f'provenance.json records {expected}'
                )
        packages[package['id']] = files

    core, template = packages['geomas-core'], packages['geoteaser']
    phrases: dict[tuple[str, ...], set[str]] = {}
    codes: dict[str, set[str]] = {}
    for entity in core['entities.json']:
        for text in _texts(entity):
            found = _tokens(text)
            if found:
                phrases.setdefault(found, set()).add(entity['id'])
            for word in found:
                if _is_code(word):
                    codes.setdefault(word, set()).add(entity['id'])
    same: dict[str, set[str]] = {}
    for relation in core['relations.json']:
        if relation['kind'] == 'same':
            same.setdefault(relation['from'], set()).add(relation['to'])
            same.setdefault(relation['to'], set()).add(relation['from'])
    return {
        'provenance': provenance,
        'entities': {entity['id']: entity for entity in core['entities.json']},
        'attributes': {attribute['id']: attribute for attribute in core['attributes.json']},
        'codelists': {
            document['id']: [label for concept in document['concepts'] for label in concept['labels'].values()]
            for name, document in core.items()
            if name.startswith('codelists/')
        },
        'rows': {row['id']: row for row in template['rows.json']},
        'fields': {field['key']: field for field in template['fields.json']},
        'phrases': phrases,
        'longest_phrase': max(map(len, phrases)),
        'codes': codes,
        'heads': {entity['id']: entity['concept'] for entity in core['entities.json'] if 'concept' in entity},
        'same': same,
    }


def _ontology() -> dict[str, Any]:
    return _load(str(ASSETS))


def _by_priority(entity_ids: Iterable[str], entities: Mapping[str, Any]) -> list[str]:
    return sorted(entity_ids, key=lambda entity_id: (entities[entity_id]['priority'], entity_id))


def _ordered_terms(
    entity_ids: Sequence[str],
    entities: Mapping[str, Any],
    skip: Callable[[str], bool] = lambda text: False,
) -> list[str]:
    """Labels and synonyms of `entity_ids` in that order, without casefolded repeats, at most `MAX_TERMS`."""
    terms: list[str] = []
    seen: set[str] = set()
    for entity_id in entity_ids:
        for text in _texts(entities[entity_id]):
            if text.casefold() in seen or skip(text):
                continue
            seen.add(text.casefold())
            terms.append(text)
            if len(terms) == MAX_TERMS:
                return terms
    return terms


def _field_annotation(ontology: Mapping[str, Any], field: Mapping[str, Any]) -> dict[str, Any]:
    entities = ontology['entities']
    attributes = {reference.removeprefix(ONTOLOGY_PREFIX) for reference in field['attributes']}
    named = [reference.removeprefix(ONTOLOGY_PREFIX) for reference in ontology['rows'][field['row']].get('entities', [])]
    carrying = [entity_id for entity_id in named if attributes & set(entities[entity_id]['attributes'])]
    others = [entity_id for entity_id in named if entity_id not in carrying]
    codelist = next(
        (
            ontology['codelists'][ontology['attributes'][attribute]['codelist']]
            for attribute in sorted(attributes)
            if ontology['attributes'][attribute].get('codelist')
        ),
        None,
    )
    return {
        'terms': _ordered_terms([*_by_priority(carrying, entities), *_by_priority(others, entities)], entities),
        'value_type': field['value_type'],
        'codelist': codelist,
    }


def annotate_batch(batch: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `batch` whose `geoteaser` fields each carry `ontology`.

    `ontology` holds `terms` (labels and synonyms of the row's entities, those carrying one
    of the field's attributes first, each group by `priority` then id, at most 12),
    `value_type`, and `codelist` (the labels of the enum attribute's codelist, or None).
    A field whose `field_key` is not in `geoteaser` is copied unchanged.
    """
    ontology = _ontology()
    fields = []
    for field in batch.get('fields') or []:
        template_field = ontology['fields'].get(str(field.get('field_key') or ''))
        fields.append(
            field if template_field is None else {**field, 'ontology': _field_annotation(ontology, template_field)}
        )
    return {**batch, 'fields': fields}


def linked_entities(text: str) -> set[str]:
    """Entity ids `text` reaches by a label, a synonym, a code or a concept group head."""
    ontology = _ontology()
    words = _tokens(text)
    found: set[str] = set()
    for size in range(1, min(len(words), ontology['longest_phrase']) + 1):
        for start in range(len(words) - size + 1):
            found |= ontology['phrases'].get(words[start : start + size], set())
    for word in words:
        if _is_code(word):
            found |= ontology['codes'].get(word, set())
    return found | {ontology['heads'][entity_id] for entity_id in found if entity_id in ontology['heads']}


def _added_terms(query: str) -> list[str]:
    ontology = _ontology()
    reached = linked_entities(query)
    reached |= {other for entity_id in reached for other in ontology['same'].get(entity_id, ())}
    present = set(_tokens(query))
    return _ordered_terms(
        _by_priority(reached, ontology['entities']),
        ontology['entities'],
        skip=lambda text: set(_tokens(text)) <= present,
    )


def expand_queries(queries: Sequence[str]) -> list[str]:
    """`queries` in order, then one widened query for each query that names an ontology concept.

    A widened query is the original, a space and the added terms joined by spaces: labels and
    synonyms of the reached entities and of their `same` relations whose tokens are not all in
    the query, by `priority` then id, at most 12. When the assets fail to load for any reason,
    `queries` is returned unchanged and the failure is logged.
    """
    try:
        _ontology()
    except Exception:
        log.exception('GeoMAS ontology assets failed to load; chat retrieval runs unexpanded')
        return list(queries)
    expanded = list(queries)
    for query in queries:
        added = _added_terms(query) if query else []
        if added:
            log.debug('ontology expansion of %r adds %s', query, added)
            expanded.append(f'{query} {" ".join(added)}')
    return expanded


def ontology_record() -> dict[str, Any]:
    """The packages, manifest digests, GMM commit and mind map digest a run used, for `run_log`."""
    provenance = _ontology()['provenance']
    return {
        'packages': [
            {'id': package['id'], 'version': package['version'], 'manifest_digest': package['manifest_digest']}
            for package in provenance['packages']
        ],
        'source_repository': provenance['source_repository'],
        'source_commit': provenance['source_commit'],
        'mindmap_sha256': provenance['mindmap']['sha256'],
    }
