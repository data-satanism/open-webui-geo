import logging
from typing import Any

from open_webui.models.files import Files

log = logging.getLogger(__name__)

DOCUMENT_CONTEXT_MAX_CHARS = 110
DOCUMENT_CONTEXT_METADATA_KEY = "document_context"
DOCUMENT_CONTEXT_CUSTOM_FIELDS_KEY = "custom_fields"
DOCUMENT_CONTEXT_CUSTOM_FIELDS_CONTEXT_KEY = "context"


from openai import OpenAI

DEFAULT_BASE_URL = "http://87.228.65.110:11435/v1"
DEFAULT_MODEL = "granite4:1b"
DEFAULT_API_KEY = "sk-no-key-needed"


def create_client(base_url: str = DEFAULT_BASE_URL, api_key: str = DEFAULT_API_KEY) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=api_key)


def request_model(
    prompt: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    api_key: str = DEFAULT_API_KEY,
    temperature: float = 0.7,
    max_tokens: int = 512,
) -> str:
    client = create_client(base_url=base_url, api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""



def normalize_document_context_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def build_document_context(text: str, limit: int = DOCUMENT_CONTEXT_MAX_CHARS) -> str:
    normalized_text = normalize_document_context_text(text)
    if not normalized_text:
        return ""

    if len(normalized_text) <= limit:
        return normalized_text

    return normalized_text[:limit].rstrip()


def get_file_document_context(file_id: str) -> str:
    if not file_id:
        return ""

    try:
        file = Files.get_file_by_id(file_id)
        if not file or not file.data:
            return ""
        requst = f"""По возможности извлеки из приведенного контекста:
        {build_document_context(file.data.get("content", ""))}
        Следуюбщую информацию о документе, если она доступна:
            - название документа
            - год
            - авторов
        И верни в виде json объекта с полями "title", "year", "authors". Если информация недоступна, верни пустой объект.
        """
        return request_model(requst)
    except Exception as e:
        log.debug(f"Failed to build document context for file {file_id}: {e}")
        return ""


def get_metadata_document_context(metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}

    custom_fields = metadata.get(DOCUMENT_CONTEXT_CUSTOM_FIELDS_KEY)
    if isinstance(custom_fields, dict):
        custom_context = build_document_context(
            custom_fields.get(DOCUMENT_CONTEXT_CUSTOM_FIELDS_CONTEXT_KEY, "")
        )
        if custom_context:
            return custom_context

    legacy_context = build_document_context(metadata.get(DOCUMENT_CONTEXT_METADATA_KEY, ""))
    if legacy_context:
        return legacy_context

    return ""


def set_metadata_document_context(metadata: dict[str, Any], context: str) -> dict[str, Any]:
    enriched_metadata = dict(metadata or {})
    custom_fields = enriched_metadata.get(DOCUMENT_CONTEXT_CUSTOM_FIELDS_KEY)
    custom_fields = dict(custom_fields) if isinstance(custom_fields, dict) else {}

    custom_fields[DOCUMENT_CONTEXT_CUSTOM_FIELDS_CONTEXT_KEY] = context
    enriched_metadata[DOCUMENT_CONTEXT_CUSTOM_FIELDS_KEY] = custom_fields
    enriched_metadata[DOCUMENT_CONTEXT_METADATA_KEY] = context

    return enriched_metadata


def resolve_document_context(
    document: str,
    metadata: dict[str, Any] | None = None,
    context_cache: dict[str, str] | None = None,
) -> str:
    metadata = metadata or {}

    existing_context = get_metadata_document_context(metadata)
    if existing_context:
        return existing_context

    file_id = metadata.get("file_id")
    if file_id:
        if context_cache is not None:
            if file_id not in context_cache:
                context_cache[file_id] = get_file_document_context(file_id)
            context = context_cache[file_id]
        else:
            context = get_file_document_context(file_id)

        if context:
            return context

    return build_document_context(document)


def enrich_metadata_with_document_context(
    document: str,
    metadata: dict[str, Any] | None = None,
    context_cache: dict[str, str] | None = None,
) -> dict[str, Any]:
    enriched_metadata = dict(metadata or {})
    context = resolve_document_context(document, enriched_metadata, context_cache)

    if context:
        enriched_metadata = set_metadata_document_context(enriched_metadata, context)

    return enriched_metadata


def enrich_documents_metadata_with_context(
    documents: list[str], metadatas: list[dict]
) -> tuple[list[str], list[dict]]:
    if not documents or not metadatas:
        return documents, metadatas

    enriched_metadatas = []
    context_cache: dict[str, str] = {}

    for document, metadata in zip(documents, metadatas):
        enriched_metadatas.append(
            enrich_metadata_with_document_context(document, metadata, context_cache)
        )

    return documents, enriched_metadatas


def enrich_query_result_with_document_context(query_result: dict[str, Any]) -> dict[str, Any]:
    if not query_result:
        return query_result

    documents = query_result.get("documents") or []
    metadatas = query_result.get("metadatas") or []

    if not documents or not metadatas or not documents[0] or not metadatas[0]:
        return query_result

    enriched_documents, enriched_metadatas = enrich_documents_metadata_with_context(
        documents[0], metadatas[0]
    )

    return {
        **query_result,
        "documents": [enriched_documents],
        "metadatas": [enriched_metadatas],
    }


def enrich_result_object_with_document_context(result: Any) -> Any:
    if (
        not result
        or not hasattr(result, "documents")
        or not hasattr(result, "metadatas")
        or not result.documents
        or not result.metadatas
    ):
        return result

    for batch_index, (documents, metadatas) in enumerate(zip(result.documents, result.metadatas)):
        _, enriched_metadatas = enrich_documents_metadata_with_context(documents, metadatas)
        result.metadatas[batch_index] = enriched_metadatas

    return result