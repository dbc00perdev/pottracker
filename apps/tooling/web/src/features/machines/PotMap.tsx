import { useEffect, useMemo, useState } from "react";

import { ActiveLoadoutTable } from "@/features/machines/ActiveLoadoutTable";
import { ActiveOffsetsPanel } from "@/features/machines/ActiveOffsetsPanel";
import {
  buildActiveLoadout,
  indexToolsByT,
} from "@/features/machines/activeLoadout";
import { findNextPotNumber, potPosition } from "@/features/machines/ringLayout";
import { ToolDetailDrawer } from "@/features/machines/ToolDetailDrawer";
import { useAssignments } from "@/hooks/useAssignments";
import { usePots, useSpindle } from "@/hooks/useMachines";
import { useTools } from "@/hooks/useTools";
import { cn } from "@/lib/utils";
import type { Machine, Pot, PotLocation, PotStateValue, Spindle } from "@/types/api";

// Role palette (less orange): spindle=cyan, NEXT=sky, loaded=green, probe=violet.

type FaceStyle = { ring: string; bg: string; text: string; label: string };
type PaneMode = "active" | "offsets";

const STATE_STYLE: Record<PotStateValue, FaceStyle> = {
  loaded: { ring: "border-emerald-500/80", bg: "bg-emerald-950/80", text: "text-emerald-300", label: "loaded" },
  empty: { ring: "border-neutral-700", bg: "bg-neutral-900", text: "text-neutral-600", label: "empty" },
  unverified: {
    ring: "border-amber-500/70", bg: "bg-amber-950/40", text: "text-amber-300", label: "unverified",
  },
  probe: { ring: "border-violet-400", bg: "bg-violet-950/90", text: "text-violet-300", label: "probe" },
};

const LOCATION_LABEL: Record<Exclude<PotLocation, null>, string> = {
  spindle: "→ spindle",
  next: "→ next",
};

export function PotMap({ machine }: { machine: Machine }) {
  const { data: pots, isPending, isError } = usePots(machine.id);
  const { data: spindle } = useSpindle(machine.id);
  const { data: toolsPage } = useTools(
    { assigned_machine_id: machine.id, limit: 200 },
    { refetchInterval: 5000 },
  );
  const { data: asgPage } = useAssignments(
    { machine_id: machine.id, limit: 200 },
    { refetchInterval: 5000 },
  );

  const [hoverT, setHoverT] = useState<number | null>(null);
  const [selectedT, setSelectedT] = useState<number | null>(null);
  const [pane, setPane] = useState<PaneMode>("active");

  const byT = useMemo(
    () => indexToolsByT(toolsPage?.items ?? [], asgPage?.items ?? [], machine.id),
    [toolsPage?.items, asgPage?.items, machine.id],
  );
  const loadout = useMemo(
    () => buildActiveLoadout(pots ?? [], spindle ?? null, byT),
    [pots, spindle, byT],
  );
  const loadoutByT = useMemo(
    () => new Map(loadout.map((r) => [r.t_number, r])),
    [loadout],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelectedT(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (isPending) return <p className="text-neutral-500">Loading pots…</p>;
  if (isError) return <p className="text-status-alarm">Failed to load pot table.</p>;
  if (!pots || pots.length === 0)
    return <p className="text-neutral-500">No pot data mirrored yet.</p>;

  const byPot = new Map(pots.map((p) => [p.pot_number, p]));
  const cells = Array.from({ length: machine.pot_count }, (_, i) => i + 1);
  const stats = summarize(pots, spindle ?? null);
  const nextPot = findNextPotNumber(pots, spindle?.next_t_number ?? null);
  const focusT = selectedT ?? hoverT;

  const onActivateT = (t: number) => {
    setSelectedT(t);
    setHoverT(t);
    // scrollIntoView is missing in jsdom — optional-call for tests + browsers.
    document.querySelector(`[data-pot-t="${t}"]`)?.scrollIntoView?.({
      block: "nearest", behavior: "smooth",
    });
    document.querySelector(`tr[data-t="${t}"]`)?.scrollIntoView?.({
      block: "nearest", behavior: "smooth",
    });
  };

  return (
    <div className="space-y-4">
      <StatusStrip spindle={spindle ?? null} stats={stats} nextAtSix={nextPot != null} />

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(320px,520px)_1fr]">
        <div className="rounded-lg border border-neutral-800 bg-neutral-950/40 p-4">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Carousel — {machine.pot_count} pots
            {nextPot != null && (
              <span className="ml-2 font-normal normal-case tracking-normal text-sky-300">
                · NEXT pot {nextPot} at 6 o&apos;clock
              </span>
            )}
          </h2>

          <div
            className="relative mx-auto aspect-square w-full max-w-[520px]"
            role="list"
            aria-label={`Pot carousel, ${machine.pot_count} pots`}
          >
            <Hub
              spindle={spindle ?? null}
              focusT={focusT}
              selectedT={selectedT}
              onHoverT={setHoverT}
              onActivateT={onActivateT}
            />

            {cells.map((potNumber) => {
              const pot = byPot.get(potNumber);
              const state: PotStateValue = pot?.state ?? "empty";
              const location = state === "probe" ? null : (pot?.location ?? null);
              const style = STATE_STYLE[state];
              const t = pot?.t_number ?? null;
              const vacated = location != null;
              const isNextFace =
                t != null &&
                spindle?.next_t_number != null &&
                t === spindle.next_t_number;
              const showTool = !vacated && state !== "empty" && t != null;
              const face =
                state === "probe"
                  ? t != null ? `T${t}` : "probe"
                  : vacated
                    ? location === "spindle" ? "→sp" : "→nx"
                    : showTool ? `T${t}` : "—";
              const aria =
                `Pot ${potNumber} ` +
                (vacated
                  ? `tool T${t} ${LOCATION_LABEL[location].replace("→ ", "in ")}`
                  : style.label) +
                (showTool && state !== "probe" ? ` tool T${t}` : "") +
                (state === "probe" && t != null ? ` tool T${t}` : "") +
                (!vacated && pot?.verified ? " presetter-verified" : "");
              const pos = potPosition(potNumber, machine.pot_count, nextPot);
              const hl = t != null && focusT === t;
              const sel = t != null && selectedT === t;

              return (
                <div
                  key={potNumber}
                  role="listitem"
                  data-pot-t={t ?? undefined}
                  aria-label={aria}
                  style={{ left: pos.left, top: pos.top }}
                  onMouseEnter={() => t != null && setHoverT(t)}
                  onMouseLeave={() => setHoverT(null)}
                  onClick={() => t != null && onActivateT(t)}
                  className={cn(
                    "absolute flex h-[62px] w-[62px] -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center rounded-full border-2 text-center leading-tight transition-transform sm:h-14 sm:w-14",
                    t != null && "cursor-pointer hover:z-10 hover:scale-110",
                    vacated
                      ? "border-dashed border-neutral-600 bg-neutral-950/90 opacity-80"
                      : cn(style.ring, style.bg),
                    isNextFace && !vacated && "shadow-[0_0_0_3px_rgba(56,189,248,0.4)]",
                    state === "empty" && !vacated && "border-dashed",
                    hl && "z-10 scale-110 shadow-[0_0_0_3px_rgba(34,211,238,0.45)]",
                    sel && "z-20 shadow-[0_0_0_3px_rgba(165,180,252,0.65)]",
                  )}
                >
                  <span className="font-mono text-[9px] text-neutral-500">{potNumber}</span>
                  <span
                    className={cn(
                      "font-mono text-xs font-bold sm:text-[13px]",
                      vacated
                        ? location === "spindle"
                          ? "text-cyan-400/90"
                          : "text-sky-400/90"
                        : style.text,
                    )}
                  >
                    {face}
                  </span>
                  {vacated && t != null && (
                    <span className="font-mono text-[8px] text-neutral-600">T{t}</span>
                  )}
                  {!vacated && pot?.verified && (
                    <span className="absolute right-1 top-0.5 text-[10px] text-emerald-400" aria-hidden>
                      ✓
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          <PotLegend />
          <p className="mt-3 text-center text-xs leading-relaxed text-neutral-500">
            Hub = spindle (cyan). NEXT pot at 6 o&apos;clock (sky). Probe = violet.
            Hover highlights; click opens detail.
          </p>
        </div>

        <div className="space-y-3">
          <div className="flex gap-1 border-b border-neutral-800" role="tablist" aria-label="Loadout views">
            {(["active", "offsets"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={pane === m}
                onClick={() => setPane(m)}
                className={cn(
                  "min-h-[44px] px-3 text-sm capitalize",
                  pane === m
                    ? "border-b-2 border-neutral-100 text-neutral-100"
                    : "text-neutral-400 hover:text-neutral-200",
                )}
              >
                {m === "active" ? "Active" : "Offsets"}
              </button>
            ))}
          </div>
          {pane === "active" ? (
            <ActiveLoadoutTable
              rows={loadout}
              hoverT={focusT}
              onHoverT={setHoverT}
              onActivateT={onActivateT}
            />
          ) : (
            <ActiveOffsetsPanel
              machineId={machine.id}
              rows={loadout}
              hoverT={focusT}
              onHoverT={setHoverT}
              onActivateT={onActivateT}
            />
          )}
        </div>
      </div>

      <ToolDetailDrawer
        open={selectedT != null}
        row={selectedT != null ? loadoutByT.get(selectedT) ?? null : null}
        onClose={() => setSelectedT(null)}
      />
    </div>
  );
}

function summarize(pots: Pot[], spindle: Spindle | null) {
  let loaded = 0;
  let unverified = 0;
  let probe = 0;
  for (const p of pots) {
    if (p.location != null) continue;
    if (p.state === "loaded") loaded += 1;
    else if (p.state === "unverified") unverified += 1;
    else if (p.state === "probe") probe += 1;
  }
  return {
    loaded,
    unverified,
    probe,
    head: spindle?.head_t_number ?? null,
    next: spindle?.next_t_number ?? null,
    mode: spindle?.mode ?? null,
    running: spindle?.running ?? null,
  };
}

function StatusStrip({
  spindle,
  stats,
  nextAtSix,
}: {
  spindle: Spindle | null;
  stats: ReturnType<typeof summarize>;
  nextAtSix: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <Chip
        k="Spindle"
        v={stats.head != null ? `T${stats.head}` : "—"}
        accent="spindle"
        ariaLabel={stats.head != null ? `Spindle: tool T${stats.head}` : "Spindle: none"}
      />
      <Chip
        k="Next"
        v={stats.next != null ? `T${stats.next}` : "—"}
        accent="next"
        ariaLabel={stats.next != null ? `Next: tool T${stats.next}` : "Next: none"}
      />
      {nextAtSix && <Chip k="Ring" v="NEXT @ 6" accent="next" />}
      <Chip k="Loaded" v={String(stats.loaded)} accent="ok" />
      {stats.unverified > 0 && (
        <Chip k="Unverified" v={String(stats.unverified)} accent="warn" />
      )}
      {stats.probe > 0 && <Chip k="Probe" v={String(stats.probe)} accent="probe" />}
      {stats.mode != null && (
        <Chip k="Mode" v={`${stats.mode}${stats.running ? " · run" : ""}`} accent="dim" />
      )}
      {spindle?.emergency_stop && <Chip k="E-stop" v="ACTIVE" accent="alarm" />}
    </div>
  );
}

function Chip({
  k, v, accent, ariaLabel,
}: {
  k: string;
  v: string;
  accent: "ok" | "warn" | "spindle" | "next" | "probe" | "dim" | "alarm";
  ariaLabel?: string;
}) {
  const vColor = {
    ok: "text-emerald-300",
    warn: "text-amber-300",
    spindle: "text-cyan-300",
    next: "text-sky-300",
    probe: "text-violet-300",
    dim: "text-neutral-200",
    alarm: "text-status-alarm",
  }[accent];
  return (
    <div
      className="min-w-[104px] rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2"
      aria-label={ariaLabel}
    >
      <div className="text-[11px] uppercase tracking-wide text-neutral-500">{k}</div>
      <div className={cn("font-mono text-lg font-bold", vColor)}>{v}</div>
    </div>
  );
}

function Hub({
  spindle, focusT, selectedT, onHoverT, onActivateT,
}: {
  spindle: Spindle | null;
  focusT: number | null;
  selectedT: number | null;
  onHoverT: (t: number | null) => void;
  onActivateT: (t: number) => void;
}) {
  const head = spindle?.head_t_number ?? null;
  const next = spindle?.next_t_number ?? null;
  const hl = head != null && focusT === head;
  const sel = head != null && selectedT === head;
  return (
    <div
      data-pot-t={head ?? undefined}
      onMouseEnter={() => head != null && onHoverT(head)}
      onMouseLeave={() => onHoverT(null)}
      onClick={() => head != null && onActivateT(head)}
      className={cn(
        "absolute left-1/2 top-1/2 z-[1] flex h-[176px] w-[176px] -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center rounded-full border-2 border-dashed border-cyan-400/70 bg-slate-900 text-center sm:h-36 sm:w-36",
        head != null && "cursor-pointer",
        hl && "shadow-[0_0_0_3px_rgba(34,211,238,0.4)]",
        sel && "shadow-[0_0_0_3px_rgba(165,180,252,0.6)]",
      )}
      aria-hidden
    >
      <span className="text-[10px] uppercase tracking-widest text-neutral-500">Spindle</span>
      <span className="font-mono text-3xl font-extrabold text-cyan-300 sm:text-2xl">
        {head != null ? `T${head}` : "—"}
      </span>
      {next != null && (
        <span className="mt-1 font-mono text-[11px] text-sky-300">next → T{next}</span>
      )}
    </div>
  );
}

function PotLegend() {
  const items: { state: PotStateValue; desc: string }[] = [
    { state: "loaded", desc: "measured" },
    { state: "unverified", desc: "identity only" },
    { state: "empty", desc: "empty" },
    { state: "probe", desc: "probe" },
  ];
  return (
    <div className="mt-4 flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-neutral-500">
      {items.map(({ state, desc }) => (
        <span key={state} className="flex items-center gap-1.5">
          <span className={cn("inline-block h-2.5 w-2.5 rounded-full border-2", STATE_STYLE[state].ring, STATE_STYLE[state].bg)} />
          <span className={STATE_STYLE[state].text}>{STATE_STYLE[state].label}</span>
          <span className="text-neutral-600">— {desc}</span>
        </span>
      ))}
      <span className="text-cyan-300">spindle</span>
      <span className="text-sky-300">NEXT @ 6</span>
      <span className="text-neutral-500">→sp / →nx vacated</span>
    </div>
  );
}
