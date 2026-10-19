// Agent done gate for OpenCode: an agent stops only when its work has landed.
//
// When a session goes idle, ask scripts/agent_done_gate.py whether the
// session's branch work has landed (PR merged, CI green on main, local main
// fast-forwarded). If it has not, send the gate's next step back into the
// session as a new prompt. Any error lets the session rest (fail open).
// See docs/agent-done-gate.md.

const running = new Set();

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
        if (!verdict || verdict.may_stop !== false) return;
        await client.session.prompt({
          path: { id: sessionID },
          body: { parts: [{ type: "text", text: verdict.message }] },
        });
      } catch {
        // fail open: a broken gate must never trap a session
      } finally {
        running.delete(sessionID);
      }
    },
  };
};
