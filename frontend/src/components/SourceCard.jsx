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
        <span className="source-filename">
          {source.filename}
        </span>

        {hasPage && (
          <span>(Page {source.page})</span>
        )}
      </div>

      <div className="score-line">
        Keyword Match:{" "}
        <strong>{formatPercent(source.keyword)}</strong>
      </div>

      <div className="score-line">
        Semantic Match:{" "}
        <strong>{formatPercent(source.semantic)}</strong>
      </div>

      <div className="score-line">
        Final Relevance:{" "}
        <strong>{formatPercent(source.relevance)}</strong>
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