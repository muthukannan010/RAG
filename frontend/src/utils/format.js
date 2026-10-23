export function formatBytes(value) {
  if (value == null || !Number.isFinite(Number(value))) {
    return "";
  }

  const bytes = Number(value);

  if (bytes < 1024) {
    return `${bytes} B`;
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatPercent(value) {
  if (value == null || value === "") {
    return "—";
  }

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return String(value);
  }

  // Support either a ratio (0–1) or percentage (0–100).
  const percentage =
    number >= 0 && number <= 1
      ? number * 100
      : number;

  return `${percentage.toFixed(
    Number.isInteger(percentage) ? 0 : 2
  )}%`;
}

export function formatDate(value) {
  if (!value) {
    return "—";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleString();
}