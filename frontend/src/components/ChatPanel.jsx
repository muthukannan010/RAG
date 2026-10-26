import { useEffect, useRef } from "react";
import Icon from "./Icon.jsx";
import SourceCard from "./SourceCard.jsx";

export default function ChatPanel({
  messages,
  question,
  onQuestionChange,
  onSendQuestion,
  isSearching,
  isBusy,
  onUploadClick,
  onOpenSource,
  onNewConversation,
  apiStatus,
  settingsOpen,
  onToggleSettings,
}) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages, isSearching]);

  function handleSubmit(event) {
    event.preventDefault();

    const prompt = question.trim();

    if (!prompt || isBusy) {
      return;
    }

    onQuestionChange("");
    void onSendQuestion(prompt);
  }

  function handleKeyDown(event) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      handleSubmit(event);
    }
  }

  return (
    <main className="chat-panel">


      <div className="chat-scroll">
        {messages.length === 0 ? (
          <div className="welcome-state">

            <h2>Ask your documents anything.</h2>

            <p>
              Search your uploaded PDFs and explore the passages
              that support the results.
            </p>

            <span>
              Try asking a question in the box below.
            </span>
          </div>
        ) : (
          <div className="conversation">
            {messages.map((message) =>
              message.role === "user" ? (
                <div
                  className="user-message-row"
                  key={message.id}
                >
                  <div className="user-message">
                    {message.content}
                  </div>
                </div>
              ) : (
                <article
                  className="assistant-message"
                  key={message.id}
                >
                  {message.error ? (
                    <div className="chat-error">
                      <strong>Search failed</strong>
                      <p>{message.error}</p>
                    </div>
                  ) : (
                    <>
                      {message.answer && (
                        <p className="assistant-answer">
                          {message.answer}
                        </p>
                      )}

                      {message.results.map((source, index) => (
                        <SourceCard
                          key={`${message.id}-${source.id}-${index}`}
                          source={source}
                          question={message.question}
                          onOpenSource={onOpenSource}
                        />
                      ))}

                      {message.results.length === 0 &&
                        !message.answer && (
                          <div className="no-results">
                            No answer or source passages were returned
                            by the search service.
                          </div>
                        )}
                    </>
                  )}
                </article>
              )
            )}

            {isSearching && (
              <div
                className="searching-indicator"
                role="status"
              >
                <span className="tiny-spinner" />
                Searching your documents...
              </div>
            )}

            <div ref={endRef} />
          </div>
        )}
      </div>

      <div className="composer-area">
        <form className="composer" onSubmit={handleSubmit}>
          <button
            className="composer-attach"
            type="button"
            title="Upload a PDF"
            aria-label="Upload a PDF"
            onClick={onUploadClick}
            disabled={isBusy}
          >
            <Icon name="clip" size={24} />
          </button>

          <textarea
            rows={1}
            value={question}
            onChange={(event) =>
              onQuestionChange(event.target.value)
            }
            onKeyDown={handleKeyDown}
            placeholder="Ask something..."
            aria-label="Ask a question about your documents"
            disabled={isSearching}
          />

          <button
            className="composer-send"
            type="submit"
            title="Send question"
            aria-label="Send question"
            disabled={!question.trim() || isBusy}
          >
            <Icon name="send" size={21} />
          </button>
        </form>

        <p className="composer-hint">
          Press Enter to send, Shift + Enter for new line
        </p>
      </div>
    </main>
  );
}
