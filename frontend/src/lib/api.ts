// Typed API client. The frontend NEVER reads artifact files directly — it
// only talks to the FastAPI layer over HTTP.

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.name = "ApiError";
  }
}

// Shown when the configured backend is unreachable or is not the Dalel API
// (e.g. an unrelated service occupying the port). Points the operator at the
// address without hiding genuine API errors.
const WRONG_BACKEND_MESSAGE =
  `API Dalel недоступен или указан неверный адрес сервера (${API_BASE_URL}).` +
  " Проверьте, что бэкенд запущен и NEXT_PUBLIC_API_BASE_URL указывает на него.";

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      signal,
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", WRONG_BACKEND_MESSAGE);
  }

  if (!response.ok) {
    let body: { error?: string; detail?: string } | null = null;
    try {
      body = (await response.json()) as { error?: string; detail?: string };
    } catch {
      body = null;
    }
    // A genuine Dalel API error always carries our `{error, detail}` shape.
    if (body && typeof body.error === "string") {
      throw new ApiError(response.status, body.error, body.detail ?? "Не удалось загрузить данные.");
    }
    // Otherwise the response did not come from the Dalel API (wrong port /
    // foreign service): surface an actionable message, not a bare "Not Found".
    throw new ApiError(response.status, "wrong_backend", WRONG_BACKEND_MESSAGE);
  }

  return (await response.json()) as T;
}

export function buildQuery(params: Record<string, string | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value != null && value !== "") {
      search.set(key, value);
    }
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}
