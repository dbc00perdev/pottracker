import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiFetch, onAuthFailure } from "@/lib/api";
import { tokens } from "@/lib/tokens";
import type { MeResponse, TokenPair } from "@/types/api";

interface AuthState {
  user: MeResponse | null;
  /** True while the on-mount /auth/me bootstrap is in flight. */
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(() => {
    tokens.clear();
    setUser(null);
  }, []);

  // Unrecoverable auth (refresh failed mid-session) → drop to logged-out.
  useEffect(() => {
    onAuthFailure(() => setUser(null));
  }, []);

  // Bootstrap: if we hold an access token, resolve the current user once.
  useEffect(() => {
    let active = true;
    async function bootstrap() {
      if (!tokens.access()) {
        setLoading(false);
        return;
      }
      try {
        const me = await apiFetch<MeResponse>("/auth/me");
        if (active) setUser(me);
      } catch {
        if (active) {
          tokens.clear();
          setUser(null);
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    void bootstrap();
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const pair = await apiFetch<TokenPair>("/auth/login", {
      method: "POST",
      body: { username, password },
      auth: false,
    });
    tokens.set(pair.access_token, pair.refresh_token);
    const me = await apiFetch<MeResponse>("/auth/me");
    setUser(me);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
