/**
 * The rank surfaces in the DOM: the plate draws its rank's tiles, the card
 * shows the commander's rank and opens the record, the record is a dialog
 * with its five pages (the uniform choice among them), and the promotion
 * notice tells a new rank, steps aside for a plain level-up and lets officers'
 * toasts go.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import { LEVEL_XP } from "../../progression/levelCatalog";
import { LOCAL_REWARDS, type ProgressionSnapshot } from "../../progression/progressionApi";
import { celebrationOf, useProgression } from "../../progression/progressionStore";
import { NOTICE_MS, PromotionNotice, TILE_STEP_MS, TOAST_MS } from "./PromotionNotice";
import { RankCard } from "./RankCard";
import { RankPlate } from "./RankPlate";
import { RanksOverlay } from "./RanksOverlay";
import { ServiceRecord } from "./ServiceRecord";

const CREW = [{ agentId: "scout", name: "Scout" }, { agentId: "forge", name: "Forge" }];

function snapshot(over: Partial<ProgressionSnapshot> = {}): ProgressionSnapshot {
  return {
    subjects: [], petId: "gigi", recent: [], latestSeq: 0, maxLevel: 50, levelXp: [...LEVEL_XP], rules: [
      { source: "chat_turn", kind: "person", xp: 5, trigger: "server", cooldownS: 0, dailyCap: 100 },
      { source: "simulator_round", kind: "person", xp: 8, trigger: "world", cooldownS: 45, dailyCap: 80 },
      { source: "holodeck_round", kind: "person", xp: 8, trigger: "world", cooldownS: 45, dailyCap: 80 },
      { source: "task_done", kind: "agent", xp: 40, trigger: "server", cooldownS: 0, dailyCap: 0 },
    ],
    rewards: [...LOCAL_REWARDS], ranks: [], titles: { person: [], agent: [], pet: [] }, looks: {}, ...over,
  };
}

function seed(level: number, extra: Partial<ProgressionSnapshot> = {}) {
  const xp = LEVEL_XP[level - 1] + 10;
  useProgression.setState({
    snapshot: snapshot(extra),
    subjects: {
      person: { subjectId: "person", kind: "person", xp, level, xpIntoLevel: 10, xpForNext: (LEVEL_XP[level] ?? xp) - LEVEL_XP[level - 1], title: "cadet" },
      "agent:scout": { subjectId: "agent:scout", kind: "agent", xp: LEVEL_XP[14], level: 15, xpIntoLevel: 0, xpForNext: 100, title: "" },
    },
    banners: [], toasts: [], popups: [], record: null, uniform: "auto",
  });
}

beforeAll(async () => {
  await loadLocaleChunk("ship");
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("RankPlate", () => {
  it("lays the rank's tiles into the six slots, and only as many as revealed", () => {
    const { container, rerender } = render(<RankPlate rank="lieutenant" label="Lieutenant" />);
    expect(screen.getByRole("img", { name: "Lieutenant" })).toBeTruthy();
    const lit = () => [...container.querySelectorAll("[data-slot]")].map((g) => g.getAttribute("data-lit"));
    expect(lit()).toEqual(["true", "false", "true", "false", "false", "false"]);
    rerender(<RankPlate rank="lieutenant" label="Lieutenant" revealed={1} />);
    expect(lit()).toEqual(["true", "false", "false", "false", "false", "false"]);
    rerender(<RankPlate rank="fleet_admiral" />);
    expect(lit().every((v) => v === "true")).toBe(true);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("RankCard", () => {
  beforeEach(() => seed(15));

  it("shows the rank derived from the level, not the server's old title, and opens the record", () => {
    render(<RankCard />);
    const card = screen.getByRole("button", { name: /Lieutenant/ });
    expect(card.getAttribute("data-rank")).toBe("lieutenant");
    expect(card.textContent).toContain("Line officers");
    expect(card.textContent).toMatch(/to Senior Lieutenant/);
    fireEvent.click(card);
    expect(useProgression.getState().record).toBe("record");
  });

  it("has a compact form that still opens the record and tells the stage", () => {
    const onOpen = vi.fn();
    render(<RankCard compact onOpen={onOpen} />);
    const card = screen.getByRole("button", { name: /Lieutenant/ });
    expect(card.getAttribute("data-compact")).toBe("true");
    expect(card.textContent).not.toContain("Line officers");
    fireEvent.click(card);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(useProgression.getState().record).toBe("record");
  });

  it("reads as a recruit before the first answer", () => {
    useProgression.setState({ snapshot: null, subjects: {} });
    render(<RankCard />);
    expect(screen.getByRole("button", { name: /Recruit/ }).getAttribute("data-rank")).toBe("recruit");
  });
});

describe("ServiceRecord", () => {
  beforeEach(() => seed(30));

  it("is closed until the store opens it, and closes on Escape", () => {
    render(<ServiceRecord crew={CREW} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    act(() => useProgression.getState().openRecord("record"));
    const dialog = screen.getByRole("dialog", { name: "Service record" });
    expect(within(dialog).getByText("Line Captain")).toBeTruthy();
    expect(within(dialog).getAllByRole("tab")).toHaveLength(5);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(useProgression.getState().record).toBeNull();
  });

  it("marks the current rank on the ladder and dims the ranks ahead", () => {
    render(<ServiceRecord crew={CREW} />);
    act(() => useProgression.getState().openRecord("ladder"));
    const current = document.querySelector('[aria-current="step"]');
    expect(current?.textContent).toContain("Line Captain");
    expect(document.querySelectorAll('.vr-step[data-state="ahead"]')).toHaveLength(5);
    expect(document.querySelectorAll('.vr-step[data-state="held"]')).toHaveLength(9);
  });

  it("lets the commander wear an issued uniform but not one still locked", () => {
    render(<ServiceRecord crew={CREW} />);
    act(() => useProgression.getState().openRecord("rewards"));
    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => r.getAttribute("data-uniform"))).toEqual(["auto", "deck", "line", "command", "flag"]);
    expect(radios[0].getAttribute("aria-checked")).toBe("true");
    expect((radios[4] as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(radios[2]);
    expect(useProgression.getState().uniform).toBe("line");
    expect(screen.getByText("Good Conduct Ribbon")).toBeTruthy();
    useProgression.getState().chooseUniform("auto");
  });

  it("explains only the rules this build knows, with their limits", () => {
    render(<ServiceRecord crew={CREW} />);
    act(() => useProgression.getState().openRecord("earn"));
    const sources = [...document.querySelectorAll("[data-source]")].map((li) => li.getAttribute("data-source"));
    expect(sources).toEqual(["chat_turn", "simulator_round", "task_done"]);
    expect(document.querySelector('[data-source="simulator_round"]')?.textContent).toContain("up to 80 a day");
  });

  it("lists the crew by rank with the companion drone", () => {
    render(<ServiceRecord crew={CREW} companionName="Gigi" />);
    act(() => useProgression.getState().openRecord("crew"));
    const rows = [...document.querySelectorAll("tbody tr")].map((tr) => tr.getAttribute("data-agent"));
    expect(rows).toEqual(["scout", "forge", "companion"]);
    expect(document.querySelector('[data-agent="scout"]')?.textContent).toContain("Lieutenant");
    expect(document.querySelector('[data-agent="companion"]')?.textContent).toContain("Gigi");
  });
});

describe("RanksOverlay", () => {
  beforeEach(() => seed(14));

  it("draws nothing while the Verse is not active", () => {
    useProgression.setState({ banners: [celebrationOf({ subjectId: "person", kind: "person", level: 14, previousLevel: 13, title: "", unlocked: [] })] });
    const { container, rerender } = render(<RanksOverlay active={false} />);
    expect(container.innerHTML).toBe("");
    rerender(<RanksOverlay active />);
    expect(screen.getByRole("status", { name: /Promotion: Lieutenant/ })).toBeTruthy();
  });
});

describe("PromotionNotice", () => {
  beforeEach(() => seed(14));

  it("tells the commander's new rank, lays the tiles on and goes by itself", () => {
    vi.useFakeTimers();
    const party = celebrationOf({ subjectId: "person", kind: "person", level: 14, previousLevel: 13, title: "", unlocked: [] });
    useProgression.setState({ banners: [party] });
    render(<PromotionNotice crew={CREW} />);
    const notice = screen.getByRole("status", { name: /Promotion: Lieutenant/ });
    expect(notice.textContent).toContain("A commission is yours");
    const lit = () => notice.querySelectorAll('[data-lit="true"]').length;
    expect(lit()).toBe(0);
    act(() => { vi.advanceTimersByTime(TILE_STEP_MS * 2); });
    expect(lit()).toBe(2);
    act(() => { vi.advanceTimersByTime(NOTICE_MS); });
    expect(useProgression.getState().banners).toHaveLength(0);
  });

  it("names what the quartermaster issued and closes on Acknowledge", () => {
    const party = celebrationOf({ subjectId: "person", kind: "person", level: 11, previousLevel: 10, title: "", unlocked: ["uniform_line"] });
    useProgression.setState({ banners: [party] });
    render(<PromotionNotice />);
    expect(screen.getByText("Issued: Line tunic")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Acknowledge" }));
    expect(useProgression.getState().banners).toHaveLength(0);
  });

  it("turns a level-up without a new rank into a quiet line", () => {
    const party = celebrationOf({ subjectId: "person", kind: "person", level: 15, previousLevel: 14, title: "", unlocked: [] });
    useProgression.setState({ banners: [party] });
    render(<PromotionNotice />);
    expect(screen.queryByRole("button", { name: "Acknowledge" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "You reached level 15" }));
    expect(useProgression.getState().banners).toHaveLength(0);
  });

  it("names the companion drone in its quiet line", () => {
    const party = celebrationOf({ subjectId: "pet:gigi", kind: "pet", level: 4, previousLevel: 3, title: "", unlocked: [] });
    useProgression.setState({ banners: [party] });
    const { unmount } = render(<PromotionNotice />);
    expect(screen.getByRole("button", { name: "Companion drone reached level 4" })).toBeTruthy();
    unmount();
    render(<PromotionNotice companionName="Gigi" />);
    expect(screen.getByRole("button", { name: "Gigi reached level 4" })).toBeTruthy();
  });

  it("gives the drone's new rank the full notice", () => {
    const party = celebrationOf({ subjectId: "pet:gigi", kind: "pet", level: 5, previousLevel: 4, title: "", unlocked: [] });
    useProgression.setState({ banners: [party] });
    render(<PromotionNotice companionName="Gigi" />);
    expect(screen.getByRole("status", { name: /Companion drone promoted: Technician/ })).toBeTruthy();
  });

  it("shows an officer's promotion as a toast that goes after a while", () => {
    vi.useFakeTimers();
    const party = celebrationOf({ subjectId: "agent:scout", kind: "agent", level: 11, previousLevel: 10, title: "", unlocked: [] });
    useProgression.setState({ toasts: [party] });
    render(<PromotionNotice crew={CREW} />);
    expect(screen.getByRole("button", { name: "Scout promoted to Ensign" })).toBeTruthy();
    act(() => { vi.advanceTimersByTime(TOAST_MS + 10); });
    expect(useProgression.getState().toasts).toHaveLength(0);
  });
});
