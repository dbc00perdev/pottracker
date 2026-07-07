import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

interface FromState {
  from?: { pathname?: string };
}

export function LoginPage() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const from = (location.state as FromState | null)?.from?.pathname ?? "/";

  if (user) return <Navigate to={from} replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed — please try again");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-950 p-4 text-neutral-100">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-5 rounded-lg border border-neutral-800 bg-neutral-900 p-6"
      >
        <div>
          <h1 className="text-xl font-semibold">Lance Tooling</h1>
          <p className="mt-1 text-sm text-neutral-400">Sign in to continue</p>
        </div>

        <div className="space-y-2">
          <label htmlFor="username" className="block text-sm text-neutral-300">
            Username
          </label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            className="min-h-[44px] w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 text-base outline-none focus:border-neutral-400"
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="password" className="block text-sm text-neutral-300">
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="min-h-[44px] w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 text-base outline-none focus:border-neutral-400"
          />
        </div>

        {error && (
          <p role="alert" className="text-sm text-status-alarm">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="min-h-[44px] w-full rounded-md bg-neutral-100 px-4 font-medium text-neutral-900 disabled:opacity-50"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
