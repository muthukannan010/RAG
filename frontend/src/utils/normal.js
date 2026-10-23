export function extractDocuments(payload) {
  if (Array.isArray(payload)) {
    return payload;
  }

  if (Array.isArray(payload?.documents)) {
    return payload.documents;
  }

  if (Array.isArray(payload?.items)) {
    return payload.items;
  }

  if (Array.isArray(payload?.data)) {
    return payload.data;
  }

  return [];
}

export function normalizeDocument(item) {
  const rawId =
    item.document_id ??
    item.id ??
    item.documentId ??
    item.uuid ??
    null;

  return {
    id: rawId == null ? null : String(rawId),

    filename:
      item.filename ??
      item.original_filename ??
      item.document_name ??
      item.name ??
      "Untitled PDF",

    pages:
      item.page_count ??
      item.pages ??
      null,

    bytes:
      item.size_bytes ??
      item.file_size ??
      item.size ??
      null,

    chunkCount:
      item.chunk_count ??
      item.chunks_count ??
      null,

    uploadedAt:
      item.uploaded_at ??
      item.created_at ??
      item.updated_at ??
      null,

    status:
      item.status ??
      "Available",
  };
}

export function extractSearchResults(payload) {
  const data = payload?.data ?? payload;

  if (Array.isArray(data)) {
    return data;
  }

  return (
    data?.results ??
    data?.sources ??
    data?.chunks ??
    data?.items ??
    []
  );
}

export function normalizeSource(item, index = 0) {
  const metadata = item.metadata ?? {};

  return {
    id: String(
      item.id ??
      item.chunk_id ??
      index
    ),

    documentId:
      item.document_id ??
      item.doc_id ??
      metadata.document_id ??
      null,

    filename:
      item.filename ??
      item.document_name ??
      item.source ??
      metadata.filename ??
      metadata.source ??
      "Source document",

    page:
      item.page_number ??
      item.page ??
      metadata.page_number ??
      metadata.page ??
      null,

    keyword:
      item.keyword_match_percent ??
      item.keyword_match ??
      item.keyword_score ??
      metadata.keyword_match ??
      null,

    semantic:
      item.semantic_match_percent ??
      item.semantic_match ??
      item.semantic_score ??
      metadata.semantic_match ??
      null,

    relevance:
      item.final_relevance ??
      item.final_score ??
      item.relevance_score ??
      item.score ??
      null,

    text:
      item.snippet ??
      item.content ??
      item.chunk_text ??
      item.text ??
      item.page_content ??
      "",

    fileUrl:
      item.file_url ??
      item.pdf_url ??
      metadata.file_url ??
      null,
  };
}

export function normalizeSearchResponse(payload) {
  const data = payload?.data ?? payload;

  const answer =
    data?.answer ??
    data?.generated_answer ??
    data?.response ??
    "";

  const sources = extractSearchResults(payload);

  return {
    answer: typeof answer === "string" ? answer : "",
    results: sources.map(normalizeSource),
  };
}