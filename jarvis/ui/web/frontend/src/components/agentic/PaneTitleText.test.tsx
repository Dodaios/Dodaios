import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PaneTitleText } from "./PaneTitleText";

const LONG = "Turn the Git tab of our app into a control center with branches and pull requests";

/** jsdom lays nothing out, so the two widths a title is measured by are given. */
function widths(scroll: number, client: number) {
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(scroll);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(client);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("pane title text", () => {
  it("writes a title out whole, with no ellipsis of its own", () => {
    widths(300, 300);
    render(<PaneTitleText text={LONG} data-testid="title" />);
    const title = screen.getByTestId("title");
    expect(title.textContent).toBe(LONG);
    expect(title.className).not.toContain("truncate");
    expect(title.getAttribute("data-clipped")).toBeNull();
    expect(title.style.maskImage).toBe("");
  });

  it("fades a title wider than its row instead of cutting it", () => {
    widths(640, 300);
    render(<PaneTitleText text={LONG} data-testid="title" />);
    const title = screen.getByTestId("title");
    expect(title.textContent).toBe(LONG);
    expect(title.getAttribute("data-clipped")).toBe("true");
    expect(title.style.maskImage).toContain("linear-gradient");
  });

  it("leaves a title that fits by a rounded pixel untouched", () => {
    widths(301, 300);
    render(<PaneTitleText text={LONG} data-testid="title" />);
    expect(screen.getByTestId("title").getAttribute("data-clipped")).toBeNull();
  });
});
