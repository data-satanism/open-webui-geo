"""The pinned induction seed: loading with digest checks, the lexical index and the prompt seed block."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import PinnedAssetMismatch

ASSETS = Path(__file__).resolve().parent / 'assets'
SEED_FILE = 'ontology-induction-seed.v0.1.json'
PROPOSAL_SCHEMA_FILE = 'ontology-induction-proposal.schema.json'
PROVENANCE_FILE = 'provenance.json'

PROMPT_KINDS = ('class', 'layer_role', 'entity_scope', 'semantic_family')
PROMPT_TERM_KEYS = ('term_id', 'label', 'labels_ru', 'description')
PROPOSED_KINDS = ('class', 'relation', 'attribute', 'field', 'entity_scope', 'semantic_family', 'layer_role')

SEED_BLOCK_HEADER = 'SEED TERMS (one JSON object per line):'

DEFAULT_INDUCTION_PROMPT = (
    'You read one fragment of a geological document and list the domain terms it uses.\n'
    'Return JSON only, as {"items": [...]}. Each item has:\n'
    '- "surface_form": the term exactly as written in the fragment;\n'
    '- "excerpt": a verbatim quote from the fragment that contains the term, at most two sentences;\n'
    '- "proposed_kind": one of class, relation, attribute, field, entity_scope, semantic_family, layer_role;\n'
    '- "proposed_class": optional, the term_id of a class term from the seed below that the term is an instance '
    'or kind of;\n'
    '- "suggested_seed_term_id": optional, the term_id of the seed term below that the term names or is a '
    'variant of.\n'
    'Copy the excerpt character for character from the fragment; never paraphrase, translate or shorten words. '
    'Use only term_id values that appear in the seed. Omit an optional key rather than guess it. '
    'Return {"items": []} when the fragment uses no domain terms.'
)


@dataclass(frozen=True)
class PinnedSeed:
    """The verified seed and proposal schema."""

    seed_id: str
    sha256: str
    terms: tuple[Mapping[str, Any], ...]
    proposal_schema: Mapping[str, Any]


@dataclass(frozen=True)
class SeedIndex:
    """Seed terms by normalised label, and the id sets the guards and the merge read."""

    by_form: Mapping[str, tuple[str, ...]]
    term_ids: frozenset[str]
    class_term_ids: frozenset[str]
    lexical_term_ids: tuple[str, ...]
    kind_by_term_id: Mapping[str, str]
    unlabelled_count: int


def _verified(assets: Path, name: str, recorded: Mapping[str, Any]) -> bytes:
    entry = recorded.get(name)
    if not isinstance(entry, Mapping):
        raise PinnedAssetMismatch(f'{name} has no provenance record')
    try:
        raw = (assets / name).read_bytes()
    except OSError as exc:
        raise PinnedAssetMismatch(f'{name} cannot be read: {exc}') from exc
    if len(raw) != entry.get('bytes') or hashlib.sha256(raw).hexdigest() != entry.get('sha256'):
        raise PinnedAssetMismatch(
            f'{name} does not match its recorded digest; the copy has drifted from '
            f'{entry.get("source_repository")}@{entry.get("source_commit")}'
        )
    return raw


def load_pinned_seed(assets: Path | None = None) -> PinnedSeed:
    """Load the seed and the proposal schema, verifying both against `provenance.json`.

    Raises `PinnedAssetMismatch` naming the file when a digest, a byte count, the seed id or the
    term count differs from the record.
    """
    root = assets or ASSETS
    try:
        recorded = json.loads((root / PROVENANCE_FILE).read_text(encoding='utf-8'))['files']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PinnedAssetMismatch(f'{PROVENANCE_FILE} cannot be read: {exc}') from exc
    seed_raw = _verified(root, SEED_FILE, recorded)
    schema_raw = _verified(root, PROPOSAL_SCHEMA_FILE, recorded)
    seed = json.loads(seed_raw.decode('utf-8'))
    entry = recorded[SEED_FILE]
    if seed.get('seed_id') != entry.get('seed_id') or len(seed.get('terms') or ()) != entry.get('terms'):
        raise PinnedAssetMismatch(f'{SEED_FILE} seed_id or term count does not match its provenance record')
    return PinnedSeed(
        seed_id=seed['seed_id'],
        sha256=entry['sha256'],
        terms=tuple(seed['terms']),
        proposal_schema=json.loads(schema_raw.decode('utf-8')),
    )


def build_seed_index(terms: Iterable[Mapping[str, Any]], normalize: Callable[[str], str]) -> SeedIndex:
    """Index every seed term by the normalised form of its `label` and each `labels_ru` entry."""
    forms: dict[str, set[str]] = {}
    term_ids: set[str] = set()
    class_ids: set[str] = set()
    lexical: set[str] = set()
    kinds: dict[str, str] = {}
    total = 0
    for term in terms:
        total += 1
        term_id = term['term_id']
        term_ids.add(term_id)
        kinds[term_id] = term['kind']
        if term['kind'] == 'class':
            class_ids.add(term_id)
        labels_ru = list(term.get('labels_ru') or ())
        if labels_ru:
            lexical.add(term_id)
        for label in [term['label'], *labels_ru]:
            form = normalize(label)
            if form:
                forms.setdefault(form, set()).add(term_id)
    return SeedIndex(
        by_form={form: tuple(sorted(ids)) for form, ids in forms.items()},
        term_ids=frozenset(term_ids),
        class_term_ids=frozenset(class_ids),
        lexical_term_ids=tuple(sorted(lexical)),
        kind_by_term_id=kinds,
        unlabelled_count=total - len(lexical),
    )


def seed_block(terms: Iterable[Mapping[str, Any]]) -> str:
    """The seed subset the model sees: class, layer-role, entity-scope and semantic-family terms.

    One compact JSON object per line with `term_id`, `label`, `labels_ru` and `description` where
    present, in seed order. The same terms give the same bytes.
    """
    lines = []
    for term in terms:
        if term.get('kind') not in PROMPT_KINDS:
            continue
        shown = {key: term[key] for key in PROMPT_TERM_KEYS if key in term}
        lines.append(json.dumps(shown, ensure_ascii=False, separators=(',', ':')))
    return '\n'.join(lines)


def system_prompt(prompt: str, block: str) -> str:
    """The system message of every call in a run: the induction prompt, then the seed block."""
    return f'{prompt}\n\n{SEED_BLOCK_HEADER}\n{block}'


def prompt_sha256(prompt: str) -> str:
    """SHA-256 of the induction prompt text encoded as UTF-8."""
    return hashlib.sha256(prompt.encode('utf-8')).hexdigest()
