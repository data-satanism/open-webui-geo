"""Controlled lexical normalization and a bounded legacy BM25 cache.

The normalization deliberately avoids unrestricted fuzzy matching.  It fixes
common Russian/OCR representation differences and adds conservative stems;
domain aliases remain an explicit, reviewable allowlist.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_DASHES = re.compile(r'[\u2010-\u2015\u2212\ufe58\ufe63\uff0d-]+')
_TOKEN = re.compile(r'[0-9a-zа-я]+', re.IGNORECASE)
_CYRILLIC = re.compile(r'[а-я]', re.IGNORECASE)
_LATIN = re.compile(r'[a-z]', re.IGNORECASE)
_LATIN_LOOKALIKES = str.maketrans(
    {
        'a': 'а',
        'b': 'в',
        'c': 'с',
        'e': 'е',
        'k': 'к',
        'm': 'м',
        'o': 'о',
        'p': 'р',
        't': 'т',
        'x': 'х',
        'y': 'у',
    }
)

# Keep this list short and auditable.  Adding a pair is a retrieval-policy
# change and must be evaluated against hard negatives before rollout.
GEOLOGICAL_ALIASES: Mapping[str, tuple[str, ...]] = {
    'геологоразведочные работы': ('грр',),
    'геолого разведочные работы': ('грр',),
    'золоторудный': ('золото рудный', 'au'),
    'меднопорфировый': ('медно порфировый', 'cu porphyry'),
    'прогнозные ресурсы': ('ресурсы p1 p2 p3',),
    'рудное золото': ('au',),
}

_CONSERVATIVE_RUSSIAN_SUFFIXES = (
    'иями',
    'ями',
    'ами',
    'ого',
    'ему',
    'ому',
    'ыми',
    'ими',
    'ией',
    'ий',
    'ый',
    'ая',
    'ое',
    'ые',
    'ов',
    'ев',
    'ам',
    'ям',
    'ах',
    'ях',
)


def normalize_geological_text(text: str) -> str:
    """Normalize Unicode, Russian ``ё`` and controlled OCR confusions."""

    normalized = unicodedata.normalize('NFKC', str(text)).casefold().replace('ё', 'е')
    normalized = _DASHES.sub(' ', normalized)
    tokens: list[str] = []
    for token in _TOKEN.findall(normalized):
        # Convert Latin lookalikes only inside mixed-script OCR tokens.  Pure
        # Latin identifiers such as Au, Cu, P1 and URLs remain untouched.
        if _CYRILLIC.search(token) and _LATIN.search(token):
            token = token.translate(_LATIN_LOOKALIKES)
        tokens.append(token)
    return ' '.join(tokens)


def _conservative_stem(token: str) -> str | None:
    if len(token) < 7 or not _CYRILLIC.search(token):
        return None
    for suffix in _CONSERVATIVE_RUSSIAN_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return None


def geological_lexical_tokens(
    text: str,
    *,
    aliases: Mapping[str, Sequence[str]] = GEOLOGICAL_ALIASES,
) -> list[str]:
    """Return exact plus conservative lexical features for BM25."""

    normalized = normalize_geological_text(text)
    tokens = normalized.split()
    features = list(tokens)
    for token in tokens:
        stem = _conservative_stem(token)
        if stem:
            features.append(f'__stem_{stem}')
    for phrase, expansions in aliases.items():
        normalized_phrase = normalize_geological_text(phrase)
        if normalized_phrase and normalized_phrase in normalized:
            for expansion in expansions:
                features.extend(normalize_geological_text(expansion).split())
    return features


@dataclass(frozen=True)
class LexicalIndexEntry:
    collection_result: Any
    retriever: Any
    original_text_by_hash: Mapping[str, str]
    built_at: float


class LegacyLexicalIndexCache:
    """Thread-safe TTL/LRU cache for legacy full-collection BM25 indexes."""

    def __init__(
        self,
        *,
        max_entries: int = 16,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1 or ttl_seconds <= 0:
            raise ValueError('lexical cache requires positive bounds')
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[tuple[str, bool], LexicalIndexEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, collection_name: str, enriched: bool) -> LexicalIndexEntry | None:
        key = (collection_name, enriched)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or self._clock() - entry.built_at >= self._ttl_seconds:
                if entry is not None:
                    del self._entries[key]
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return entry

    def put(
        self,
        collection_name: str,
        enriched: bool,
        *,
        collection_result: Any,
        retriever: Any,
        original_text_by_hash: Mapping[str, str],
    ) -> LexicalIndexEntry:
        key = (collection_name, enriched)
        entry = LexicalIndexEntry(
            collection_result=collection_result,
            retriever=retriever,
            original_text_by_hash=dict(original_text_by_hash),
            built_at=self._clock(),
        )
        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return entry

    def invalidate(self, collection_name: str | None = None) -> None:
        with self._lock:
            if collection_name is None:
                self._entries.clear()
                return
            for key in [key for key in self._entries if key[0] == collection_name]:
                del self._entries[key]

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                'entries': len(self._entries),
                'hits': self._hits,
                'misses': self._misses,
            }


LEGACY_LEXICAL_INDEX_CACHE = LegacyLexicalIndexCache()


def invalidate_legacy_lexical_cache(collection_name: str | None = None) -> None:
    LEGACY_LEXICAL_INDEX_CACHE.invalidate(collection_name)
