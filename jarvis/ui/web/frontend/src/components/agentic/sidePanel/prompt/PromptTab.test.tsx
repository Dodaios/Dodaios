import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkspacePaneRow } from "@/lib/agenticIdeApi";
import { useIdeSkillsStore } from "@/store/ideSkills";
import { useWorkspacePanesStore } from "@/store/workspacePanes";
import { PromptTab } from "./PromptTab";

function pane(over: Partial<WorkspacePaneRow>): WorkspacePaneRow {
  return {
    workspace_id: "w1", workspace_name: "App", folder: "/repo", workspace_active: true,
    key: "t1", history_id: "h1", name: "T1", agent: "claude", display_name: "Claude Code",
    accepts_prompts: true, status: "live", exit_code: null, activity: "idle", activity_since: 0,
    worked: false, started_at: null, last_output_at: null, last_prompt: "", last_prompt_at: null,
    recap: "", has_resume: false, readable: false, account: null, account_label: null, archived: false,
    ...over,
  } as WorkspacePaneRow;
}

const PANES = [pane({}), pane({ key: "t2", history_id: "h2", name: "T2", agent: "codex", display_name: "Codex" })];

/** An in-memory backend: the improver, the pane list and the pane prompt route. */
function fakeBackend(options: { submitted?: boolean | null; improveStatus?: number } = {}) {
  const calls: { url: string; method: string; body: Record<string, unknown> }[] = [];
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchFake = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    calls.push({ url, method, body });
    if (url.endsWith("/prompt-improver") && method === "GET") return json({ default_instruction: "Improve this prompt.", max_prompt_chars: 6000, max_instruction_chars: 1000 });
    if (url.endsWith("/prompt-improver") && method === "POST") {
      if (options.improveStatus) return json({ detail: "No model can write prompts right now." }, options.improveStatus);
      return json({ improved: "Make the login form accessible.", source: "tool_model:x", writer: "writer-x", folder: "/repo" });
    }
    if (url.includes("/api/agentic-ide/panes")) return json({ panes: PANES, active_id: "w1" });
    if (url.includes("/terminals/") && url.includes("/prompt")) {
      return json({ terminal: "T2", sent: body.prompt, composed_by: "raw", files: [], submitted: options.submitted === undefined ? true : options.submitted });
    }
    // The model catalog: an empty one leaves the picker on "Automatic".
    return json({ providers: [] });
  };
  return { calls, fetchFake };
}

beforeEach(() => {
  localStorage.clear();
  useWorkspacePanesStore.setState({ panes: PANES });
  useIdeSkillsStore.setState({ target: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PromptTab", () => {
  it("improves the typed prompt with the selected pane's repository as context", async () => {
    const backend = fakeBackend();
    vi.stubGlobal("fetch", backend.fetchFake);
    useIdeSkillsStore.setState({ target: { workspaceId: "w1", pane: "t2" } });
    render(<PromptTab />);

    expect(screen.queryByTestId("ide-prompt-result")).toBeNull();
    fireEvent.change(screen.getByTestId("ide-prompt-input"), { target: { value: "login form barrierefrei" } });
    fireEvent.click(screen.getByTestId("ide-prompt-improve"));

    const output = (await screen.findByTestId("ide-prompt-output")) as HTMLTextAreaElement;
    expect(output.value).toBe("Make the login form accessible.");
    const call = backend.calls.find((entry) => entry.method === "POST" && entry.url.endsWith("/prompt-improver"))!;
    expect(call.body).toEqual({ prompt: "login form barrierefrei", provider: "", model: "", instruction: "", workspace: "w1", pane: "t2" });
    // Improving is a preview: nothing was typed into a pane.
    expect(backend.calls.some((entry) => entry.url.includes("/terminals/"))).toBe(false);
  });

  it("sends the edited result, as written, to the chosen terminal", async () => {
    const backend = fakeBackend();
    vi.stubGlobal("fetch", backend.fetchFake);
    useIdeSkillsStore.setState({ target: { workspaceId: "w1", pane: "t2" } });
    render(<PromptTab />);

    fireEvent.change(screen.getByTestId("ide-prompt-input"), { target: { value: "login" } });
    fireEvent.click(screen.getByTestId("ide-prompt-improve"));
    fireEvent.change(await screen.findByTestId("ide-prompt-output"), { target: { value: "Make the login form accessible. Keep the layout." } });
    fireEvent.click(screen.getByTestId("ide-prompt-send"));

    await screen.findByTestId("ide-prompt-notice");
    const sent = backend.calls.find((entry) => entry.url.includes("/terminals/"))!;
    expect(sent.url).toContain("/terminals/t2/prompt?workspace=w1");
    // Never composed a second time: the pane gets the text the user approved.
    expect(sent.body).toMatchObject({ prompt: "Make the login form accessible. Keep the layout.", compose: false });
    expect(screen.getByTestId("ide-prompt-notice").textContent).toContain("T2");
  });

  it("says so when the terminal did not take the prompt", async () => {
    const backend = fakeBackend({ submitted: false });
    vi.stubGlobal("fetch", backend.fetchFake);
    render(<PromptTab />);

    fireEvent.change(screen.getByTestId("ide-prompt-input"), { target: { value: "login" } });
    fireEvent.click(screen.getByTestId("ide-prompt-improve"));
    await screen.findByTestId("ide-prompt-output");
    fireEvent.click(screen.getByTestId("ide-prompt-send"));

    const notice = await screen.findByTestId("ide-prompt-notice");
    expect(notice.textContent).toContain("did not take the prompt");
  });

  it("shows the server's reason when no model can improve the prompt", async () => {
    const backend = fakeBackend({ improveStatus: 409 });
    vi.stubGlobal("fetch", backend.fetchFake);
    render(<PromptTab />);

    fireEvent.change(screen.getByTestId("ide-prompt-input"), { target: { value: "login" } });
    fireEvent.click(screen.getByTestId("ide-prompt-improve"));

    const error = await screen.findByTestId("ide-prompt-error");
    expect(error.textContent).toBe("No model can write prompts right now.");
    expect(screen.queryByTestId("ide-prompt-result")).toBeNull();
  });

  it("passes the user's own instruction and keeps the draft across a remount", async () => {
    const backend = fakeBackend();
    vi.stubGlobal("fetch", backend.fetchFake);
    const first = render(<PromptTab />);
    fireEvent.change(screen.getByTestId("ide-prompt-input"), { target: { value: "login" } });
    fireEvent.change(screen.getByTestId("ide-prompt-instruction"), { target: { value: "Translate it to English." } });
    first.unmount();

    render(<PromptTab />);
    expect((screen.getByTestId("ide-prompt-input") as HTMLTextAreaElement).value).toBe("login");
    fireEvent.click(screen.getByTestId("ide-prompt-improve"));

    await waitFor(() => expect(backend.calls.some((entry) => entry.method === "POST" && entry.url.endsWith("/prompt-improver"))).toBe(true));
    const call = backend.calls.find((entry) => entry.method === "POST" && entry.url.endsWith("/prompt-improver"))!;
    expect(call.body.instruction).toBe("Translate it to English.");
  });
});
