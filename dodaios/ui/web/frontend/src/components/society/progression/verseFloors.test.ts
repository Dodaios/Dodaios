/**
 * The ship's decks are listed in three places: the server's `VERSE_DECKS`
 * (which decks a `deck_discovered` report may name), the client's
 * `METERED_DECKS` (which decks it reports) and the ship's `DECKS` (which decks
 * exist). A deck missing from one of them is either never paid or refused by
 * the server, so they are held together here.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { DECKS } from "../starship/plan/types";
import { reportWorldAction } from "./progressionApi";
import { METERED_DECKS } from "./useProgressionSync";

const SRC = join(__dirname, "..", "..", "..");

/** `VERSE_DECKS` as the backend declares it. */
function serverDecks(): string[] {
  const py = readFileSync(join(SRC, "..", "..", "..", "..", "progression", "service.py"), "utf8");
  const block = /^VERSE_DECKS\s*=\s*frozenset\(\{([^}]*)\}\)/m.exec(py);
  if (!block) throw new Error("VERSE_DECKS is no longer a frozenset literal in dodaios/progression/service.py");
  return [...block[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

describe("the ship's decks", () => {
  it("are the same on the server, in the reports and on the ship", () => {
    const server = serverDecks().sort();
    expect(server).toEqual(["bridge", "engineering", "holodeck", "honors", "ops"]);
    expect([...METERED_DECKS].sort()).toEqual(server);
    expect([...DECKS].sort()).toEqual(server);
    expect(new Set(DECKS).size).toBe(DECKS.length);
  });

  it("do not include what is not a deck (the stage may pass anything)", () => {
    for (const notADeck of ["agents", "coding", "arcade", "hall", ""]) expect(METERED_DECKS.has(notADeck)).toBe(false);
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
    await reportWorldAction("deck_discovered", "honors");
    expect(server.requests).toEqual([{ url: "/api/progression/actions", body: { action: "deck_discovered", ref: "honors" } }]);
    expect(server.warned).toEqual([]);
  });

  it("sends the retro games' arcade names as holodeck rounds", async () => {
    const server = serverAnswering(200);
    await reportWorldAction("arcade_round");
    await reportWorldAction("arcade_record");
    expect(server.requests.map((r) => (r.body as { action: string }).action)).toEqual(["holodeck_round", "holodeck_record"]);
  });

  it("logs a report the server refuses instead of dropping it, and does not throw", async () => {
    const server = serverAnswering(422);
    await expect(reportWorldAction("warp_jump", "andromeda")).resolves.toBeUndefined();
    expect(server.warned).toHaveLength(1);
    expect(server.warned[0]).toEqual(["Level action refused", "warp_jump", "andromeda", 422]);
  });

  it("stays quiet about an unreachable backend, and does not throw", async () => {
    const server = serverAnswering(new TypeError("Failed to fetch"));
    await expect(reportWorldAction("daily_visit")).resolves.toBeUndefined();
    expect(server.warned).toEqual([]);
    expect(server.debugged).toHaveLength(1);
  });
});
