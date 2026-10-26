/**
 * The duel's HUD and start panel: choosing an opponent starts that duel,
 * the in-match HUD shows the score and the vitals, the pause screen resumes
 * or leaves, the result screen offers a rematch or the way back.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createLocalDuel } from "../combat/session";
import { DuelController } from "../duel/duelController";
import { StageRuntime } from "../runtime";
import { DuelHud } from "./DuelHud";
import { DuelPanel } from "./DuelPanel";

const t = (key: string) => key;

afterEach(cleanup);

function setup() {
  const runtime = new StageRuntime();
  runtime.view.resize({ width: 1600, height: 900, dpr: 1 });
  const clock = { now: 0 };
  const controller = new DuelController({
    sound: null,
    now: () => clock.now,
    create: (o) => createLocalDuel({ ...o, seed: 5, config: { roundsToWin: 1, maxRounds: 1 } }),
  });
  const frame = (n: number) => {
    for (let i = 0; i < n; i++) {
      clock.now += 1000 / 60;
      controller.frame(1000 / 60);
      for (const fn of runtime.afterFrame) fn();
    }
  };
  return { runtime, controller, frame };
}

describe("duel start panel", () => {
  it("starts the chosen difficulty and says when the lift ride comes first", () => {
    const onStart = vi.fn();
    render(<DuelPanel t={t} ride last="hard" onStart={onStart} onClose={() => undefined} />);
    expect(screen.getByText(/verse\.duel\.ride/)).toBeTruthy();
    fireEvent.click(screen.getByText("verse.duel.difficulty.elite"));
    expect(onStart).toHaveBeenCalledWith("elite");
  });

  it("lists every control", () => {
    render(<DuelPanel t={t} ride={false} last="normal" onStart={() => undefined} onClose={() => undefined} />);
    for (const key of ["fire", "ads", "shield", "dodge", "vent", "pause"]) expect(screen.getByText(`verse.duel.controls.${key}`)).toBeTruthy();
    expect(screen.queryByText(/verse\.duel\.ride/)).toBeNull();
  });
});

describe("duel HUD", () => {
  it("draws the score, the vitals and the countdown while the match runs", () => {
    const { runtime, controller, frame } = setup();
    controller.start("normal");
    render(<DuelHud runtime={runtime} controller={controller} phase="running" locked t={t} onResume={() => undefined} onLeave={() => undefined} onRematch={() => undefined} />);
    act(() => frame(20));
    expect(screen.getByText("verse.duel.hud.you")).toBeTruthy();
    expect(screen.getByText("verse.duel.hud.health")).toBeTruthy();
    expect(screen.getByText("verse.duel.hud.heat")).toBeTruthy();
    expect(document.querySelector(".verse-duel-banner[data-kind='countdown']")).toBeTruthy();
    expect(document.querySelector(".verse-duel-cross")).toBeTruthy();
    // Without the pointer lock the HUD offers to take it.
    cleanup();
    const onResume = vi.fn();
    render(<DuelHud runtime={runtime} controller={controller} phase="running" locked={false} t={t} onResume={onResume} onLeave={() => undefined} onRematch={() => undefined} />);
    act(() => frame(1));
    fireEvent.click(screen.getByText("verse.duel.hud.click_to_aim"));
    expect(onResume).toHaveBeenCalled();
  });

  it("pauses with resume and leave", () => {
    const { runtime, controller, frame } = setup();
    controller.start("hard");
    act(() => frame(5));
    controller.pause();
    const onResume = vi.fn();
    const onLeave = vi.fn();
    render(<DuelHud runtime={runtime} controller={controller} phase="paused" locked={false} t={t} onResume={onResume} onLeave={onLeave} onRematch={() => undefined} />);
    fireEvent.click(screen.getByText("verse.duel.pause.resume"));
    fireEvent.click(screen.getByText("verse.duel.pause.leave"));
    expect(onResume).toHaveBeenCalled();
    expect(onLeave).toHaveBeenCalled();
  });

  it("shows the result with stats, a rematch and the way back", () => {
    const { runtime, controller, frame } = setup();
    controller.start("elite");
    let n = 0;
    while (controller.phase === "running" && n < 60 * 120) { frame(1); n++; }
    expect(controller.phase).toBe("result");
    const onRematch = vi.fn();
    const onLeave = vi.fn();
    render(<DuelHud runtime={runtime} controller={controller} phase="result" locked={false} t={t} onResume={() => undefined} onLeave={onLeave} onRematch={onRematch} />);
    expect(screen.getByText("verse.duel.result.lost")).toBeTruthy();
    expect(screen.getByText("verse.duel.result.accuracy")).toBeTruthy();
    fireEvent.click(screen.getByText("verse.duel.result.rematch"));
    fireEvent.click(screen.getByText("verse.duel.result.leave"));
    expect(onRematch).toHaveBeenCalled();
    expect(onLeave).toHaveBeenCalled();
  });
});
