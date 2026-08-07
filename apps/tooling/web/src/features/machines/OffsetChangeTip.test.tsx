import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildChangeMap, changeKey, OffsetChangeTip } from "@/features/machines/OffsetChangeTip";
import type { OffsetChange } from "@/types/api";

function change(overrides: Partial<OffsetChange>): OffsetChange {
  return {
    register_number: 21,
    register_type: "h_geom",
    changed_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
    old_value: "3.4744",
    new_value: "5.6883",
    source: "presetter_verified",
    ...overrides,
  };
}

describe("OffsetChangeTip", () => {
  it("shows old → new, age and presetter attribution", () => {
    render(<OffsetChangeTip change={change({})}>5.6883</OffsetChangeTip>);
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent("3.4744");
    expect(tip).toHaveTextContent("5.6883");
    expect(tip).toHaveTextContent("2h ago");
    expect(tip).toHaveTextContent("presetter-verified");
  });

  it("labels a manual keypad edit", () => {
    render(<OffsetChangeTip change={change({ source: "manual_edit" })}>x</OffsetChangeTip>);
    expect(screen.getByRole("tooltip")).toHaveTextContent("manual edit");
  });

  it("shows first observation as a capture, not an edit", () => {
    render(
      <OffsetChangeTip change={change({ old_value: null, source: null })}>x</OffsetChangeTip>,
    );
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent("first observed");
    expect(tip).not.toHaveTextContent("manual");
  });

  it("is honest when no audit row exists", () => {
    render(<OffsetChangeTip change={undefined}>x</OffsetChangeTip>);
    expect(screen.getByRole("tooltip")).toHaveTextContent("no change recorded");
  });

  it("buildChangeMap keys by register/type", () => {
    const map = buildChangeMap([change({}), change({ register_number: 5, register_type: "tip" })]);
    expect(map.get(changeKey(21, "h_geom"))?.new_value).toBe("5.6883");
    expect(map.get(changeKey(5, "tip"))).toBeDefined();
    expect(map.get(changeKey(5, "h_geom"))).toBeUndefined();
  });
});
