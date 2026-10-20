/**
 * The capital ship's decks are listed in two places: the server's
 * `VERSE_DECKS` (which decks a `deck_discovered` or `inspection` report may
 * name) and the Verse's `DECK_IDS` (which decks exist; the client reports
 * exactly those). A deck missing from one of them is either never paid or
 * refused by the server, so they are held together here.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { DECK_IDS } from "../verse/decks";
import { reportWorldAction } from "./progressionApi";
import { METERED_DECKS } from "./useProgressionSync";

const SRC = join(__dirname, "..", "..", "..");

/** `VERSE_DECKS` as the backend's rulebook declares it. */
function serverDecks(): string[] {
  const py = readFileSync(join(SRC, "..", "..", "..", "..", "progression", "rules.py"), "utf8");
  const block = /^VERSE_DECKS: Final\[tuple\[str, \.\.\.\]\] = \(([^)]*)\)/m.exec(py);
  if (!block) throw new Error("VERSE_DECKS is no longer a tuple literal in dodaios/progression/rules.py");
  return [...block[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

describe("the ship's decks", () => {
  it("are the same on the server, in the reports and on the ship, in order", () => {
    const server = serverDecks();
    expect(server).toEqual(["bridge", "ops", "engineering", "hangar"]);
    expect([...DECK_IDS]).toEqual(server);
    expect([...METERED_DECKS]).toEqual(server);
  });

  it("do not include what is not a deck (the stage may pass anything)", () => {
    for (const notADeck of ["holodeck", "honors", "agents", "hall", ""]) expect(METERED_DECKS.has(notADeck)).toBe(false);
  });
});

describe("reporting a world action", () => {
  const realFetch = globalThis.fetch, realWarn = console.warn, realDebug = console.debug;
  afterEach(() => {
    globalThis.fetch = realFetch;
    console.warn = realWarn;
    console.debug = realDebug;
  });

  /** Answer every request with `status`, and collect what is logged. */
  function serverAnswering(status: number | Error) {
    const requests: { url: string; body: unknown }[] = [], warned: unknown[][] = [], debugged: unknown[][] = [];
    globalThis.fetch = (async (url: RequestInfo | URL, init?: RequestInit) => {
      requests.push({ url: String(url), body: JSON.parse(String(init?.body)) });
      if (status instanceof Error) throw status;
      return new Response("{}", { status });
    }) as typeof fetch;
    console.warn = (...args: unknown[]) => { warned.push(args); };
    console.debug = (...args: unknown[]) => { debugged.push(args); };
    return { requests, warned, debugged };
  }

  it("says nothing when the server takes it", async () => {
    const server = serverAnswering(200);
    await reportWorldAction("deck_discovered", "hangar");
    expect(server.requests).toEqual([{ url: "/api/progression/actions", body: { action: "deck_discovered", ref: "hangar" } }]);
    expect(server.warned).toEqual([]);
  });

  it("sends the retro games' arcade names and the old holodeck names as simulator rounds", async () => {
    const server = serverAnswering(200);
    await reportWorldAction("arcade_round");
    await reportWorldAction("arcade_record");
    await reportWorldAction("holodeck_round");
    await reportWorldAction("holodeck_record");
    expect(server.requests.map((r) => (r.body as { action: string }).action)).toEqual([
      "simulator_round", "simulator_record", "simulator_round", "simulator_record",
    ]);
  });

  it("logs a report the server refuses instead of dropping it, and does not throw", async () => {
    const server = serverAnswering(422);
    await expect(reportWorldAction("inspection", "holodeck")).resolves.toBeUndefined();
    expect(server.warned).toHaveLength(1);
    expect(server.warned[0]).toEqual(["Level action refused", "inspection", "holodeck", 422]);
  });

  it("stays quiet about an unreachable backend, and does not throw", async () => {
    const server = serverAnswering(new TypeError("Failed to fetch"));
    await expect(reportWorldAction("daily_visit")).resolves.toBeUndefined();
    expect(server.warned).toEqual([]);
    expect(server.debugged).toHaveLength(1);
  });
});
