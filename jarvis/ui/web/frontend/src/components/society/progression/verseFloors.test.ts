/**
 * The Verse's floors are listed in three places: the server's `VERSE_FLOORS`
 * (which floors a `floor_discovered` report may name), the client's
 * `METERED_FLOORS` (which floors it reports) and the elevator's
 * `OFFICE_FLOORS` (which floors exist). A floor missing from one of them is
 * either never paid or refused by the server, so they are held together here.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { OFFICE_FLOORS } from "../office/officeStore";
import { reportWorldAction } from "./progressionApi";
import { METERED_FLOORS } from "./useProgressionSync";

const SRC = join(__dirname, "..", "..", "..");

/** `VERSE_FLOORS` as the backend declares it. */
function serverFloors(): string[] {
  const py = readFileSync(join(SRC, "..", "..", "..", "..", "progression", "service.py"), "utf8");
  const block = /^VERSE_FLOORS\s*=\s*frozenset\(\{([^}]*)\}\)/m.exec(py);
  if (!block) throw new Error("VERSE_FLOORS is no longer a frozenset literal in jarvis/progression/service.py");
  return [...block[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

describe("the Verse's floors", () => {
  it("are the same on the server, in the reports and in the elevator", () => {
    const server = serverFloors().sort();
    expect(server.length).toBeGreaterThan(0);
    expect([...METERED_FLOORS].sort()).toEqual(server);
    expect([...OFFICE_FLOORS].sort()).toEqual(server);
    // No floor is listed twice in the elevator.
    expect(new Set(OFFICE_FLOORS).size).toBe(OFFICE_FLOORS.length);
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
    await reportWorldAction("floor_discovered", "hall");
    expect(server.requests).toEqual([{ url: "/api/progression/actions", body: { action: "floor_discovered", ref: "hall" } }]);
    expect(server.warned).toEqual([]);
  });

  it("logs a report the server refuses instead of dropping it, and does not throw", async () => {
    const server = serverAnswering(400);
    await expect(reportWorldAction("floor_discovered", "attic")).resolves.toBeUndefined();
    expect(server.warned).toHaveLength(1);
    expect(server.warned[0]).toEqual(["Level action refused", "floor_discovered", "attic", 400]);
  });

  it("stays quiet about an unreachable backend, and does not throw", async () => {
    const server = serverAnswering(new TypeError("Failed to fetch"));
    await expect(reportWorldAction("daily_visit")).resolves.toBeUndefined();
    expect(server.warned).toEqual([]);
    expect(server.debugged).toHaveLength(1);
  });
});
