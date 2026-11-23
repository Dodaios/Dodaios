#!/usr/bin/env node
/**
 * Where the people who starred Personal Jarvis are, as points on a globe.
 *
 * ## Why this runs at build time and not in the browser
 *
 * The star COUNT is public and anonymous: one unauthenticated request, which
 * the page makes for itself so the number is live to the minute.
 *
 * Where those people ARE is a different question. The REST API gives you a
 * list of logins and nothing else, so a location costs one more request per
 * person — 60 an hour is the anonymous ceiling, and a page that spends it on
 * the first visitor leaves the second one staring at an error. GraphQL hands
 * back login and location together, 100 people to a request, but it refuses to
 * answer without a token, and a token in a static page is a token anyone can
 * read out of the bundle.
 *
 * So the map is drawn here, where a token is safe, and the result is committed.
 * A scheduled workflow re-runs it and the site rebuilds; see
 * `.github/workflows/stargazer-map.yml`.
 *
 * ## What ships
 *
 * Counts per place. No logins, no profile URLs, no dates, nothing that names a
 * person. "Three people in Berlin" is the whole claim the section makes, and
 * it is the whole thing this file writes. People star a repository; they do
 * not agree to be pinned to a map by name.
 *
 * Copied from the website repository (pinned commit 70125a6) when that
 * repository became private: this workflow's token cannot read it anymore.
 *
 * Usage:  node .github/stargazer-map/fetch-stargazers.mjs [--repo owner/name]
 * Auth:   $GITHUB_TOKEN, $GH_TOKEN, or a signed-in `gh` CLI
 * Writes: .github/stargazer-map/stargazers.json (git-ignored)
 */

import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { geocode } from "./geocode.mjs";

// Written beside this script; the workflow publishes an allowlisted copy of
// it to the stargazer-map branch. The file itself is never committed.
const OUT = join(fileURLToPath(new URL(".", import.meta.url)), "stargazers.json");

const DEFAULT_REPO = "PersonalJarvis/PersonalJarvis";
const PAGE = 100;

function repoArg() {
  const i = process.argv.indexOf("--repo");
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : DEFAULT_REPO;
}

function token() {
  // STARGAZERS_TOKEN first. In CI it is the only credential that can reach
  // ANOTHER repository's GraphQL, so where it exists it is the one to use;
  // see `collect` for what happens where it does not.
  const fromEnv =
    process.env.STARGAZERS_TOKEN || process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
  if (fromEnv) return fromEnv;
  try {
    // Locally there is usually a signed-in gh; in CI there is always a
    // GITHUB_TOKEN. Between them nobody has to paste a secret anywhere.
    return execFileSync("gh", ["auth", "token"], { encoding: "utf8" }).trim();
  } catch {
    throw new Error(
      "no GitHub token: set GITHUB_TOKEN, or sign in with `gh auth login`",
    );
  }
}

const QUERY = `
query($owner:String!, $name:String!, $after:String) {
  repository(owner:$owner, name:$name) {
    stargazerCount
    forkCount
    stargazers(first:${PAGE}, after:$after, orderBy:{field:STARRED_AT, direction:ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { location }
    }
  }
}`;

async function graphql(auth, variables) {
  const res = await fetch("https://api.github.com/graphql", {
    method: "POST",
    headers: {
      authorization: `bearer ${auth}`,
      "content-type": "application/json",
      "user-agent": "personal-jarvis-website-build",
    },
    body: JSON.stringify({ query: QUERY, variables }),
  });
  if (!res.ok) throw new Error(`GitHub GraphQL: HTTP ${res.status}`);
  const body = await res.json();
  if (body.errors) throw new Error(`GitHub GraphQL: ${body.errors[0].message}`);
  return body.data.repository;
}

async function collectByGraphql(auth, owner, name) {
  const locations = [];
  let after = null;
  let count = 0;
  let forks = 0;
  let requests = 0;

  for (;;) {
    const data = await graphql(auth, { owner, name, after });
    requests += 1;
    count = data.stargazerCount;
    forks = data.forkCount;
    for (const node of data.stargazers.nodes) {
      if (node.location) locations.push(node.location);
    }
    if (!data.stargazers.pageInfo.hasNextPage) break;
    after = data.stargazers.pageInfo.endCursor;
  }

  return { count, forks, locations, requests, via: "GraphQL" };
}

/**
 * Past this many stargazers, REST is no longer a polite way to ask.
 *
 * One request per person against a ceiling of a thousand an hour: at the
 * current few dozen it is nothing, at a few hundred it is most of the budget
 * and several minutes of runtime. Beyond it the script stops and names the fix
 * rather than spending the budget and writing half a globe.
 */
const REST_CEILING = 600;

async function rest(auth, path) {
  const res = await fetch(`https://api.github.com${path}`, {
    headers: {
      authorization: `bearer ${auth}`,
      accept: "application/vnd.github+json",
      "user-agent": "personal-jarvis-website-build",
    },
  });
  if (!res.ok) {
    // The body, not just the status. A 403 from this API is three different
    // problems wearing one number — no permission, primary rate limit,
    // secondary rate limit — and the status alone cannot tell them apart.
    const detail = (await res.text()).slice(0, 300).replace(/\s+/g, " ");
    throw new Error(`GitHub REST ${path}: HTTP ${res.status} — ${detail}`);
  }
  return res.json();
}

/**
 * The same two facts over REST, for a token GraphQL will not answer.
 *
 * REST hands back logins and nothing else, so a location costs one more
 * request per person — the very cost the GraphQL query exists to avoid. It is
 * the fallback and not the default for that reason alone; the answer it
 * produces is identical.
 */
async function collectByRest(auth, owner, name) {
  const repo = await rest(auth, `/repos/${owner}/${name}`);
  let requests = 1;

  if (repo.stargazers_count > REST_CEILING) {
    throw new Error(
      `${repo.stargazers_count} stargazers is past what REST can fetch politely ` +
        `(${REST_CEILING}). Set STARGAZERS_TOKEN to a token with public read ` +
        "access and the GraphQL path takes over.",
    );
  }

  const logins = [];
  for (let page = 1; ; page += 1) {
    const batch = await rest(
      auth,
      `/repos/${owner}/${name}/stargazers?per_page=${PAGE}&page=${page}`,
    );
    requests += 1;
    for (const user of batch) if (user?.login) logins.push(user.login);
    if (batch.length < PAGE) break;
  }

  // One at a time, deliberately. A burst of parallel requests is what trips
  // GitHub's secondary rate limit, and a job that runs every six hours has all
  // the time it needs.
  const locations = [];
  for (const login of logins) {
    const user = await rest(auth, `/users/${login}`);
    requests += 1;
    if (user.location) locations.push(user.location);
  }

  return { count: repo.stargazers_count, forks: repo.forks_count, locations, requests, via: "REST" };
}

/**
 * The one rejection that means "this token is the wrong kind", not "this
 * request was wrong".
 *
 * Only it may fall through to another route. A network failure, an expired
 * token or a repository that does not exist has to keep failing loudly:
 * quietly spending several hundred requests to work around a typo is worse
 * than stopping.
 */
function closedToToken(err) {
  return /not accessible by integration/i.test(String(err?.message));
}

/**
 * GraphQL where the token may use it, REST where it may not, and a plain
 * answer where neither works.
 *
 * The globe is built in the WEBSITE's repository while the stars belong to the
 * APP's, and that one fact governs everything here. A workflow's built-in
 * GITHUB_TOKEN is scoped to the repository it runs in, so against another
 * repository it is not a weaker credential — it is the wrong one, and BOTH
 * routes turn it away with "Resource not accessible by integration". Measured
 * on this workflow's first real runs, not guessed.
 *
 * There is no anonymous way around it either. A repository's star COUNT is
 * open to anyone, which is why the page can keep its own number live without a
 * server — but the LIST of who starred it answers an unauthenticated caller
 * with 401 "Requires authentication". That asymmetry is the whole reason this
 * script exists and the reason it cannot be moved into the browser.
 *
 * So: a credential is required, and the only question is which route it opens.
 *
 *   1. GRAPHQL — a hundred people per request. A signed-in `gh` locally, or
 *      STARGAZERS_TOKEN in CI.
 *   2. REST — one request per person, for a token that GraphQL refuses.
 *      Verified to produce byte-identical output.
 *
 * Anything else fails loudly and names the fix, because a globe that silently
 * stops being refreshed looks exactly like a globe nobody is starring.
 */
async function collect(auth, owner, name) {
  try {
    return await collectByGraphql(auth, owner, name);
  } catch (err) {
    if (!closedToToken(err)) throw err;
    console.log("stargazers: GraphQL is closed to this token — trying REST");
  }

  try {
    return await collectByRest(auth, owner, name);
  } catch (err) {
    if (!closedToToken(err)) throw err;
    throw new Error(
      "this token may not read another repository's stargazers. A workflow's " +
        "built-in GITHUB_TOKEN never can. Set STARGAZERS_TOKEN to a personal " +
        "access token with public repository read access.",
    );
  }
}

async function main() {
  const repo = repoArg();
  const [owner, name] = repo.split("/");
  if (!owner || !name) throw new Error(`--repo wants owner/name, got "${repo}"`);

  const { count, forks, locations, requests, via } = await collect(token(), owner, name);

  // One cluster per resolved place, so "SF", "San Francisco, CA" and
  // "san francisco" arrive as one marker of three rather than three markers
  // sitting on top of each other.
  const clusters = new Map();
  const rejected = [];

  for (const raw of locations) {
    const hit = geocode(raw);
    if (!hit) {
      rejected.push(raw);
      continue;
    }
    const key = `${hit.label}|${hit.country}`;
    const existing = clusters.get(key);
    if (existing) existing.count += 1;
    else clusters.set(key, { ...hit, count: 1 });
  }

  const list = [...clusters.values()]
    .map(({ lat, lon, label, country, count: n }) => ({
      lat,
      lon,
      label,
      country,
      count: n,
    }))
    // Biggest first, so the globe can draw the small ones on top of the large
    // ones rather than under them.
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));

  const previous = readPrevious();
  const out = {
    repo,
    count,
    forks,
    // Everyone whose location resolved, which is what the markers add up to.
    // Named plainly so the section can say "8 of 31" instead of implying the
    // globe shows all of them.
    placed: list.reduce((s, c) => s + c.count, 0),
    stated: locations.length,
    generatedAt: new Date().toISOString(),
    clusters: list,
  };

  writeFileSync(OUT, JSON.stringify(out, null, 2) + "\n", "utf8");

  const delta = previous ? count - previous.count : null;
  console.log(
    [
      `stargazers: ${count} stars${delta === null ? "" : delta === 0 ? " (unchanged)" : ` (${delta > 0 ? "+" : ""}${delta})`}, ${forks} forks`,
      `            ${locations.length} gave a location, ${out.placed} of those resolved, ${list.length} places`,
      `            ${requests} ${via} request${requests === 1 ? "" : "s"} -> .github/stargazer-map/stargazers.json`,
    ].join("\n"),
  );
  if (rejected.length) {
    console.log(`            unresolved: ${rejected.map((r) => JSON.stringify(r)).join(", ")}`);
  }
}

function readPrevious() {
  try {
    return JSON.parse(readFileSync(OUT, "utf8"));
  } catch {
    return null;
  }
}

await main();
