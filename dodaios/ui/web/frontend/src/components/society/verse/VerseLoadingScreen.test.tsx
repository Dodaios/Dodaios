import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VerseLoadingScreen } from "./VerseLoadingScreen";

describe("VerseLoadingScreen", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("shows a busy progress bar below 100 % while the deck loads", () => {
    render(<VerseLoadingScreen />);
    const bar = screen.getByRole("progressbar");
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(Number(bar.getAttribute("aria-valuenow"))).toBeLessThan(100);
    expect(screen.getByRole("status").getAttribute("aria-busy")).toBe("true");
  });

  it("fills the bar, fades out and reports gone once the deck is ready", () => {
    const onGone = vi.fn();
    const { rerender } = render(<VerseLoadingScreen onGone={onGone} />);
    rerender(<VerseLoadingScreen ready onGone={onGone} />);
    // It never just flashes: the bar fills only after the minimum time on screen.
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).not.toBe("100");
    act(() => { vi.advanceTimersByTime(1200); });
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("100");
    act(() => { vi.advanceTimersByTime(300); });
    expect(screen.getByRole("status").dataset.leaving).toBe("true");
    expect(onGone).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(600); });
    expect(onGone).toHaveBeenCalledTimes(1);
  });
});
