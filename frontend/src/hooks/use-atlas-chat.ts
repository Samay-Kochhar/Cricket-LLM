"use client";

import { useState } from "react";

import type { ChatHistoryTurn, ChatReply } from "@/lib/api-types";
import { getApiCandidates, postApi } from "@/lib/api-client";

type AtlasChatState = {
  isLoading: boolean;
  error: string | null;
  loadingLabel: string | null;
};

function traceClient(message: string, extra?: Record<string, unknown>) {
  const timestamp = new Date().toISOString();
  if (extra) {
    console.info(`[${timestamp}] [atlas] ${message}`, extra);
    return;
  }
  console.info(`[${timestamp}] [atlas] ${message}`);
}

function shouldLikelyUseWeb(message: string) {
  const lowered = message.toLowerCase();
  return [
    "recent",
    "today",
    "news",
    "context",
    "metric",
    "define",
    "definition",
    "recommend",
    "suggest",
    "should",
  ].some((token) => lowered.includes(token));
}

function looksLikeGeneralConversation(message: string) {
  const lowered = message.toLowerCase();
  return [
    "hello",
    "hi",
    "hey",
    "what do you think",
    "explain",
    "why",
    "brainstorm",
    "help me think",
  ].some((token) => lowered.includes(token));
}

function buildLoadingLabel(message: string) {
  if (shouldLikelyUseWeb(message)) {
    return "Atlas is checking ODI data and may search the web for context...";
  }
  if (looksLikeGeneralConversation(message)) {
    return "Atlas is thinking with Gemini and checking ODI evidence...";
  }
  return "Atlas is resolving your ODI query against the database...";
}

export function useAtlasChat() {
  const [state, setState] = useState<AtlasChatState>({
    isLoading: false,
    error: null,
    loadingLabel: null,
  });

  async function sendMessage(
    message: string,
    history: ChatHistoryTurn[],
    options: { silent?: boolean } = {},
  ): Promise<ChatReply> {
    const apiCandidates = getApiCandidates();
    const loadingLabel = buildLoadingLabel(message);
    if (!options.silent) {
      setState({ isLoading: true, error: null, loadingLabel });
    }
    try {
      traceClient("chat request started", { message, apiCandidates });
      const payload = await postApi<ChatReply>("/api/chat", { message, history });
      traceClient("chat request completed", {
        mode: payload.mode,
      });
      if (!options.silent) {
        setState({ isLoading: false, error: null, loadingLabel: null });
      }
      return payload;
    } catch (error) {
      const messageText = error instanceof Error ? error.message : "Unknown chat failure";
      traceClient("chat request failed", { error: messageText });
      setState({ isLoading: false, error: messageText, loadingLabel: null });
      throw error;
    }
  }

  return {
    ...state,
    sendMessage,
  };
}
