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
  const structuralMetadata = item.structural_metadata ?? null;
  const embeddedLocatorMapping =
    item.locator_mapping ??
    metadata.locator_mapping ??
    structuralMetadata?.locator_mapping ??
    (
      structuralMetadata &&
      typeof structuralMetadata === "object" &&
      !Array.isArray(structuralMetadata) &&
      (
        "mapping_status" in structuralMetadata ||
        "locator_segments" in structuralMetadata
      )
        ? structuralMetadata
        : null
    );
  const locatorSegments =
    item.locator_segments ??
    item.locatorSegments ??
    embeddedLocatorMapping?.locator_segments ??
    structuralMetadata?.locator_segments ??
    null;
  const versionId =
    item.version_id ??
    item.document_version_id ??
    item.versionId ??
    metadata.version_id ??
    embeddedLocatorMapping?.document_version_id ??
    structuralMetadata?.document_version_id ??
    locatorSegments?.[0]?.document_version_id ??
    null;
  const locatorMappingStatus =
    item.locator_mapping_status ??
    item.locatorMappingStatus ??
    embeddedLocatorMapping?.mapping_status ??
    structuralMetadata?.locator_mapping_status ??
    null;
  const filename =
    item.filename ??
    item.document_name ??
    item.source ??
    metadata.filename ??
    metadata.source ??
    "Source document";
  const basename =
    typeof filename === "string"
      ? filename.replace(/\\/g, "/").split("/").pop() || ""
      : "";
  const isDocx = basename.toLowerCase().endsWith(".docx");
  const docxLocatorNavigable =
    isDocx &&
    versionId != null &&
    locatorMappingStatus === "resolved" &&
    Array.isArray(locatorSegments) &&
    locatorSegments.length > 0 &&
    locatorSegments.every(
      (segment) =>
        segment?.mapping_status === "resolved" &&
        segment.document_version_id === versionId &&
        Array.isArray(segment.structural_path) &&
        segment.structural_path.length > 0 &&
        Number.isInteger(segment.text_range?.start) &&
        Number.isInteger(segment.text_range?.end) &&
        segment.text_range.start >= 0 &&
        segment.text_range.end > segment.text_range.start
    );

  return {
    displayRank: index + 1,

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

    filename,
    isPdf: basename.toLowerCase().endsWith(".pdf"),
    isDocx,

    page:
      item.page_number ??
      item.page ??
      metadata.page_number ??
      metadata.page ??
      null,

    keyword:
      item.keyword_match_percent ??
      item.keyword_match ??
      metadata.keyword_match ??
      null,

    keywordScore:
      item.keyword_score ??
      metadata.keyword_score ??
      null,

    keywordRank:
      item.keyword_rank ??
      metadata.keyword_rank ??
      null,

    semantic:
      item.semantic_match_percent ??
      item.semantic_match ??
      item.semantic_score ??
      metadata.semantic_match ??
      null,

    semanticRank:
      item.semantic_rank ??
      metadata.semantic_rank ??
      null,

    hybridScore:
      item.hybrid_score ??
      metadata.hybrid_score ??
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
    sourceRef:
      item.source_ref ??
      item.sourceRef ??
      null,
    quotedText:
      item.quoted_text ??
      item.quotedText ??
      null,
    versionId,
    structuralMetadata,
    locatorMappingStatus,
    locatorSegments,
    docxLocatorNavigable,
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