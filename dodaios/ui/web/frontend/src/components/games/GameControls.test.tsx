import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GameSettingRow } from "@/components/games/GameControls";
import type { GameSetting } from "@/lib/gamesApi";

const SENS: GameSetting = {
  key: "sensitivity",
  label: "Mouse Sensitivity",
  type: "slider",
  min: 0,
  max: 8,
  step: 0.01,
  default: 1.25,
};

function renderRow(value?: number) {
  const onChange = vi.fn();
  render(<GameSettingRow setting={SENS} value={value} onChange={onChange} />);
  return {
    onChange,
    slider: screen.getByRole("slider", { name: "Mouse Sensitivity" }),
    number: screen.getByRole("textbox", { name: "Mouse Sensitivity" }) as HTMLInputElement,
  };
}

describe("slider rows", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("saves a drag released off the slider, once, with the last value", () => {
    const { onChange, slider, number } = renderRow(1);
    fireEvent.pointerDown(slider);
    fireEvent.change(slider, { target: { value: "2" } });
    fireEvent.change(slider, { target: { value: "3.5" } });
    // The number follows the thumb during the drag.
    expect(number.value).toBe("3.5");
    expect(onChange).not.toHaveBeenCalled();
    // Released somewhere above the slider, not on it.
    act(() => {
      window.dispatchEvent(new Event("pointerup"));
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(3.5);
  });

  it("blocks text selection only while dragging", () => {
    const { slider } = renderRow(1);
    const during = new Event("selectstart", { cancelable: true });
    fireEvent.pointerDown(slider);
    document.dispatchEvent(during);
    expect(during.defaultPrevented).toBe(true);
    act(() => {
      window.dispatchEvent(new Event("pointerup"));
    });
    const after = new Event("selectstart", { cancelable: true });
    document.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });

  it("saves a change without a release once it settles", () => {
    vi.useFakeTimers();
    const { onChange, slider } = renderRow(1);
    fireEvent.change(slider, { target: { value: "4" } });
    expect(onChange).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(onChange).toHaveBeenCalledWith(4);
  });

  it("shows the number of an untouched default as empty", () => {
    const { number } = renderRow(undefined);
    expect(number.value).toBe("");
  });
});
