import { useMemo } from "react";

const STOP_WORDS = new Set([
  "what", "when", "where", "which", "who", "does",
  "that", "this", "with", "from", "have", "your",
  "their", "about", "into", "were", "will", "would",
  "could", "should", "the", "and", "are", "was",
  "for", "how", "can",
]);

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export default function HighlightText({ text, question }) {
  const parts = useMemo(() => {
    if (!text) {
      return [];
    }

    const terms = [
      ...new Set(
        (question.match(/[a-z0-9-]+/gi) || [])
          .map((term) => term.toLowerCase())
          .filter(
            (term) =>
              term.length > 2 && !STOP_WORDS.has(term)
          )
      ),
    ].sort((a, b) => b.length - a.length);

    if (terms.length === 0) {
      return [text];
    }

    const expression = new RegExp(
      `\\b(${terms.map(escapeRegex).join("|")})\\b`,
      "gi"
    );

    const matchedTerms = new Set(terms);

    return text.split(expression).map((part, index) => ({
      text: part,
      highlight: matchedTerms.has(part.toLowerCase()),
      key: `${index}-${part}`,
    }));
  }, [text, question]);

  return (
    <>
      {parts.map((part, index) =>
        typeof part === "string" ? (
          <span key={`${index}-${part}`}>{part}</span>
        ) : part.highlight ? (
          <mark key={part.key}>{part.text}</mark>
        ) : (
          <span key={part.key}>{part.text}</span>
        )
      )}
    </>
  );
}