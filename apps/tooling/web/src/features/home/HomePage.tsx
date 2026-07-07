import { useAuth } from "@/lib/auth";

// Placeholder authenticated landing (Phase 4 step 3). Proves the login → me →
// protected-route slice end to end. Replaced by the AppShell + Dashboard in the
// next steps.
export function HomePage() {
  const { user, logout } = useAuth();
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-neutral-950 text-neutral-100">
      <h1 className="text-2xl font-semibold">Lance Tooling</h1>
      {user && (
        <p className="text-neutral-300">
          Signed in as <span className="font-medium">{user.display_name}</span>{" "}
          <span className="font-mono text-status-ok">({user.role})</span>
        </p>
      )}
      <button
        type="button"
        onClick={logout}
        className="min-h-[44px] rounded-md border border-neutral-700 px-4 text-neutral-200"
      >
        Sign out
      </button>
    </div>
  );
}
