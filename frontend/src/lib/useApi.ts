"use client";

import { useEffect, useState } from "react";

import { ApiError, apiGet } from "./api";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

// Client-side data hook with loading/error state and request cancellation.
// `deps` re-triggers the fetch (e.g. when filters in the URL change).
export function useApi<T>(path: string | null, deps: unknown[] = []): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    error: null,
    loading: path !== null,
  });

  useEffect(() => {
    if (path === null) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true, error: null }));
    apiGet<T>(path, controller.signal)
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const message =
          err instanceof ApiError ? err.message : "Не удалось загрузить результаты.";
        setState({ data: null, error: message, loading: false });
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  return state;
}
