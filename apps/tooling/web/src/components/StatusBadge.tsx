import { AlertTriangle, CheckCircle2, CircleSlash, XCircle } from "lucide-react";
import type { ComponentType } from "react";

import { cn } from "@/lib/utils";

export type Status = "ok" | "warn" | "alarm" | "idle";

// Color is never the sole indicator (docs/05 a11y) — each status pairs a hue
// with a distinct icon and a text label.
const STYLES: Record<Status, { icon: ComponentType<{ className?: string }>; cls: string }> = {
  ok: { icon: CheckCircle2, cls: "text-status-ok" },
  warn: { icon: AlertTriangle, cls: "text-status-warn" },
  alarm: { icon: XCircle, cls: "text-status-alarm" },
  idle: { icon: CircleSlash, cls: "text-status-idle" },
};

export function StatusBadge({ status, label }: { status: Status; label: string }) {
  const { icon: Icon, cls } = STYLES[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm font-medium", cls)}>
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      {label}
    </span>
  );
}
