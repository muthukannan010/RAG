function getExtension(filename) {
  if (typeof filename !== "string") {
    return "";
  }

  const basename = filename.replace(/\\/g, "/").split("/").pop() || "";
  const separator = basename.lastIndexOf(".");
  return separator < 0 ? "" : basename.slice(separator).toLowerCase();
}

const ORIGINAL_PREVIEW_FORMATS = new Set([
  ".pptx",
  ".xlsx",
  ".txt",
  ".csv",
  ".md",
  ".markdown",
  ".html",
  ".htm",
  ".json",
  ".xml",
]);

export function getSourceFileFormat(source) {
  const extension = getExtension(source?.filename);
  return extension === ".markdown"
    ? "md"
    : extension === ".htm"
      ? "html"
      : extension.slice(1);
}

export function getSourceViewerType(source) {
  const extension = getExtension(source?.filename);

  if (source?.isPdf === true || extension === ".pdf") {
    return "pdf";
  }
  if (source?.isDocx === true || extension === ".docx") {
    return "docx";
  }
  if (ORIGINAL_PREVIEW_FORMATS.has(extension)) {
    return "preview";
  }
  return "passage";
}
