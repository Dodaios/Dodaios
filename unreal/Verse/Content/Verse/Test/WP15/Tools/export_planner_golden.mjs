// Export golden tables from today's TypeScript crew planner (life/planner.ts) so
// the Unreal port can be checked against it (parity.md C-07, C-09, C-10).
//
//   node unreal/Verse/Content/Verse/Test/WP15/Tools/export_planner_golden.mjs <frontend node_modules>
//
// It bundles planner.ts, crew.ts and loadDeck.ts with esbuild (from the given
// node_modules), replaces the ranks barrel with dutyStatus.ts (the planner needs
// nothing else from it) and writes Golden/planner_golden.json.
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../../../../../..");
const frontend = join(repo, "dodaios/ui/web/frontend");
const verse = join(frontend, "src/components/society/verse");
const modules = process.argv[2] ?? join(frontend, "node_modules");
const esbuild = createRequire(join(modules, "noop.js"))("esbuild");

const entry = `
export { idleVenueOf, intentOf, placeOnDeck, socketKey } from "${verse.replace(/\\/g, "/")}/life/planner.ts";
export { hash32, byServiceOrder } from "${verse.replace(/\\/g, "/")}/life/crew.ts";
export { deckFromManifest } from "${verse.replace(/\\/g, "/")}/content/loadDeck.ts";
`;
const ranksStub = {
  name: "ranks-stub",
  setup(build) {
    build.onResolve({ filter: /\/ranks$/ }, () => ({ path: join(verse, "ranks/dutyStatus.ts") }));
  },
};
const out = join(mkdtempSync(join(tmpdir(), "wp15-golden-")), "planner.mjs");
await esbuild.build({
  stdin: { contents: entry, resolveDir: verse, loader: "ts" },
  bundle: true, format: "esm", platform: "node", outfile: out, plugins: [ranksStub], logLevel: "error",
});
const P = await import(pathToFileURL(out).href);

// C-07: 1,000 seeded (id, t) pairs.
const idle = [];
for (let i = 0; i < 1000; i++) {
  const id = `ag_${(P.hash32(`id:${i}`) % 100000).toString(36)}`;
  const t = 1_790_000_000_000 + (P.hash32(`t:${i}`) % 86_400_000) * 13;
  const v = P.idleVenueOf(id, t);
  idle.push({ id, t, venue: v.venue, deck: v.deck, activity: v.activity });
}

// C-09 / C-10: placements of a 12-officer + 4-technician roster on each agent deck.
const statuses = ["working", "waiting", "idle", "paused", "error", "working", "idle", "idle", "working", "waiting", "idle", "working"];
const crew = statuses.map((status, i) => ({
  id: `ag_${String(i).padStart(2, "0")}`, name: `Officer ${i}`, role: "officer", status,
  createdMs: 1_790_000_000_000 + i * 60_000, lead: i === 3,
}));
["working", "waiting", "error", "idle"].forEach((status, i) => crew.push({
  id: `ws_1:T${i + 1}`, name: `T${i + 1}`, role: "technician", status, createdMs: 1_790_000_100_000 + i * 1000, lead: false,
}));
const nowMs = 1_790_000_500_000;
const rounds = new Map([["ag_06", "speaker"], ["ag_07", "listener"]]);
const plans = [];
for (const deckId of ["bridge", "ops", "engineering"]) {
  const manifest = JSON.parse(readFileSync(join(frontend, `public/verse/decks/${deckId}/manifest.json`), "utf8"));
  const deck = P.deckFromManifest(manifest, "", deckId, deckId);
  const first = P.placeOnDeck({ deck, crew, rounds, nowMs, previous: new Map() });
  const previous = new Map([...first.placements].map(([id, p]) => [id, P.socketKey(p.socket)]));
  // Remove one idle officer (ag_02): nobody else may change console (C-09).
  const second = P.placeOnDeck({ deck, crew: crew.filter((m) => m.id !== "ag_02"), rounds, nowMs, previous, homes: first.homes });
  const dump = (plan) => ({
    placements: Object.fromEntries([...plan.placements].map(([id, p]) => [id, { socket: P.socketKey(p.socket), venue: p.venue, activity: p.activity, face: p.faceCommander }])),
    homes: Object.fromEntries(plan.homes),
  });
  plans.push({ deck: deckId, first: dump(first), second: dump(second) });
}

const golden = {
  source: "dodaios/ui/web/frontend/src/components/society/verse/life/planner.ts",
  generator: "export_planner_golden.mjs",
  hash32: ["", "a", "ag_7f1:phase", "ws_91:T1:pace", "Mara:42"].map((text) => ({ text, hash: P.hash32(text) })),
  idle_venue: idle,
  roster: crew, now_ms: nowMs, rounds: Object.fromEntries(rounds),
  plans,
};
const target = join(here, "../Golden/planner_golden.json");
writeFileSync(target, JSON.stringify(golden, null, 1) + "\n");
console.log(`wrote ${target}: ${idle.length} idle rows, ${plans.length} deck plans`);
