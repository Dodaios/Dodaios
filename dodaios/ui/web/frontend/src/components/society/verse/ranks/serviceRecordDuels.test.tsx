/**
 * The service record's duel section (WP21.5): it reads `/api/progression/duels`,
 * shows sets, won / lost, K/D, headshots, finishers and the best streak, lists
 * the latest sets, and says "no sets yet" when the backend has none or is gone.
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import { LEVEL_XP } from "../../progression/levelCatalog";
import { LOCAL_REWARDS } from "../../progression/progressionApi";
import { useProgression } from "../../progression/progressionStore";
import { ServiceRecord, parseDuelRecord } from "./ServiceRecord";

const DUELS = {
  duel_stats: {
    matches: 13, wins: 8, losses: 4, unfinished: 1, kills: 96, deaths: 81, kd: 1.19,
    headshots: 31, finishers: 4, melee_kills: 2, best_streak: 6, by_tier: {}, by_weapon: {},
  },
  duels: [
    { match_id: "m3", outcome: "won", tier_key: "hard", score: { player: 10, opponent: 7 }, xp: 60, recorded_ms: 3 },
    { match_id: "m2", outcome: "unfinished", tier_key: "adaptive", score: { player: 2, opponent: 3 }, xp: 0, recorded_ms: 2 },
    { match_id: "m1", outcome: "draw", tier_key: "hard", score: {}, xp: 0, recorded_ms: 1 },
  ],
};

function openRecord() {
  useProgression.setState({
    snapshot: {
      subjects: [], petId: "gigi", recent: [], latestSeq: 0, maxLevel: 50, levelXp: [...LEVEL_XP], rules: [],
      rewards: [...LOCAL_REWARDS], ranks: [], titles: { person: [], agent: [], pet: [] }, looks: {},
    },
    subjects: {}, banners: [], toasts: [], popups: [], record: "record", uniform: "auto",
  });
}

beforeAll(async () => {
  await loadLocaleChunk("ship");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("parseDuelRecord", () => {
  it("reads totals and sets, leaves unknown outcomes out and zeroes what is missing", () => {
    const record = parseDuelRecord(DUELS);
    expect(record.totals).toMatchObject({ matches: 13, wins: 8, losses: 4, kd: 1.19, headshots: 31, finishers: 4, bestStreak: 6 });
    expect(record.sets.map((s) => s.matchId)).toEqual(["m3", "m2"]);
    expect(parseDuelRecord(null).totals.matches).toBe(0);
    expect(parseDuelRecord({ duels: "x" }).sets).toEqual([]);
  });
});

describe("ServiceRecord duel section", () => {
  it("shows the duel numbers the backend sends", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(DUELS), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    openRecord();
    render(<ServiceRecord />);
    const dialog = screen.getByRole("dialog");
    await waitFor(() => expect(dialog.querySelector('[data-stat="sets"]')).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledWith("/api/progression/duels?limit=5");
    const stat = (id: string) => dialog.querySelector(`[data-stat="${id}"] .vr-num`)?.textContent;
    expect(stat("sets")).toBe("13");
    expect(stat("record")).toBe("8 / 4");
    expect(stat("kd")).toBe("1.19");
    expect(stat("headshots")).toBe("31");
    expect(stat("finishers")).toBe("4");
    expect(stat("best_streak")).toBe("6");
    const list = within(screen.getByRole("list", { name: "Recent sets" }));
    const rows = list.getAllByRole("listitem");
    expect(rows.map((r) => r.getAttribute("data-outcome"))).toEqual(["won", "unfinished"]);
    expect(rows[0].textContent).toContain("Won · Hard");
    expect(rows[0].textContent).toContain("10 : 7");
    expect(rows[0].textContent).toContain("+60");
    expect(rows[1].textContent).toContain("Unfinished · Adaptive");
  });

  it("reads again on focus, so a set that paid nothing still shows up", async () => {
    const fewer = { ...DUELS, duel_stats: { ...DUELS.duel_stats, matches: 12 } };
    let calls = 0;
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(calls++ === 0 ? fewer : DUELS), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    openRecord();
    render(<ServiceRecord />);
    const dialog = screen.getByRole("dialog");
    const sets = () => dialog.querySelector('[data-stat="sets"] .vr-num')?.textContent;
    await waitFor(() => expect(sets()).toBe("12"));
    window.dispatchEvent(new Event("focus"));
    await waitFor(() => expect(sets()).toBe("13"));
  });

  it("says no sets yet without a backend", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    openRecord();
    render(<ServiceRecord />);
    const section = screen.getByRole("dialog").querySelector('[data-section="duels"]');
    expect(section?.textContent).toContain("No duel sets yet");
  });
});
