import { useCallback, useState } from "react";

import { API_ENDPOINTS, APP_CONFIG } from "../config/endpoint";
import { apiRequest } from "../api/client";
import { normalizeSearchResponse } from "../utils/normal";
import { logError } from "../utils/logger";

export default function useSearch() {
  const [messages, setMessages] = useState([]);
  const [isSearching, setIsSearching] = useState(false);

  const sendQuestion = useCallback(
    async (question) => {
      const prompt = question.trim();

      if (!prompt || isSearching) {
        return;
      }

      const requestId =
        typeof crypto !== "undefined" &&
        typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random()}`;

      const userMessage = {
        id: `${requestId}-user`,
        role: "user",
        content: prompt,
      };

      setMessages((current) => [...current, userMessage]);
      setIsSearching(true);

      try {
        const payload = await apiRequest(API_ENDPOINTS.search, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            [APP_CONFIG.searchField]: prompt,
          }),
        });

        const result = normalizeSearchResponse(payload);

        const assistantMessage = {
          id: `${requestId}-assistant`,
          role: "assistant",
          question: prompt,
          answer: result.answer,
          results: result.results,
        };

        setMessages((current) => [
          ...current,
          assistantMessage,
        ]);
      } catch (error) {
        logError("Document search failed", {
          message: error.message,
        });

        setMessages((current) => [
          ...current,
          {
            id: `${requestId}-assistant-error`,
            role: "assistant",
            question: prompt,
            answer: "",
            results: [],
            error: error.message,
          },
        ]);
      } finally {
        setIsSearching(false);
      }
    },
    [isSearching]
  );

  const clearConversation = useCallback(() => {
    setMessages([]);
  }, []);

  return {
    messages,
    isSearching,
    sendQuestion,
    clearConversation,
  };
}