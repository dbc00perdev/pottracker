import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, onAuthFailure } from "@/lib/api";
import { tokens } from "@/lib/tokens";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("apiFetch 401 → refresh → retry", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });
  afterEach(() => {
    localStorage.clear();
  });

  it("refreshes once on 401 and retries the original request", async () => {
    tokens.set("stale-access", "good-refresh");
    const fetchMock = vi
      .fn()
      // 1) original request → 401
      .mockResolvedValueOnce(new Response("", { status: 401 }))
      // 2) refresh → new tokens
      .mockResolvedValueOnce(
        jsonResponse(200, { access_token: "new-access", refresh_token: "new-refresh" }),
      )
      // 3) retry → success
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiFetch<{ ok: boolean }>("/tools");

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    // retry carried the refreshed bearer
    const retryInit = fetchMock.mock.calls[2][1] as RequestInit;
    const retryHeaders = retryInit.headers as Headers;
    expect(retryHeaders.get("Authorization")).toBe("Bearer new-access");
    expect(tokens.access()).toBe("new-access");
  });

  it("clears tokens and fires onAuthFailure when refresh fails", async () => {
    tokens.set("stale-access", "dead-refresh");
    const onFail = vi.fn();
    onAuthFailure(onFail);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 401 })) // original
      .mockResolvedValueOnce(new Response("", { status: 401 })); // refresh rejected
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("/tools")).rejects.toMatchObject({ status: 401 });
    expect(tokens.access()).toBeNull();
    expect(onFail).toHaveBeenCalledOnce();
  });
});
