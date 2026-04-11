"use client";

import { useState } from "react";

import type { QueryResponse } from "@/lib/api-types";
import { getApiBaseUrl } from "@/lib/api-client";
import { normalizeQueryResponse } from "@/lib/result-mappers";


const DEFAULT_API_BASE_URL = getApiBaseUrl();


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
      const response = await fetch(`${DEFAULT_API_BASE_URL}/api/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ question }),
      });

      if (!response.ok) {
        throw new Error(`Query failed with status ${response.status}`);
      }

      const payload = (await response.json()) as QueryResponse;
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
