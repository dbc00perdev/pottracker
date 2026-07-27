import type { Pot } from "@/types/api";

/**
 * Ring layout: pot numbers ascend clockwise.
 * When `anchorPot` is set (the pot holding NEXT), that pot sits at **6 o'clock**
 * so "what's next" reads bottom-center. Hub stays spindle (HEAD).
 * No "neighbor" role — adjacent pots are ordinary occupancy.
 */
export function potPosition(
  potNumber: number,
  potCount: number,
  anchorPot: number | null,
): { left: string; top: string } {
  const i = potNumber - 1;
  const ang =
    anchorPot != null
      ? (((i - (anchorPot - 1)) / potCount) * 2 * Math.PI + Math.PI / 2)
      : (i / potCount) * 2 * Math.PI - Math.PI / 2;
  const r = 41.5;
  return {
    left: `${50 + r * Math.cos(ang)}%`,
    top: `${50 + r * Math.sin(ang)}%`,
  };
}

/** Pot that currently holds NEXT (sticky cell), if mirrored. */
export function findNextPotNumber(pots: Pot[], nextT: number | null): number | null {
  if (nextT == null) return null;
  const hit = pots.find((p) => p.t_number === nextT);
  return hit?.pot_number ?? null;
}
