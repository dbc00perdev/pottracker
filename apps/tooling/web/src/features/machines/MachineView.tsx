import { useState } from "react";
import type { KeyboardEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { StatusBadge } from "@/components/StatusBadge";
import { ExportMenu } from "@/features/machines/ExportMenu";
import { machineAccent } from "@/features/machines/machineAccent";
import { useMachine } from "@/hooks/useMachines";
import { LatheTurretTable } from "@/features/machines/LatheTurretTable";
import { OffsetTable } from "@/features/machines/OffsetTable";
import { PotMap } from "@/features/machines/PotMap";
import { ToolLifeTable } from "@/features/machines/ToolLifeTable";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const TABS = ["Pot Map", "Offsets", "Tool Life", "Alarms"] as const;
type Tab = (typeof TABS)[number];

export function MachineView() {
  const { id = "" } = useParams();
  const { data: machine, isPending, isError } = useMachine(id);
  const [tab, setTab] = useState<Tab>("Pot Map");

  return (
    <div className="space-y-4">
      <Link to="/machines" className="text-sm text-neutral-400 hover:underline">
        ← Machines
      </Link>

      {isPending && <p className="text-neutral-500">Loading…</p>}
      {isError && <p className="text-status-alarm">Machine not found.</p>}

      {machine && (
        <div className={cn("space-y-4 rounded-lg border-2 p-4", machineAccent(machine).border)}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className={cn("text-xl font-semibold", machineAccent(machine).text)}>
                {machine.name}
              </h1>
              <p className="font-mono text-xs text-neutral-500">
                {machine.control_model} · polled {timeAgo(machine.focas_state.last_polled_at)}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <ExportMenu machineId={machine.id} />
              <StatusBadge
                status={machine.focas_state.connected ? "ok" : "alarm"}
                label={machine.focas_state.connected ? "Connected" : "Unreachable"}
              />
            </div>
          </div>

          {machine.machine_class === "lathe" ? (
            <LatheTurretTable machine={machine} />
          ) : (
            <>
          <div
            className="flex gap-1 border-b border-neutral-800"
            role="tablist"
            aria-label="Machine views"
            onKeyDown={(e: KeyboardEvent) => {
              const i = TABS.indexOf(tab);
              if (e.key === "ArrowRight") setTab(TABS[(i + 1) % TABS.length]);
              else if (e.key === "ArrowLeft") setTab(TABS[(i - 1 + TABS.length) % TABS.length]);
              else if (e.key === "Home") setTab(TABS[0]);
              else if (e.key === "End") setTab(TABS[TABS.length - 1]);
            }}
          >
            {TABS.map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                id={`tab-${t}`}
                aria-controls={`panel-${t}`}
                aria-selected={tab === t}
                tabIndex={tab === t ? 0 : -1}
                onClick={() => setTab(t)}
                className={cn(
                  "min-h-[44px] px-3 text-sm",
                  tab === t
                    ? "border-b-2 border-neutral-100 text-neutral-100"
                    : "text-neutral-400 hover:text-neutral-200",
                )}
              >
                {t}
              </button>
            ))}
          </div>

          <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} tabIndex={0}>
            {tab === "Pot Map" && <PotMap machine={machine} />}
            {tab === "Offsets" && <OffsetTable machineId={machine.id} />}
            {tab === "Tool Life" && <ToolLifeTable machineId={machine.id} />}
            {tab === "Alarms" && (
              <p className="text-neutral-500">
                Alarms are not available in v1 — no alarm mirror table yet (migration 0004+).
              </p>
            )}
          </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
