/**
 * The level UI in the DOM: the insignia draws what its rank wears, the
 * service record is an accessible dialog (tabs, Escape, focus trap, the suit
 * choice), and the promotion layer shows the ceremony and the crew's toasts
 * and lets them go.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import type { ProgressionSnapshot, RewardRow } from "../../progression/progressionApi";
import { celebrationOf, useProgression } from "../../progression/progressionStore";
import { slotOf } from "../../progression/levelCatalog";
import { Insignia } from "./Insignia";
import { ServiceRecord } from "./ServiceRecord";
import { CEREMONY_MS, PromotionLayer, TOAST_MS } from "./PromotionCeremony";

vi.mock("../../data", () => ({
  useSocietyRoster: () => ({
    data: { agents: [
      { agentId: "jarvis", name: "Gigi", tier: "lead" },
      { agentId: "scout", name: "Scout", tier: "member" },
      { agentId: "forge", name: "Forge", tier: "member" },
    ] },
  }),
}));

const CURVE = Array.from({ length: 50 }, (_, i) => i * i * 20);
const reward = (id: RewardRow["rewardId"], person: number): RewardRow => ({ rewardId: id, slot: slotOf(id), levels: { person, agent: null, pet: null } });

function snapshot(): ProgressionSnapshot {
  return {
    subjects: [
      { subjectId: "person", kind: "person", xp: CURVE[16] + 40, level: 17, xpIntoLevel: 40, xpForNext: CURVE[17] - CURVE[16], title: "ensign" },
      { subjectId: "agent:scout", kind: "agent", xp: 900, level: 8, xpIntoLevel: 0, xpForNext: 100, title: "petty_officer" },
    ],
    petId: "gigi",
    recent: [
      { seq: 1, subjectId: "person", kind: "person", source: "dog_petted", xp: 3, levelBefore: 16, levelAfter: 16, ref: "", tsMs: Date.now() - 60_000 },
      { seq: 2, subjectId: "person", kind: "person", source: "warp_jump", xp: 5, levelBefore: 16, levelAfter: 16, ref: "gas_giant@1", tsMs: Date.now() },
    ],
    latestSeq: 2, maxLevel: 50, levelXp: CURVE,
    rules: [{ source: "chat_turn", kind: "person", xp: 5, trigger: "server", cooldownS: 0, dailyCap: 100 }],
    rewards: [reward("suit_field_armor", 6), reward("suit_command_coat", 16), reward("suit_dress_whites", 26), reward("destination_gas_giant", 5), reward("destination_ice_moon", 20)],
    ranks: [], titles: { person: [], agent: [], pet: [] }, looks: {},
  };
}

beforeAll(async () => { await loadLocaleChunk("ship"); });
beforeEach(() => {
  useProgression.setState({ snapshot: null, subjects: {}, banners: [], toasts: [], suit: "auto", record: null });
  useProgression.getState().hydrate(snapshot(), []);
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("Insignia", () => {
  it("draws chevrons, pips and stars, and is decorative without a title", () => {
    const { container, rerender } = render(<Insignia rank="petty_officer" />);
    expect(container.querySelectorAll("polygon")).toHaveLength(3);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    rerender(<Insignia rank="lieutenant_commander" title="Lieutenant Commander" size={64} />);
    expect(container.querySelectorAll("circle")).toHaveLength(3);
    expect(screen.getByRole("img", { name: "Lieutenant Commander" }).getAttribute("width")).toBe("64");
    rerender(<Insignia rank="admiral" />);
    expect(container.querySelectorAll("polygon")).toHaveLength(4);
    rerender(<Insignia rank="cadet" tone="muted" />);
    expect(container.querySelector("defs")).toBeNull();
  });
});

describe("ServiceRecord", () => {
  it("is a dialog that opens on the asked page and closes on Escape", () => {
    const onClose = vi.fn();
    render(<ServiceRecord onClose={onClose} initialTab="ranks" />);
    const dialog = screen.getByRole("dialog", { name: "Service record" });
    expect(screen.getByRole("tab", { name: "Ranks" }).getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: "Ranks" }));
    expect(within(dialog).getByText("Your rank")).toBeTruthy();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows the record with the next promotion and a log in words", () => {
    render(<ServiceRecord onClose={() => {}} />);
    expect(screen.getAllByText("Ensign").length).toBeGreaterThan(0);
    expect(screen.getByText("Lieutenant Junior Grade at level 19")).toBeTruthy();
    expect(screen.getByText("Jumped to Banded Giant")).toBeTruthy();
    expect(screen.getByText("Petted the office dog")).toBeTruthy();
  });

  it("moves between pages with the arrow keys and keeps focus inside", () => {
    render(<ServiceRecord onClose={() => {}} />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Record" }), { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "Crew" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("Scout")).toBeTruthy();
    const dialog = screen.getByRole("dialog");
    const closeButton = screen.getByRole("button", { name: "Close" });
    const focusables = dialog.querySelectorAll<HTMLElement>("button:not([disabled]), [tabindex]:not([tabindex='-1'])");
    focusables[focusables.length - 1].focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(focusables[0]);
    expect(closeButton).toBeTruthy();
  });

  it("lets the captain choose an open suit, never a locked one", () => {
    render(<ServiceRecord onClose={() => {}} initialTab="rewards" />);
    const group = screen.getByRole("radiogroup", { name: "Suit to wear" });
    expect(within(group).getByRole("radio", { name: /Automatic/ }).getAttribute("aria-checked")).toBe("true");
    // Automatic wears the finest suit open at level 17.
    expect(within(within(group).getByRole("radio", { name: /Command Coat/ })).getByText("Wearing")).toBeTruthy();
    fireEvent.click(within(group).getByRole("radio", { name: /Field Armour/ }));
    expect(useProgression.getState().suit).toBe("suit_field_armor");
    fireEvent.click(within(group).getByRole("radio", { name: /Dress Whites/ }));
    expect(useProgression.getState().suit).toBe("suit_field_armor");
    expect(screen.getByText("Banded Giant")).toBeTruthy();
  });
});

describe("PromotionLayer", () => {
  it("lays the new insignia on for the captain and goes after six seconds", () => {
    vi.useFakeTimers();
    useProgression.setState({ banners: [celebrationOf({ subjectId: "person", kind: "person", level: 16, previousLevel: 15, title: "ensign", unlocked: ["suit_command_coat"] })] });
    render(<PromotionLayer />);
    expect(screen.getByText("Promotion")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Ensign" })).toBeTruthy();
    expect(screen.getByText("Command Coat")).toBeTruthy();
    act(() => { vi.advanceTimersByTime(CEREMONY_MS); });
    expect(useProgression.getState().banners).toHaveLength(0);
  });

  it("says level up between two ranks, and Escape dismisses", () => {
    useProgression.setState({ banners: [celebrationOf({ subjectId: "pet:gigi", kind: "pet", level: 4, previousLevel: 3, title: "crewman", unlocked: [] })] });
    render(<PromotionLayer />);
    expect(screen.getByText("Level up")).toBeTruthy();
    expect(screen.getByText("Companion · Gigi")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(useProgression.getState().banners).toHaveLength(0);
  });

  it("tells an android's promotion quietly in the corner", () => {
    vi.useFakeTimers();
    useProgression.setState({ toasts: [celebrationOf({ subjectId: "agent:scout", kind: "agent", level: 3, previousLevel: 2, title: "crewman", unlocked: [] })] });
    render(<PromotionLayer />);
    expect(screen.getByText("Scout was promoted to Crewman")).toBeTruthy();
    act(() => { vi.advanceTimersByTime(TOAST_MS); });
    expect(useProgression.getState().toasts).toHaveLength(0);
  });
});
