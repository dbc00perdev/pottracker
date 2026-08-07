// Fetch wrapper for the tooling API. Responsibilities:
//   - prefix every path with /api/tooling (dev-proxied to FastAPI :8000)
//   - attach the bearer access token
//   - on a 401, refresh once and retry the request a single time; concurrent
//     401s share one in-flight refresh (no refresh storm)
//   - surface RFC 7807 problem+json as a typed ApiError
//
// A failed refresh clears tokens and notifies the auth layer via onAuthFailure
// so the UI can drop to the login screen.

import { tokens } from "@/lib/tokens";
import type { Problem } from "@/types/api";

const BASE = "/api/tooling";

export class ApiError extends Error {
  readonly status: number;
  readonly problem?: Problem;

  constructor(status: number, message: string, problem?: Problem) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

let authFailureHandler: (() => void) | null = null;

/** Register a callback fired when auth is unrecoverable (refresh failed). */
export function onAuthFailure(handler: () => void): void {
  authFailureHandler = handler;
}

let refreshInFlight: Promise<boolean> | null = null;

async function doRefresh(): Promise<boolean> {
  const refreshToken = tokens.refresh();
  if (!refreshToken) return false;
  const res = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) {
    tokens.clear();
    return false;
  }
  const data = (await res.json()) as { access_token: string; refresh_token: string };
  tokens.set(data.access_token, data.refresh_token);
  return true;
}

function refreshOnce(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

export interface ApiOptions extends Omit<RequestInit, "body"> {
  /** JSON-serializable body; the wrapper stringifies + sets the content type. */
  body?: unknown;
  /** Attach the bearer token + enable 401-refresh. Default true. */
  auth?: boolean;
}

export async function apiFetch<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { auth = true, body, headers, ...rest } = opts;

  const send = (): Promise<Response> => {
    const h = new Headers(headers);
    if (body !== undefined) h.set("Content-Type", "application/json");
    if (auth) {
      const at = tokens.access();
      if (at) h.set("Authorization", `Bearer ${at}`);
    }
    return fetch(`${BASE}${path}`, {
      ...rest,
      headers: h,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  };

  let res = await send();

  if (res.status === 401 && auth) {
    const refreshed = await refreshOnce();
    if (refreshed) {
      res = await send();
    }
    if (!refreshed || res.status === 401) {
      tokens.clear();
      authFailureHandler?.();
      throw await toApiError(res);
    }
  }

  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Authenticated file download (a bare <a href> can't carry the bearer
 * token). Same 401-refresh-once behavior as apiFetch; resolves to the blob +
 * the server's Content-Disposition filename. */
export async function apiDownload(
  path: string,
): Promise<{ blob: Blob; filename: string }> {
  const send = (): Promise<Response> => {
    const h = new Headers();
    const at = tokens.access();
    if (at) h.set("Authorization", `Bearer ${at}`);
    return fetch(`${BASE}${path}`, { headers: h });
  };

  let res = await send();
  if (res.status === 401) {
    const refreshed = await refreshOnce();
    if (refreshed) res = await send();
    if (!refreshed || res.status === 401) {
      tokens.clear();
      authFailureHandler?.();
      throw await toApiError(res);
    }
  }
  if (!res.ok) throw await toApiError(res);

  const disposition = res.headers.get("content-disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return { blob: await res.blob(), filename: match?.[1] ?? "export.txt" };
}

/** Hand a downloaded blob to the browser as a file-save. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function toApiError(res: Response): Promise<ApiError> {
  let problem: Problem | undefined;
  let message = res.statusText || `HTTP ${res.status}`;
  try {
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("json")) {
      problem = (await res.json()) as Problem;
      if (problem?.detail) message = problem.detail;
    }
  } catch {
    // non-JSON or empty body — keep the status-line message
  }
  return new ApiError(res.status, message, problem);
}
