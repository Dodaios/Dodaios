import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { DictationButton, formatElapsed } from "@/components/agentchat/DictationButton";

function renderButton(dictating: boolean, onToggle = vi.fn()) {
  return render(
    <DictationButton
      dictating={dictating}
      onToggle={onToggle}
      startLabel="Dictate"
      stopLabel="Stop dictation"
    />,
  );
}

describe("DictationButton", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  test("idle, it is only the microphone and starts a dictation", () => {
    const onToggle = vi.fn();
    renderButton(false, onToggle);
    expect(screen.queryByTestId("dictation-status")).toBeNull();
    const mic = screen.getByTestId("dictation-button");
    expect(mic.getAttribute("aria-label")).toBe("Dictate");
    expect(mic.hasAttribute("data-jarvis-dictation-trigger")).toBe(true);
    fireEvent.click(mic);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  test("an idle-only size reaches the microphone but never the recording pill", () => {
    const props = { onToggle: vi.fn(), startLabel: "Dictate", stopLabel: "Stop dictation", idleClassName: "w-9" };
    const { rerender } = render(<DictationButton dictating={false} {...props} />);
    expect(screen.getByTestId("dictation-button").className).toContain("w-9");
    rerender(<DictationButton dictating {...props} />);
    // A fixed 36px width squeezed dot, wave, timer and stop over the Send button.
    expect(screen.getByTestId("dictation-status").className).not.toContain("w-9");
  });

  test("live, it announces itself, shows the waveform and counts up", () => {
    renderButton(true);
    const pill = screen.getByTestId("dictation-status");
    expect(pill.getAttribute("role")).toBe("status");
    expect(pill.textContent).toContain("Listening");
    expect(pill.textContent).toContain("0:00");
    expect(screen.getByTestId("dictation-waveform").children.length).toBeGreaterThan(0);
    act(() => {
      vi.advanceTimersByTime(7_000);
    });
    expect(screen.getByTestId("dictation-status").textContent).toContain("0:07");
  });

  test("the stop sits inside the pill and ends the dictation", () => {
    const onToggle = vi.fn();
    renderButton(true, onToggle);
    const stop = screen.getByTestId("dictation-stop");
    expect(stop.getAttribute("aria-label")).toBe("Stop dictation");
    fireEvent.click(stop);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  test("the clock restarts with the next dictation instead of carrying over", () => {
    const view = renderButton(true);
    act(() => {
      vi.advanceTimersByTime(65_000);
    });
    expect(screen.getByTestId("dictation-status").textContent).toContain("1:05");
    view.rerender(<DictationButton dictating={false} onToggle={vi.fn()} startLabel="Dictate" stopLabel="Stop dictation" />);
    view.rerender(<DictationButton dictating onToggle={vi.fn()} startLabel="Dictate" stopLabel="Stop dictation" />);
    expect(screen.getByTestId("dictation-status").textContent).toContain("0:00");
  });

  test("transcribing, it is a pill with a spinner and a line, and no stop", () => {
    const props = { onToggle: vi.fn(), startLabel: "Dictate", stopLabel: "Stop dictation" };
    render(<DictationButton dictating={false} transcribing {...props} />);
    const pill = screen.getByTestId("dictation-transcribing");
    expect(pill.getAttribute("role")).toBe("status");
    expect(pill.getAttribute("aria-live")).toBe("polite");
    expect(pill.textContent).toBe("Transcribing…");
    expect(pill.querySelector("svg")?.getAttribute("class")).toContain("motion-safe:animate-spin");
    // The recording is over: nothing here starts or stops one.
    expect(pill.querySelector("button")).toBeNull();
    expect(screen.queryByTestId("dictation-button")).toBeNull();
    expect(screen.queryByTestId("dictation-stop")).toBeNull();
    expect(screen.queryByTestId("dictation-status")).toBeNull();
  });

  test("transcribing with a send queued, the line says the message goes out when ready", () => {
    const props = { onToggle: vi.fn(), startLabel: "Dictate", stopLabel: "Stop dictation" };
    render(<DictationButton dictating={false} transcribing sendQueued {...props} />);
    expect(screen.getByTestId("dictation-transcribing").textContent).toBe("Sending when ready…");
  });

  test("transcribing is neutral, not the green of a live microphone", () => {
    const props = { onToggle: vi.fn(), startLabel: "Dictate", stopLabel: "Stop dictation", idleClassName: "w-9" };
    render(<DictationButton dictating={false} transcribing {...props} />);
    const classes = screen.getByTestId("dictation-transcribing").className;
    expect(classes).toContain("border-border");
    expect(classes).toContain("bg-secondary");
    expect(classes).toContain("text-muted-foreground");
    expect(classes).not.toContain("success");
    // The idle-only size would crush the line.
    expect(classes).not.toContain("w-9");
  });

  test("goes from recording to transcribing to the idle microphone", () => {
    const props = { onToggle: vi.fn(), startLabel: "Dictate", stopLabel: "Stop dictation" };
    const { rerender } = render(<DictationButton dictating {...props} />);
    expect(screen.getByTestId("dictation-status")).toBeTruthy();
    rerender(<DictationButton dictating={false} transcribing {...props} />);
    expect(screen.queryByTestId("dictation-status")).toBeNull();
    expect(screen.getByTestId("dictation-transcribing")).toBeTruthy();
    rerender(<DictationButton dictating={false} transcribing={false} {...props} />);
    expect(screen.queryByTestId("dictation-transcribing")).toBeNull();
    expect(screen.getByTestId("dictation-button")).toBeTruthy();
  });

  test("a live microphone wins over a transcribing flag", () => {
    const props = { onToggle: vi.fn(), startLabel: "Dictate", stopLabel: "Stop dictation" };
    render(<DictationButton dictating transcribing {...props} />);
    expect(screen.getByTestId("dictation-status")).toBeTruthy();
    expect(screen.queryByTestId("dictation-transcribing")).toBeNull();
  });

  test("formats elapsed time as m:ss", () => {
    expect(formatElapsed(0)).toBe("0:00");
    expect(formatElapsed(102_400)).toBe("1:42");
  });
});
