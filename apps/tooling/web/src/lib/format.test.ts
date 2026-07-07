import { describe, expect, it } from "vitest";

import { compactSpec, inch, mm, mmToInch, timeAgo } from "@/lib/format";

describe("format", () => {
  it("mm renders 4 decimals and handles null", () => {
    expect(mm("6.35")).toBe("6.3500");
    expect(mm(63.5042)).toBe("63.5042");
    expect(mm(null)).toBe("—");
  });

  it("inch renders 5 decimals", () => {
    expect(inch("0.25")).toBe("0.25000");
    expect(inch(null)).toBe("—");
  });

  it("mmToInch converts and renders 5 decimals", () => {
    expect(mmToInch("25.4")).toBe("1.00000");
    expect(mmToInch("6.35")).toBe("0.25000");
    expect(mmToInch(null)).toBe("—");
  });

  it("compactSpec joins present fields only", () => {
    expect(
      compactSpec({ diameter_mm: "6.35", flute_count: 4, substrate: "carbide", coating: "tialn" }),
    ).toBe("6.3500mm 4F carbide, tialn");
    expect(
      compactSpec({ diameter_mm: "6.35", flute_count: null, substrate: null, coating: null }),
    ).toBe("6.3500mm");
  });

  it("timeAgo buckets seconds/minutes/hours from a fixed now", () => {
    const now = new Date("2026-07-07T12:00:00Z").getTime();
    expect(timeAgo("2026-07-07T11:59:30Z", now)).toBe("30s ago");
    expect(timeAgo("2026-07-07T11:55:00Z", now)).toBe("5m ago");
    expect(timeAgo(null, now)).toBe("—");
  });
});
