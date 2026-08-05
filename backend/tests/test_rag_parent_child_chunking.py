from __future__ import annotations

import json

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from open_webui.retrieval.chunking import (
    documents_have_parent_child_lineage,
    expand_parent_context_result,
    extract_parent_child_ingestion_metadata,
    finalize_child_documents,
    prepare_parent_documents,
    preserve_split_metadata,
    split_parent_documents,
)


def test_uploaded_geomas_metadata_is_allowlisted_and_normalized() -> None:
    metadata = extract_parent_child_ingestion_metadata(
        {
            'document_id': 'top-level-is-overridden',
            'data': {
                'document_id': ' source-file-1 ',
                'document_version': 'sha256-version',
                'object_ids': [' Lekyn ', 'Lekyn', '', 42],
                'domain_facets': '["resources", "technology"]',
                'source_class': 'technical_report',
                'temporal_role': 'historical_actual',
                'page': 999,
                'file_id': 'foreign-file',
                '_rag_parent_text': 'forged parent',
                'annotation_spans': [{'start': 0, 'end': 10}],
            },
        }
    )

    assert metadata == {
        'document_id': 'source-file-1',
        'document_version': 'sha256-version',
        'object_ids': ['Lekyn'],
        'domain_facets': ['resources', 'technology'],
        'source_class': 'technical_report',
        'temporal_role': 'historical_actual',
    }


def test_unknown_enums_and_unsafe_locator_metadata_are_rejected() -> None:
    metadata = extract_parent_child_ingestion_metadata(
        {
            'data': {
                'source_class': 'arbitrary_source',
                'temporal_role': 'sometime',
                'page_label': 500,
                'atomic_ranges': [{'start': 0, 'end': 50}],
            }
        }
    )

    assert metadata == {}


def test_markdown_header_metadata_is_preserved_in_section_path() -> None:
    text = '# Deposit\n\n## Resources\n\nC1: 12 t'
    evidence_start = text.index('C1')
    source = Document(
        page_content=text,
        metadata={
            'file_id': 'file-1',
            'annotation_spans': [
                {'start': evidence_start, 'end': len(text), 'labels': ['resources']},
            ],
        },
    )
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[('#', 'Header 1'), ('##', 'Header 2')],
        strip_headers=False,
    )
    sections = preserve_split_metadata(source, splitter.split_text(source.page_content))
    parents = prepare_parent_documents(sections)

    assert sections[-1].metadata['Header 1'] == 'Deposit'
    assert sections[-1].metadata['Header 2'] == 'Resources'
    assert parents[-1].metadata['section_path'] == 'Deposit > Resources'
    assert sections[-1].metadata['annotation_locator_status'] == 'located'
    assert sections[-1].metadata['annotation_spans'][0]['start'] == sections[-1].page_content.index('C1')


def test_parent_and_child_ids_are_stable_and_have_no_orphans() -> None:
    first = Document(page_content='A' * 80, metadata={'file_id': 'a', 'hash': 'version-a', 'page': 3})
    second = Document(page_content='B' * 80, metadata={'file_id': 'b', 'hash': 'version-b', 'page': 4})
    forward = prepare_parent_documents([first, second])
    reverse = prepare_parent_documents([second, first])
    assert {item.page_content: item.metadata['parent_chunk_id'] for item in forward} == {
        item.page_content: item.metadata['parent_chunk_id'] for item in reverse
    }

    splitter = RecursiveCharacterTextSplitter(chunk_size=30, chunk_overlap=5, add_start_index=True)
    children = split_parent_documents(forward, splitter)
    parent_ids = {parent.metadata['parent_chunk_id'] for parent in forward}
    assert children
    assert all(child.metadata['parent_chunk_id'] in parent_ids for child in children)
    assert len({child.metadata['child_chunk_id'] for child in children}) == len(children)
    assert all(child.metadata['document_id'] and child.metadata['document_version'] for child in children)
    assert all(child.metadata['page'] in {3, 4} for child in children)
    assert documents_have_parent_child_lineage(children) is True
    assert documents_have_parent_child_lineage(forward) is False


def test_mistral_page_label_is_used_for_citations_and_raw_index_is_preserved() -> None:
    parent = prepare_parent_documents(
        [Document(page_content='first page', metadata={'file_id': 'mistral', 'page': 0, 'page_label': 1})]
    )[0]

    assert parent.metadata['page'] == 1
    assert parent.metadata['source_page_index'] == 0
    assert parent.metadata['page_locator_status'] == 'provided'


def test_overlapping_annotations_form_union_facets_without_disjoint_projection() -> None:
    annotations = [
        {'start': 0, 'end': 12, 'labels': ['resources']},
        {'start': 5, 'end': 18, 'labels': ['geology']},
    ]
    source = Document(
        page_content='0123456789abcdefghij',
        metadata={'file_id': 'facets', 'annotation_spans': json.dumps(annotations)},
    )
    parent = prepare_parent_documents([source])[0]
    child = Document(page_content=source.page_content[4:14], metadata={'start_index': 4})
    result = finalize_child_documents(parent, [child])[0]

    assert json.loads(result.metadata['child_domain_facets']) == ['geology', 'resources']
    assert json.loads(result.metadata['child_facet_coverage']) == {'geology': 1, 'resources': 1}

    outside = finalize_child_documents(
        parent,
        [Document(page_content=source.page_content[18:20], metadata={'start_index': 18})],
    )[0]
    assert json.loads(outside.metadata['child_domain_facets']) == []


def test_atomic_resource_row_is_not_cut_at_child_boundary() -> None:
    text = 'prefix\nquantity=12; grade=4.1; cutoff=1.0; year=2024\nsuffix'
    row_start = text.index('quantity')
    row_end = text.index('\nsuffix')
    parent = prepare_parent_documents(
        [
            Document(
                page_content=text, metadata={'file_id': 'rows', 'atomic_ranges': [{'start': row_start, 'end': row_end}]}
            )
        ]
    )[0]
    partial = Document(page_content=text[row_start + 5 : row_start + 15], metadata={'start_index': row_start + 5})
    child = finalize_child_documents(parent, [partial])[0]

    assert child.metadata['start_index'] == row_start
    assert child.metadata['end_index'] == row_end
    assert child.page_content == text[row_start:row_end]


def test_parent_context_is_bounded_and_returned_after_child_ranking() -> None:
    text = 'A' * 200 + 'TARGET' + 'B' * 200
    parent = prepare_parent_documents([Document(page_content=text, metadata={'file_id': 'bounded'})])[0]
    child = finalize_child_documents(
        parent,
        [Document(page_content='TARGET', metadata={'start_index': 200})],
        max_parent_context_chars=60,
    )[0]
    result = expand_parent_context_result(
        {
            'documents': [[child.page_content, child.page_content]],
            'metadatas': [[child.metadata, child.metadata]],
            'distances': [[0.9, 0.8]],
        }
    )

    assert len(result['documents'][0]) == 1
    assert len(result['documents'][0][0]) == 60
    assert 'TARGET' in result['documents'][0][0]
    assert result['metadatas'][0][0]['context_expanded_to_parent'] is True
    assert result['distances'][0] == [0.9]
