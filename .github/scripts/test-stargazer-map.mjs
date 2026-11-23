import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const yaml = readFileSync(new URL("../workflows/stargazer-map.yml", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const script = yaml.split("          script: |\n")[1].replace(/^            /gm, "");
const execute = new (Object.getPrototypeOf(async function () {}).constructor)(
  "require", "github", "context", "core", script,
);

const snapshot = {
  repo: "PersonalJarvis/PersonalJarvis", count: 1, forks: 0, placed: 1, stated: 1,
  generatedAt: "2026-09-01T00:00:00Z", login: "must-not-publish",
  clusters: [{ lat: 52, lon: 13, label: "Berlin", country: "Germany", count: 1,
    profile: "must-not-publish" }],
};

async function run({ exists = false, fail = false } = {}) {
  const writes = [];
  const github = { rest: {
    git: {
      async getRef({ ref }) {
        if (ref === "heads/stargazer-map" && !exists) throw { status: fail ? 403 : 404 };
        return { data: { object: { sha: "main-sha" } } };
      },
      async createRef(args) { writes.push({ kind: "branch", ...args }); },
    },
    repos: {
      async getContent() {
        if (!exists) throw { status: 404 };
        return { data: { sha: "old-file-sha" } };
      },
      async createOrUpdateFileContents(args) { writes.push({ kind: "file", ...args }); },
    },
  } };
  await execute(() => ({ readFileSync: () => JSON.stringify(snapshot) }), github,
    { repo: { owner: "PersonalJarvis", repo: "PersonalJarvis" } }, { info() {} });
  return writes;
}

test("bootstrap creates the data branch and publishes only aggregate fields", async () => {
  const writes = await run();
  assert.equal(writes[0].ref, "refs/heads/stargazer-map");
  assert.equal(writes[0].sha, "main-sha");
  const data = JSON.parse(Buffer.from(writes[1].content, "base64"));
  assert.equal(data.login, undefined);
  assert.equal(data.clusters[0].profile, undefined);
  assert.equal(data.placed, 1);
  assert.equal(writes[1].branch, "stargazer-map");
});

test("existing branch is updated using the previous file SHA without touching main", async () => {
  const writes = await run({ exists: true });
  assert.equal(writes.length, 1);
  assert.equal(writes[0].sha, "old-file-sha");
  assert.equal(writes[0].branch, "stargazer-map");
});

test("permission failures abort publication", async () => {
  await assert.rejects(run({ fail: true }), (error) => error.status === 403);
});

test("star and reconciliation triggers run the collector from main without a personal token", () => {
  assert.match(yaml, /watch:\s+types: \[started\]/);
  assert.match(yaml, /cron: "23 \* \* \* \*"/);
  // The collector comes from this repository; only main-branch triggers may run it.
  assert.doesNotMatch(yaml, /^\s+ref: /m);
  assert.doesNotMatch(yaml, /^\s+pull_request/m);
  assert.match(yaml, /GITHUB_TOKEN: \$\{\{ github.token \}\}/);
  assert.doesNotMatch(yaml, /STARGAZERS_TOKEN|pull_request_target/);
});

test("the geocoder runs from this repository, never from a foreign checkout", () => {
  // The website repository is private; a checkout of it fails with
  // "Repository not found" and the public feed stops moving.
  assert.equal([...yaml.matchAll(/^\s+repository: /gm)].length, 0);
  assert.match(yaml, /run: node \.github\/stargazer-map\/fetch-stargazers\.mjs --repo Dodaios\/Dodaios/);
  assert.match(yaml, /readFileSync\('\.github\/stargazer-map\/stargazers\.json'/);
});
