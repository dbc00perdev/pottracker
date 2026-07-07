// JWT access + refresh token storage. localStorage is acceptable for v1 (D4-7):
// single-origin shop tablets, low XSS surface (no third-party embeds). Revisit
// if the threat model changes.

const ACCESS_KEY = "lance.tooling.access_token";
const REFRESH_KEY = "lance.tooling.refresh_token";

export const tokens = {
  access(): string | null {
    return localStorage.getItem(ACCESS_KEY);
  },
  refresh(): string | null {
    return localStorage.getItem(REFRESH_KEY);
  },
  set(access: string, refresh: string): void {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear(): void {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};
