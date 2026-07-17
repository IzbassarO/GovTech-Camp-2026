"use client";

import { useEffect, useState } from "react";

import type {
  LiveJobEvent,
  LiveJobEventsResponse,
  LiveJobResponse,
  LiveJobStatus,
} from "./types";
import { ApiError, apiGetWithJobToken } from "./api";
import { readJobToken } from "./jobTokens";

const TERMINAL_STATUSES = new Set<LiveJobStatus>([
  "completed",
  "failed",
  "cancelled",
  "expired",
]);

export interface LiveJobPollingState {
  data: LiveJobResponse | null;
  events: LiveJobEvent[];
  accessToken: string | null;
  error: string | null;
  loading: boolean;
}

export function useLiveJob(jobId: string, retry: number): LiveJobPollingState {
  const [state, setState] = useState<LiveJobPollingState>({
    data: null,
    events: [],
    accessToken: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    const accessToken = readJobToken("live_analysis", jobId);
    if (!accessToken) {
      setState({
        data: null,
        events: [],
        accessToken: null,
        error:
          "Защищённый ключ задания недоступен в текущей вкладке. Создайте новый анализ или вернитесь в исходную вкладку.",
        loading: false,
      });
      return;
    }

    let stopped = false;
    let timer: number | undefined;
    let controller: AbortController | undefined;
    setState((current) => ({
      ...current,
      accessToken,
      error: null,
      loading: current.data === null,
    }));

    const poll = async () => {
      controller = new AbortController();
      try {
        const [response, eventResponse] = await Promise.all([
          apiGetWithJobToken<LiveJobResponse>(
            `/api/live/jobs/${encodeURIComponent(jobId)}`,
            accessToken,
            controller.signal,
          ),
          apiGetWithJobToken<LiveJobEventsResponse>(
            `/api/live/jobs/${encodeURIComponent(jobId)}/events`,
            accessToken,
            controller.signal,
          ),
        ]);
        if (stopped) return;
        if (
          response.mode !== "live_analysis" ||
          response.job_id !== eventResponse.job_id
        ) {
          throw new Error("Сервер вернул задание другого режима.");
        }
        setState({
          data: response,
          events: eventResponse.events,
          accessToken,
          error: null,
          loading: false,
        });
        if (!TERMINAL_STATUSES.has(response.status)) {
          timer = window.setTimeout(poll, 900);
        }
      } catch (error: unknown) {
        if (stopped || controller.signal.aborted) return;
        const message =
          error instanceof ApiError && (error.status === 403 || error.status === 404)
            ? "Задание недоступно или срок его хранения истёк."
            : error instanceof Error
              ? error.message
              : "Не удалось получить состояние анализа.";
        setState((current) => ({ ...current, accessToken, error: message, loading: false }));
      }
    };

    void poll();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [jobId, retry]);

  return state;
}
