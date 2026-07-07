// Placeholder shell (Phase 4 step 1). Replaced by the real AppShell + router in
// the next steps. Renders enough to confirm Tailwind tokens + build work.
export function App() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-neutral-950 text-neutral-100">
      <h1 className="text-2xl font-semibold">Lance Tooling</h1>
      <p className="text-neutral-400">Frontend foundation — scaffold OK.</p>
      <span className="font-mono text-status-ok">H125 = 63.5042 mm</span>
    </div>
  );
}
