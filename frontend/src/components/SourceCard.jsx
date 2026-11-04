import Icon from "./Icon.jsx";
import HighlightText from "./HighlightText.jsx";
import { formatPercent } from "../utils/format.js";

export default function SourceCard({
  source,
  question,
  onOpenSource,
}) {
  const hasPage =
    source.page != null &&
    Number.isFinite(Number(source.page));

  return (
    <section className="source-card">
      <div className="source-top-line" />

      <div className="source-meta">
        <div className="source-meta">
  {source.sourceRef && (
    <strong className="source-reference">
      [{source.sourceRef}]
    </strong>
  )}

  <span className="source-filename">
    {source.filename}
  </span>

  {source.page != null && (
    <span>(Page {source.page})</span>
  )}
</div>
        <span className="source-filename">
          {source.filename}
        </span>

        {hasPage && (
          <span>(Page {source.page})</span>
        )}
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
        Semantic Similarity:{" "}
        <strong>{formatPercent(source.semantic)}</strong>
      </div>

      <div className="score-line">
        Semantic Rank:{" "}
        <strong>
          {source.semanticRank == null
            ? "—"
            : `#${source.semanticRank}`}
        </strong>
      </div>

      <div className="score-line">
        Hybrid RRF Score:{" "}
        <strong>
          {source.hybridScore == null
            ? "—"
            : Number(source.hybridScore).toFixed(6)}
        </strong>
      </div>

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