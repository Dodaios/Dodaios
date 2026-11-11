import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { IdeLayoutSwitch } from "./IdeLayoutSwitch";
import { useIdeThreadsStore } from "@/store/ideThreads";

beforeEach(() => {
  localStorage.clear();
  useIdeThreadsStore.setState({ layout: "grid" });
});

afterEach(cleanup);

const checked = (id: string) => screen.getByTestId(`ide-layout-${id}`).getAttribute("aria-checked");

describe("IdeLayoutSwitch", () => {
  it("offers grid and threads as icon buttons", () => {
    render(<IdeLayoutSwitch />);
    expect(screen.getAllByRole("radio").map((button) => button.getAttribute("aria-label")))
      .toEqual(["Terminal grid", "Threads"]);
    for (const button of screen.getAllByRole("radio")) expect(button.textContent).toBe("");
    expect(checked("grid")).toBe("true");
  });

  it("switches the layout and marks the face that is on", () => {
    render(<IdeLayoutSwitch />);
    fireEvent.click(screen.getByTestId("ide-layout-threads"));
    expect(useIdeThreadsStore.getState().layout).toBe("threads");
    expect(checked("threads")).toBe("true");
    expect(checked("grid")).toBe("false");

    fireEvent.click(screen.getByTestId("ide-layout-grid"));
    expect(useIdeThreadsStore.getState().layout).toBe("grid");
    expect(checked("grid")).toBe("true");
  });
});
