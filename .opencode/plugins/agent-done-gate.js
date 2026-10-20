// Agent done gate for OpenCode: an agent stops only when its work has landed.
//
// When a session goes idle, ask scripts/agent_done_gate.py whether the
// session's branch work has landed (PR merged, CI green on main, local main
// fast-forwarded). If it has not, send the gate's next step back into the
// session as a new prompt. Any error lets the session rest (fail open).
// Each decision is logged to ~/.agent-done-gate/opencode.log.
// See docs/agent-done-gate.md.

import { appendFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const LOG_DIR = join(homedir(), ".agent-done-gate");
const running = new Set();

function log(line) {
  try {
    mkdirSync(LOG_DIR, { recursive: true });
    appendFileSync(join(LOG_DIR, "opencode.log"), `${new Date().toISOString()} ${line}\n`);
  } catch {
    // logging is best effort
  }
}

function pythonCandidates() {
  return process.platform === "win32" ? ["python", "py"] : ["python3", "python"];
}

export const AgentDoneGate = async ({ client, $, directory, worktree }) => {
  const root = worktree || directory;
  const gate = `${root}/scripts/agent_done_gate.py`;

  async function verdictFor(sessionID) {
    for (const python of pythonCandidates()) {
      const result = await $`${python} ${gate} --json --wait 480 --session ${sessionID} --cwd ${directory}`
        .nothrow()
        .quiet();
      const text = result.stdout.toString().trim();
      if (!text) continue;
      try {
        return JSON.parse(text);
      } catch {
        return null;
      }
    }
    return null;
  }

  return {
    event: async ({ event }) => {
      if (event?.type !== "session.idle") return;
      const sessionID = event.properties?.sessionID;
      if (!sessionID || running.has(sessionID)) return;
      running.add(sessionID);
      try {
        // Sub-agent sessions report to their parent; only the root session is gated.
        const info = await client.session.get({ path: { id: sessionID } }).catch(() => null);
        if (info?.data?.parentID) return;
        const verdict = await verdictFor(sessionID);
        log(`${sessionID} ${directory}: ${verdict ? verdict.verdict : "no answer"}`);
        if (!verdict || verdict.may_stop !== false) return;
        // Do not await the reply: the session goes idle again when it is done,
        // and that idle must be checked, so release the session first.
        running.delete(sessionID);
        client.session
          .prompt({
            path: { id: sessionID },
            body: { parts: [{ type: "text", text: verdict.message }] },
          })
          .then(() => log(`${sessionID}: the session answered the next step`))
          .catch((error) => log(`${sessionID}: could not send the next step (${error})`));
        log(`${sessionID}: sent the next step back into the session`);
      } catch (error) {
        log(`${sessionID}: gate skipped (${error})`); // fail open
      } finally {
        running.delete(sessionID);
      }
    },
  };
};
