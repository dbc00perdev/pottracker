import { describe, expect, it } from "vitest";

import {
  buildActiveLoadout,
  filterActiveLoadout,
  indexToolsByT,
} from "@/features/machines/activeLoadout";
import type { Assignment, Pot, Spindle, Tool } from "@/types/api";

function pot(overrides: Partial<Pot> & Pick<Pot, "pot_number">): Pot {
  return {
    t_number: null,
    state: "empty",
    verified: false,
    assigned_h_register: null,
    offset_mm: null,
    location: null,
    last_polled_at: "2026-07-09T12:00:00Z",
    last_changed_at: "2026-07-09T12:00:00Z",
    ...overrides,
  };
}

function tool(partial: {
  id: string;
  short_id: string;
  t_number: number;
  h_register: number;
  machine_id?: string;
}): Tool {
  return {
    id: partial.id,
    short_id: partial.short_id,
    tool_type: { code: "drill", display_name: "Drill" },
    diameter_mm: "6.0000",
    diameter_inch: null,
    flute_count: 2,
    corner_radius_mm: null,
    flute_length_mm: null,
    overall_length_mm: null,
    shank_diameter_mm: "6.0000",
    substrate: null,
    coating: null,
    vendor: null,
    vendor_part_number: null,
    vendor_url: null,
    manufacturer: "OSG",
    edp_number: "123",
    max_doc_mm: null,
    max_woc_mm: null,
    requires_tsc: false,
    requires_climb: false,
    is_consumable_class: false,
    regrind_count: 0,
    description: "6mm 2FL DRILL",
    notes: null,
    assignments: [
      {
        machine_id: partial.machine_id ?? "m1",
        machine_name: "Viper",
        t_number: partial.t_number,
        h_register: partial.h_register,
        d_register: null,
      },
    ],
    retired_at: null,
  };
}

function asg(partial: Partial<Assignment> & Pick<Assignment, "t_number" | "h_register">): Assignment {
  return {
    id: `a-${partial.t_number}`,
    tool_id: "t1",
    tool_short_id: "100001",
    machine_id: "m1",
    machine_name: "Viper",
    d_register: null,
    cached_h_geom_mm: null,
    cached_h_wear_mm: null,
    cached_d_geom_mm: null,
    cached_d_wear_mm: null,
    pending_review: false,
    pending_reason: null,
    assigned_at: "2026-07-09T12:00:00Z",
    last_confirmed_at: null,
    deleted_at: null,
    ...partial,
  };
}

describe("buildActiveLoadout", () => {
  const pots: Pot[] = [
    pot({ pot_number: 1, t_number: 84, state: "loaded", verified: true, assigned_h_register: 84, offset_mm: "5.10" }),
    pot({ pot_number: 2, t_number: 50, state: "loaded", verified: true, assigned_h_register: 50, offset_mm: "3.40", location: "spindle" }),
    pot({ pot_number: 3, t_number: 33, state: "loaded", assigned_h_register: 33, offset_mm: "2.00", location: "next" }),
    pot({ pot_number: 4, t_number: 17, state: "unverified" }),
  ];
  const spindle: Spindle = {
    head_t_number: 50,
    next_t_number: 33,
    mode: "auto",
    running: true,
    emergency_stop: false,
    last_polled_at: "2026-07-09T12:00:00Z",
    last_changed_at: "2026-07-09T12:00:00Z",
  };

  it("lists spindle, next, and resident pots once each", () => {
    const byT = indexToolsByT(
      [
        tool({ id: "1", short_id: "100084", t_number: 84, h_register: 84 }),
        tool({ id: "2", short_id: "100050", t_number: 50, h_register: 50 }),
      ],
      [asg({ t_number: 84, h_register: 84 }), asg({ t_number: 50, h_register: 50 })],
      "m1",
    );
    const rows = buildActiveLoadout(pots, spindle, byT);
    const ts = rows.map((r) => r.t_number);
    expect(ts).toEqual([50, 33, 84, 17]); // spindle, next, pot1, pot4
    expect(rows.find((r) => r.t_number === 50)?.whereKind).toBe("spindle");
    expect(rows.find((r) => r.t_number === 33)?.whereKind).toBe("next");
    expect(rows.find((r) => r.t_number === 84)?.status).toBe("verified");
    expect(rows.find((r) => r.t_number === 17)?.status).toBe("no_record");
  });

  it("marks pending_review from assignments as VERIFY", () => {
    const byT = indexToolsByT(
      [tool({ id: "1", short_id: "100084", t_number: 84, h_register: 84 })],
      [asg({ t_number: 84, h_register: 84, pending_review: true })],
      "m1",
    );
    const rows = buildActiveLoadout(
      [pot({ pot_number: 1, t_number: 84, state: "loaded", assigned_h_register: 84, offset_mm: "1" })],
      null,
      byT,
    );
    expect(rows[0].status).toBe("pending");
  });

  it("does not list empty ordinal pots as active (pot N == T N reinit sentinel)", () => {
    // Pot 19 reading T19 with no assignment → API state empty; must not appear
    // as "on machine" in the loadout (ghost identity).
    const byT = indexToolsByT([], [], "m1");
    const rows = buildActiveLoadout(
      [
        pot({ pot_number: 19, t_number: 19, state: "empty" }),
        pot({ pot_number: 1, t_number: 84, state: "loaded", assigned_h_register: 84, offset_mm: "1" }),
      ],
      null,
      byT,
    );
    expect(rows.map((r) => r.t_number)).toEqual([84]);
    expect(rows.find((r) => r.t_number === 19)).toBeUndefined();
  });

  it("filters by search string", () => {
    const byT = indexToolsByT(
      [tool({ id: "1", short_id: "100084", t_number: 84, h_register: 84 })],
      [],
      "m1",
    );
    const rows = buildActiveLoadout(pots, spindle, byT);
    // Only T84 is joined to a tool (manufacturer OSG); others are NO REC.
    expect(filterActiveLoadout(rows, "osg").map((r) => r.t_number)).toEqual([84]);
    expect(filterActiveLoadout(rows, "t17").map((r) => r.t_number)).toEqual([17]);
    expect(filterActiveLoadout(rows, "zzzz")).toEqual([]);
  });
});
