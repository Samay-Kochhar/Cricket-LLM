"use client";

import { useCallback, useState } from "react";

import type { WorkbenchSearchResponse } from "@/lib/api-types";
import { getApiCandidates, postApi } from "@/lib/api-client";

type WorkbenchSearchState = {
  isLoading: boolean;
  error: string | null;
  result: WorkbenchSearchResponse | null;
};

function traceWorkbench(message: string, extra?: Record<string, unknown>) {
  const timestamp = new Date().toISOString();
  if (extra) {
    console.info(`[${timestamp}] [workbench] ${message}`, extra);
    return;
  }
  console.info(`[${timestamp}] [workbench] ${message}`);
}

export function useWorkbenchSearch() {
  const [state, setState] = useState<WorkbenchSearchState>({
    isLoading: false,
    error: null,
    result: null,
  });

  const search = useCallback(async (query: string) => {
    setState({ isLoading: true, error: null, result: null });
    try {
      const apiCandidates = getApiCandidates();
      traceWorkbench("search started", { query, apiCandidates });
      const payload = await postApi<WorkbenchSearchResponse>("/api/workbench/search", { query });
      traceWorkbench("search completed", {
        kind: payload.kind,
      });
      setState({ isLoading: false, error: null, result: payload });
      return payload;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown workbench search failure";
      traceWorkbench("search failed", { error: message });
      setState({ isLoading: false, error: message, result: null });
      throw error;
    }
  }, []);

  return {
    ...state,
    search,
  };
}
