"use client";

import { useState } from "react";

import type { QueryResponse } from "@/lib/api-types";
import { postApi } from "@/lib/api-client";
import { normalizeQueryResponse } from "@/lib/result-mappers";


type QueryState = {
  isLoading: boolean;
  error: string | null;
  result: QueryResponse | null;
};


export function useQueryAnalysis() {
  const [state, setState] = useState<QueryState>({
    isLoading: false,
    error: null,
    result: null,
  });

  async function runQuery(question: string) {
    setState({ isLoading: true, error: null, result: null });

    try {
      const payload = await postApi<QueryResponse>("/api/query", { question });
      setState({
        isLoading: false,
        error: null,
        result: normalizeQueryResponse(payload),
      });
    } catch (error) {
      setState({
        isLoading: false,
        error: error instanceof Error ? error.message : "Unknown query failure",
        result: null,
      });
    }
  }

  return {
    ...state,
    runQuery,
  };
}
