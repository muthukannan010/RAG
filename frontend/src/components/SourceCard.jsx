import { useState } from "react";

import HighlightText from "./HighlightText.jsx";
import Icon from "./Icon.jsx";

export default function SourceCard({
  source,
  question,
  onOpenSource,
}) {
  const [showRetrievedRank, setShowRetrievedRank] = useState(false);

  function formatScore(value, digits = 3) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) {
      return "—";
    }

    return Number(value).toFixed(digits);
  }

  const hasPage =
    source.page != null &&
    Number.isFinite(Number(source.page));

  return (
    <section className="source-card">
      <div className="source-top-line" />

      <button
        type="button"
        className="source-rank-toggle"
        onClick={() =>
          setShowRetrievedRank((visible) => !visible)
        }
        aria-label={
          showRetrievedRank
            ? "Hide original semantic retrieval rank"
            : "Show original semantic retrieval rank"
        }
        aria-expanded={showRetrievedRank}
        title={
          showRetrievedRank
            ? "Hide original semantic retrieval rank"
            : "Show original semantic retrieval rank"
        }
      >
        <Icon
          name={showRetrievedRank ? "eyeOff" : "eye"}
          size={18}
        />
      </button>

      <div className="source-meta">
        {source.sourceRef && (
          <button
            type="button"
            className="source-reference"
            onClick={() => onOpenSource(source)}
            disabled={!hasPage}
            title={`Open cited page ${source.page ?? ""}`}
          >
            [{source.sourceRef}]
          </button>
        )}

        <span className="source-filename">
          {source.filename}
        </span>

        {hasPage && (
          <span>(Page {source.page})</span>
        )}
      </div>

      <div className="score-line">
        Similarity Rank:{" "}
        <strong>
          {source.displayRank == null
            ? "—"
            : `#${source.displayRank}`}
        </strong>
      </div>

      <div className="score-line">
        Keyword Rank:{" "}
        <strong>
          {source.keywordRank == null
            ? "—"
            : `#${source.keywordRank}`}
        </strong>
      </div>

      <div className="score-line">
        Keyword Score (BM25):{" "}
        <strong>{formatScore(source.keywordScore, 4)}</strong>
      </div>

      <div className="score-line">
        Cosine Similarity:{" "}
        <strong>{formatScore(source.semantic)}</strong>
      </div>

      {showRetrievedRank && (
        <div className="score-line retrieved-rank">
          Original Semantic Rank:{" "}
          <strong>
            {source.semanticRank == null
              ? "—"
              : `#${source.semanticRank}`}
          </strong>
        </div>
      )}

      <div className="score-line">
        Hybrid RRF Score:{" "}
        <strong>
          {source.hybridScore == null
            ? "—"
            : Number(source.hybridScore).toFixed(6)}
        </strong>
      </div>

      {source.quotedText && (
        <blockquote className="citation-quote">
          <strong>Supporting passage</strong>
          <p>{source.quotedText}</p>
        </blockquote>
      )}

      {source.text && (
        <p className="source-snippet">
          <HighlightText
            text={source.text}
            question={question}
          />
        </p>
      )}

      <div className="source-actions">
        <button
          type="button"
          className="view-page-button"
          onClick={() => onOpenSource(source)}
          disabled={!hasPage}
        >
          [ View Page {source.page ?? "—"} ]
        </button>
      </div>
    </section>
  );
}