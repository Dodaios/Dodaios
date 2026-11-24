import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { collectContextActions } from "@/lib/contextActions";
import { useContextActions } from "./useContextActions";

afterEach(cleanup);

function Box({ label }: { label: string | null }) {
  const ref = useContextActions(label ? () => [{ id: "a", label, run: () => {} }] : null);
  return <div ref={ref} data-testid="box"><span>inner</span></div>;
}

describe("useContextActions", () => {
  it("gives the element and its children the latest entries", () => {
    const { getByText, rerender } = render(<Box label="Copy message" />);
    expect(collectContextActions(getByText("inner"))[0]?.[0]?.label).toBe("Copy message");
    rerender(<Box label="Copy answer" />);
    expect(collectContextActions(getByText("inner"))[0]?.[0]?.label).toBe("Copy answer");
    rerender(<Box label={null} />);
    expect(collectContextActions(getByText("inner"))).toEqual([]);
  });

  it("detaches on unmount", () => {
    const { getByTestId, unmount } = render(<Box label="x" />);
    const box = getByTestId("box");
    unmount();
    expect(box.hasAttribute("data-context-actions")).toBe(false);
  });
});
