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

async function _handleResponse<T>(response: Response): Promise<T> {
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

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function jobTokenHeaders(accessToken: string): HeadersInit {
  return { Accept: "application/json", "X-Dalel-Job-Token": accessToken };
}

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
  return _handleResponse<T>(response);
}

export async function apiPost<T>(
  path: string,
  payload: unknown,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      signal,
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", WRONG_BACKEND_MESSAGE);
  }
  return _handleResponse<T>(response);
}

/** Submit real file bytes. The browser must choose the multipart boundary. */
export async function apiPostForm<T>(
  path: string,
  payload: FormData,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      signal,
      headers: { Accept: "application/json" },
      body: payload,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", WRONG_BACKEND_MESSAGE);
  }
  return _handleResponse<T>(response);
}

export async function apiGetWithJobToken<T>(
  path: string,
  accessToken: string,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      signal,
      headers: jobTokenHeaders(accessToken),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", WRONG_BACKEND_MESSAGE);
  }
  return _handleResponse<T>(response);
}

export async function apiDeleteWithJobToken<T>(
  path: string,
  accessToken: string,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "DELETE",
      signal,
      headers: jobTokenHeaders(accessToken),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", WRONG_BACKEND_MESSAGE);
  }
  return _handleResponse<T>(response);
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
