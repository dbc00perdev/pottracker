import type { Assignment, Pot, Spindle, Tool } from "@/types/api";

// Active loadout = tools currently on the machine (spindle + next + pot
// identities), NOT the full crib. Enriched from tools assigned to this machine
// when a record exists; otherwise flagged NO REC (R11 honesty).

export type WhereKind = "spindle" | "next" | "pot";

export type LoadoutStatus = "verified" | "pending" | "no_record" | "unverified" | "probe";

export interface ActiveLoadoutRow {
  t_number: number;
  /** Offset register N (h_register) when assigned; null if no assignment. */
  n_register: number | null;
  whereKind: WhereKind;
  /** Display: SPINDLE | NEXT | pot N */
  where: string;
  pot_number: number | null;
  state: Pot["state"] | "spindle_only";
  potVerified: boolean;
  tool_id: string | null;
  short_id: string | null;
  type_code: string | null;
  type_label: string | null;
  description: string | null;
  manufacturer: string | null;
  edp_number: string | null;
  /** No collet column in schema yet — surface shank when present. */
  shank_mm: string | null;
  pending_review: boolean;
  status: LoadoutStatus;
}

const WHERE_RANK: Record<WhereKind, number> = { spindle: 0, next: 1, pot: 2 };

export interface ToolAtT {
  tool: Tool;
  h_register: number;
  pending_review: boolean;
}

/** Join tools + assignments for this machine, keyed by t_number. */
export function indexToolsByT(
  tools: Tool[],
  assignments: Assignment[],
  machineId: string,
): Map<number, ToolAtT> {
  const pendingByT = new Map<number, boolean>();
  for (const a of assignments) {
    if (a.machine_id !== machineId || a.deleted_at) continue;
    pendingByT.set(a.t_number, a.pending_review);
  }

  const map = new Map<number, ToolAtT>();
  for (const tool of tools) {
    for (const a of tool.assignments) {
      if (a.machine_id !== machineId) continue;
      map.set(a.t_number, {
        tool,
        h_register: a.h_register,
        pending_review: pendingByT.get(a.t_number) ?? false,
      });
    }
  }
  return map;
}

function statusFor(
  state: Pot["state"] | "spindle_only",
  hasRecord: boolean,
  pending: boolean,
  potVerified: boolean,
): LoadoutStatus {
  if (state === "probe") return "probe";
  if (!hasRecord) return "no_record";
  if (pending) return "pending";
  if (state === "unverified") return "unverified";
  if (potVerified) return "verified";
  return "verified";
}

/**
 * Build unique active rows from pot mirror + spindle HEAD/NEXT.
 * Spindle/next win over pot residence so a tool is not listed twice.
 */
export function buildActiveLoadout(
  pots: Pot[],
  spindle: Spindle | null,
  byT: Map<number, ToolAtT>,
): ActiveLoadoutRow[] {
  const map = new Map<number, ActiveLoadoutRow>();

  const put = (
    t: number,
    whereKind: WhereKind,
    pot_number: number | null,
    pot: Pot | null,
  ) => {
    const prev = map.get(t);
    if (prev && WHERE_RANK[whereKind] >= WHERE_RANK[prev.whereKind]) return;

    const hit = byT.get(t);
    const state: Pot["state"] | "spindle_only" = pot?.state ?? "spindle_only";
    const potVerified = pot?.verified ?? false;
    const pending = hit?.pending_review ?? false;
    const n = hit?.h_register ?? pot?.assigned_h_register ?? null;

    map.set(t, {
      t_number: t,
      n_register: n,
      whereKind,
      where:
        whereKind === "spindle"
          ? "SPINDLE"
          : whereKind === "next"
            ? "NEXT"
            : `pot ${pot_number}`,
      pot_number,
      state,
      potVerified,
      tool_id: hit?.tool.id ?? null,
      short_id: hit?.tool.short_id ?? null,
      type_code: hit?.tool.tool_type.code ?? null,
      type_label: hit?.tool.tool_type.display_name ?? null,
      description: hit?.tool.description ?? null,
      manufacturer: hit?.tool.manufacturer ?? null,
      edp_number: hit?.tool.edp_number ?? null,
      shank_mm: hit?.tool.shank_diameter_mm ?? null,
      pending_review: pending,
      status: statusFor(state, hit != null, pending, potVerified),
    });
  };

  const head = spindle?.head_t_number ?? null;
  const next = spindle?.next_t_number ?? null;
  if (head != null) {
    const pot = pots.find((p) => p.t_number === head) ?? null;
    put(head, "spindle", pot?.pot_number ?? null, pot);
  }
  if (next != null && next !== head) {
    const pot = pots.find((p) => p.t_number === next) ?? null;
    put(next, "next", pot?.pot_number ?? null, pot);
  }

  for (const p of pots) {
    if (p.t_number == null) continue;
    if (p.t_number === head || p.t_number === next) continue;
    // Skip confirmed-empty pots. Common case: PMC sticky/reinit cell reads
    // pot N = N (e.g. pot 19 → T19) with no assignment — occupancy marks EMPTY
    // but the raw t_number would otherwise pollute the loadout as a ghost tool.
    if (p.state === "empty") continue;
    put(p.t_number, "pot", p.pot_number, p);
  }

  return [...map.values()].sort((a, b) => {
    if (WHERE_RANK[a.whereKind] !== WHERE_RANK[b.whereKind]) {
      return WHERE_RANK[a.whereKind] - WHERE_RANK[b.whereKind];
    }
    return (a.pot_number ?? 999) - (b.pot_number ?? 999) || a.t_number - b.t_number;
  });
}

/** Client-side search over the active set (not the full crib). */
export function filterActiveLoadout(
  rows: ActiveLoadoutRow[],
  q: string,
): ActiveLoadoutRow[] {
  const s = q.trim().toLowerCase();
  if (!s) return rows;
  return rows.filter((r) => {
    const hay = [
      `t${r.t_number}`,
      r.n_register != null ? `n${r.n_register}` : "",
      r.n_register != null ? `h${r.n_register}` : "",
      r.where,
      r.pot_number,
      r.short_id,
      r.type_code,
      r.type_label,
      r.description,
      r.manufacturer,
      r.edp_number,
      r.shank_mm,
      r.status,
    ]
      .filter((x) => x != null && x !== "")
      .join(" ")
      .toLowerCase();
    return hay.includes(s);
  });
}
