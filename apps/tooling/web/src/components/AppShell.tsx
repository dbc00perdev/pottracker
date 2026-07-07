import { useCallback, useRef, useState } from "react";
import { Outlet } from "react-router-dom";

import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { useFocusTrap } from "@/lib/a11y";

// Authenticated layout: fixed sidebar on lg+, off-canvas drawer below (docs/05
// §Mobile responsiveness). The drawer traps focus, closes on Escape, and
// restores focus to the menu button.
export function AppShell() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  useFocusTrap(drawerRef, drawerOpen, closeDrawer);

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-neutral-100 focus:px-3 focus:py-2 focus:text-neutral-900"
      >
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-neutral-800 bg-neutral-900 lg:block">
        <Sidebar />
      </aside>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            tabIndex={-1}
            className="absolute inset-0 bg-black/60"
            onClick={closeDrawer}
          />
          <aside
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="absolute inset-y-0 left-0 w-60 border-r border-neutral-800 bg-neutral-900"
          >
            <Sidebar onNavigate={closeDrawer} />
          </aside>
        </div>
      )}

      <div className="flex min-h-screen flex-col lg:pl-60">
        <TopBar onMenu={() => setDrawerOpen(true)} />
        <main id="main" className="flex-1 p-4">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
