import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { IdeLayoutSwitch } from "./IdeLayoutSwitch";
import { useIdeThreadsStore } from "@/store/ideThreads";

beforeEach(() => {
  localStorage.clear();
  useIdeThreadsStore.setState({ layout: "threads" });
});

afterEach(cleanup);

const checked = (id: string) => screen.getByTestId(`ide-layout-${id}`).getAttribute("aria-checked");

describe("IdeLayoutSwitch", () => {
  it("offers chat first, then the grid, each with a short word", () => {
    render(<IdeLayoutSwitch />);
    const radios = screen.getAllByRole("radio");
    expect(radios.map((button) => button.getAttribute("aria-label"))).toEqual(["Threads", "Terminal grid"]);
    expect(radios.map((button) => button.textContent)).toEqual(["Chat", "Grid"]);
    expect(checked("threads")).toBe("true");
  });

  it("switches the layout and marks the face that is on", () => {
    render(<IdeLayoutSwitch />);
    fireEvent.click(screen.getByTestId("ide-layout-grid"));
    expect(useIdeThreadsStore.getState().layout).toBe("grid");
    expect(checked("grid")).toBe("true");
    expect(checked("threads")).toBe("false");

    fireEvent.click(screen.getByTestId("ide-layout-threads"));
    expect(useIdeThreadsStore.getState().layout).toBe("threads");
    expect(checked("threads")).toBe("true");
  });

  it("drops to named icons on the rail", () => {
    render(<IdeLayoutSwitch railed />);
    for (const button of screen.getAllByRole("radio")) {
      expect(button.textContent).toBe("");
      expect(button.getAttribute("title")).toBe(button.getAttribute("aria-label"));
    }
  });
});
