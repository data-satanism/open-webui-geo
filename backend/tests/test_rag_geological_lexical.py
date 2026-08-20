from open_webui.retrieval.lexical import (
    LegacyLexicalIndexCache,
    geological_lexical_tokens,
    normalize_geological_text,
)


def test_normalization_handles_unicode_dashes_yo_and_mixed_script_ocr():
    assert normalize_geological_text('Медно‑порфировая рyда, Ёлкин') == ('медно порфировая руда елкин')


def test_pure_latin_identifiers_are_not_rewritten():
    assert normalize_geological_text('Au Cu P1') == 'au cu p1'


def test_tokens_add_controlled_aliases_and_conservative_morphology():
    tokens = geological_lexical_tokens('Выполнены геолого-разведочные работы')
    assert 'грр' in tokens
    assert '__stem_разведочн' in tokens
    assert 'работы' in tokens


def test_cache_reuses_entry_and_expires_deterministically():
    now = [100.0]
    cache = LegacyLexicalIndexCache(
        max_entries=2,
        ttl_seconds=10,
        clock=lambda: now[0],
    )
    cache.put(
        'collection-a',
        True,
        collection_result='result',
        retriever='bm25',
        original_text_by_hash={'hash': 'text'},
    )
    assert cache.get('collection-a', True).retriever == 'bm25'
    now[0] = 111.0
    assert cache.get('collection-a', True) is None
    assert cache.stats() == {'entries': 0, 'hits': 1, 'misses': 1}


def test_cache_invalidates_both_enrichment_variants():
    cache = LegacyLexicalIndexCache(max_entries=3, ttl_seconds=10)
    for enriched in (False, True):
        cache.put(
            'collection-a',
            enriched,
            collection_result='result',
            retriever='bm25',
            original_text_by_hash={},
        )
    cache.invalidate('collection-a')
    assert cache.stats()['entries'] == 0
