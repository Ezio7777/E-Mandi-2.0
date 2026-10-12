import { env } from "@/config/env";
import { ApiError } from "./errors";

type Query = Record<string, string | number | boolean | undefined | null>;
interface RequestOptions extends Omit<RequestInit, "body"> {
  query?: Query;
  body?: unknown;
}

let accessToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

/** Bearer token (if the backend uses one) is kept in memory only, never in localStorage. */
export const setAccessToken = (t: string | null) => { accessToken = t; };
export const setUnauthorizedHandler = (fn: (() => void) | null) => { onUnauthorized = fn; };

function buildUrl(path: string, query?: Query) {
  const url = new URL(`${env.apiUrl}${path.startsWith("/") ? path : `/${path}`}`);
  if (query) for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  return url.toString();
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { query, body, headers, ...rest } = opts;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), {
      credentials: "include", // httpOnly session cookie from the backend
      ...rest,
      headers: {
        Accept: "application/json",
        ...(body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your connection and try again.", "NETWORK");
  }

  if (res.status === 204) return undefined as T;

  const isJson = res.headers.get("content-type")?.includes("application/json");
  const payload: unknown = isJson ? await res.json().catch(() => undefined) : undefined;

  if (!res.ok) {
    if (res.status === 401) onUnauthorized?.();
    const p = (payload ?? {}) as { message?: string; detail?: string; code?: string };
    throw new ApiError(res.status, p.message ?? p.detail ?? `Request failed (${res.status})`, p.code, payload);
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string, query?: Query, init?: RequestInit) => request<T>(path, { ...init, method: "GET", query }),
  post: <T>(path: string, body?: unknown, init?: RequestInit) => request<T>(path, { ...init, method: "POST", body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
