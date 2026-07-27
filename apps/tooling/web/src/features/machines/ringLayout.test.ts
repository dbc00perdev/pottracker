import { describe, expect, it } from "vitest";

import { findNextPotNumber, potPosition } from "@/features/machines/ringLayout";
import type { Pot } from "@/types/api";

describe("ringLayout", () => {
  it("puts anchor pot at 6 o'clock (bottom center)", () => {
    // 6 o'clock: left=50%, top > 50%
    const p = potPosition(7, 24, 7);
    expect(parseFloat(p.left)).toBeCloseTo(50, 5);
    expect(parseFloat(p.top)).toBeGreaterThan(90);
  });

  it("without anchor, pot 1 is at 12 o'clock (top center)", () => {
    const p = potPosition(1, 24, null);
    expect(parseFloat(p.left)).toBeCloseTo(50, 5);
    expect(parseFloat(p.top)).toBeLessThan(10);
  });

  it("finds the pot holding NEXT", () => {
    const pots = [
      { pot_number: 3, t_number: 33 },
      { pot_number: 1, t_number: 84 },
    ] as Pot[];
    expect(findNextPotNumber(pots, 33)).toBe(3);
    expect(findNextPotNumber(pots, 99)).toBeNull();
    expect(findNextPotNumber(pots, null)).toBeNull();
  });
});
