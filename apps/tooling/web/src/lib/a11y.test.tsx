import { fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { useFocusTrap } from "@/lib/a11y";

function Trapped({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, true, onClose);
  return (
    <div ref={ref}>
      <button type="button">first</button>
      <button type="button">last</button>
    </div>
  );
}

describe("useFocusTrap", () => {
  it("focuses the first item on activation", () => {
    render(<Trapped onClose={() => {}} />);
    expect(screen.getByText("first")).toHaveFocus();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<Trapped onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("wraps Tab from the last item back to the first", () => {
    render(<Trapped onClose={() => {}} />);
    const last = screen.getByText("last");
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByText("first")).toHaveFocus();
  });
});
