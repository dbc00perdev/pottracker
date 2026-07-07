import { LogOut, Menu, Search } from "lucide-react";

import { useAuth } from "@/lib/auth";

export function TopBar({ onMenu }: { onMenu: () => void }) {
  const { user, logout } = useAuth();
  return (
    <header className="flex h-14 items-center gap-3 border-b border-neutral-800 bg-neutral-900 px-3">
      <button
        type="button"
        onClick={onMenu}
        aria-label="Open navigation"
        className="flex h-11 w-11 items-center justify-center rounded-md text-neutral-300 hover:bg-neutral-800 lg:hidden"
      >
        <Menu className="h-5 w-5" aria-hidden />
      </button>

      <div className="flex flex-1 items-center gap-2 rounded-md bg-neutral-950 px-3 text-neutral-400">
        <Search className="h-4 w-4 shrink-0" aria-hidden />
        <input
          type="search"
          placeholder="Search tools…"
          aria-label="Search"
          className="h-10 w-full bg-transparent text-sm text-neutral-100 outline-none"
        />
      </div>

      {user && (
        <span className="hidden text-sm text-neutral-300 sm:inline">
          {user.display_name} <span className="font-mono text-neutral-500">({user.role})</span>
        </span>
      )}
      <button
        type="button"
        onClick={logout}
        aria-label="Sign out"
        className="flex h-11 items-center gap-2 rounded-md px-3 text-sm text-neutral-300 hover:bg-neutral-800"
      >
        <LogOut className="h-4 w-4" aria-hidden />
        <span className="hidden sm:inline">Sign out</span>
      </button>
    </header>
  );
}
