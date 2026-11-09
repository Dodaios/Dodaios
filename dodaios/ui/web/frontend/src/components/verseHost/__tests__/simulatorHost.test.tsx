import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useEventStore } from "@/store/events";
import { handleVerseOpen } from "../openRequest";
import { ASTEROID_BEST_KEY, programmeById, SimulatorHost } from "../SimulatorHost";

const report = vi.fn();
vi.mock("@/components/society/progression/progressionApi", () => ({
  reportWorldAction: (...args: unknown[]) => report(...args),
}));
vi.mock("@/components/society/arcade/RetroArcadeOverlay", () => ({
  RetroArcadeOverlay: ({ gameId, onClose }: { gameId: string; onClose: () => void }) => (
    <button data-testid={`retro-${gameId}`} onClick={onClose}>retro</button>
  ),
}));
vi.mock("@/components/society/arcade/ArcadeCabinet", () => ({
  ArcadeCabinet: ({ onClose }: { onClose: () => void }) => (
    <button data-testid="asteroid-cabinet" onClick={() => { window.localStorage.setItem("jarvis.office.arcade.asteroids.best", "900"); onClose(); }}>3d</button>
  ),
}));

describe("Verse.Parity.S-07 simulator.open opens the web arcade", () => {
  afterEach(() => { report.mockClear(); window.localStorage.clear(); });

  it("opens the named retro programme and closes back to nothing", async () => {
    useEventStore.setState({ solo: false } as never);
    render(<SimulatorHost />);
    expect(screen.queryByTestId("verse-simulator-host")).toBeNull();
    act(() => { handleVerseOpen({ target: "simulator", programme: "neon-snake" }); });
    const retro = await screen.findByTestId("retro-neon-snake");
    expect(useEventStore.getState().activeSection).toBe("agents");
    act(() => retro.click());
    expect(screen.queryByTestId("verse-simulator-host")).toBeNull();
    expect(report).not.toHaveBeenCalled();
  });

  it("ignores a programme this build does not have", () => {
    useEventStore.setState({ solo: false } as never);
    render(<SimulatorHost />);
    act(() => { handleVerseOpen({ target: "simulator", programme: "nope" }); });
    expect(screen.queryByTestId("verse-simulator-host")).toBeNull();
    expect(programmeById("nope")).toBeNull();
  });
});

describe("Verse.Parity.W-06 simulator_record when the asteroid best rises", () => {
  afterEach(() => { report.mockClear(); window.localStorage.clear(); });

  it("reports once when the run ends with a higher best", async () => {
    useEventStore.setState({ solo: false } as never);
    window.localStorage.setItem(ASTEROID_BEST_KEY, "400");
    render(<SimulatorHost />);
    act(() => { handleVerseOpen({ target: "simulator", programme: "asteroid-run" }); });
    const cabinet = await screen.findByTestId("asteroid-cabinet");
    act(() => cabinet.click());
    expect(report).toHaveBeenCalledTimes(1);
    expect(report).toHaveBeenCalledWith("simulator_record", "asteroid-run");
  });

  it("reports nothing when the best did not rise", async () => {
    useEventStore.setState({ solo: false } as never);
    window.localStorage.setItem(ASTEROID_BEST_KEY, "900");
    render(<SimulatorHost />);
    act(() => { handleVerseOpen({ target: "simulator", programme: "asteroid-run" }); });
    const cabinet = await screen.findByTestId("asteroid-cabinet");
    act(() => cabinet.click());
    expect(report).not.toHaveBeenCalled();
  });
});
