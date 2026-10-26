import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { AgentRuntimesResponse } from "@/lib/agentRuntimesApi";
import type { ProviderOption } from "@/store/agentChat";
import { CreateAgentDialogHost } from "./CreateAgentDialog";
import { isCreateCancelled, useCreateAgentDialog } from "./createAgentStore";
import type { Starter, StartersResponse } from "./startersApi";

const { STRINGS } = vi.hoisted(() => ({
  STRINGS: {
    "agent_create.preview.instructions_words": "{words} words",
    "agent_create.preview.instructions_rules": "{rules} rules · {words} words",
    "agent_create.preview.tools_value": "{picked} of {total}",
  } as Record<string, string>,
}));
vi.mock("@/i18n", () => ({
  useT: () => (key: string) => STRINGS[key] ?? key,
  translate: (key: string) => key,
  fill: (template: string, vars: Record<string, string | number>) =>
    template.replace(/\{(\w+)\}/g, (match, key: string) => (key in vars ? String(vars[key]) : match)),
}));
vi.mock("../companion/CompanionEditor", () => ({
  CompanionEditor: ({ value }: { value: { shape: string } }) => <div data-testid="companion-editor">{value.shape}</div>,
}));
const { createAgent, seed, spawn, menu } = vi.hoisted(() => ({
  createAgent: vi.fn(),
  seed: vi.fn(),
  spawn: vi.fn(),
  menu: { options: [] as unknown[], live: {} as Record<string, unknown[]> },
}));
vi.mock("../data", async () => {
  class AgentNameTaken extends Error {}
  class RuntimeProviderUnsupported extends Error {}
  const requestError = (body: { detail?: { reason?: string; detail?: string } | string } | null, fallback: string) => {
    const detail = body?.detail;
    if (typeof detail === "string") return new Error(detail);
    if (detail?.reason === "runtime_provider_unsupported") return new RuntimeProviderUnsupported(detail.detail ?? fallback);
    return new Error(detail?.detail ?? fallback);
  };
  return {
    AgentNameTaken, RuntimeProviderUnsupported, requestError, useCreateSocietyAgent: () => createAgent,
    rowToAgent: (row: { agent_id: string; name: string; session_id?: string }) => ({
      agentId: row.agent_id, name: row.name, chatSessionId: row.session_id ?? null,
    }),
  };
});
vi.mock("./firstMessage", () => ({ seedFirstMessage: seed }));
vi.mock("../world/spawnStore", () => ({ announceSpawn: spawn }));
vi.mock("../chat/useModelMenuData", () => ({
  useModelMenuData: () => ({
    options: menu.options, providers: [], live: menu.live,
    loading: false, refreshing: false, failed: false, refresh: () => Promise.resolve(),
  }),
}));
const READY: AgentRuntimesResponse = {
  runtimes: [
    { runtime: "hermes", label: "Hermes", installed: true, version: "0.21.0", minimum_version: "0.20.6",
      ready: true, problem: "", problem_kind: "", install_hint: "", job: null },
  ],
  supported_providers: ["openai"],
};
vi.mock("@/lib/agentRuntimesApi", () => ({
  fetchAgentRuntimes: () => Promise.resolve(READY),
  ensureAgentRuntime: vi.fn(),
}));

function provider(over: Partial<ProviderOption>): ProviderOption {
  return {
    id: "openai", label: "OpenAI", family: "openai", runner: "brain", models_source: "live",
    curated_models: [{ id: "gpt-5.2", label: "GPT-5.2" }, { id: "gpt-5.5", label: "GPT-5.5" }],
    default_model: "", keyless: false, native_resume: false, effort_levels: [], default_effort: "",
    permission_modes: [], default_permission_mode: "", cli_installed: null, connected: true, active: false,
    ...over,
  };
}

const SUMMARY = { instructions_words: 42, instructions_rules: 3, skills: null, routines: 1, tools: 3, asks_before: 1, limited_tools: false };
const STARTERS: Starter[] = [
  {
    id: "code-reviewer", area: "coding", icon: "git-pull-request", name: "Code Reviewer", title: "Reviews",
    outcome: "Reads a branch before you merge.", instructions: "You review.\n\n- a\n- b\n- c",
    first_message: "Review my branch.", routine: null,
    tools: [{ id: "cli:gh", label: "GitHub CLI", available: true, connected: true }],
    summary: { ...SUMMARY, routines: 0, tools: 1, asks_before: 2 },
  },
  {
    id: "daily-briefing", area: "personal", icon: "sunrise", name: "Daily Briefing", title: "Briefs",
    outcome: "Starts your day with one note.", instructions: "You brief me.",
    first_message: "Give me a briefing for today.",
    routine: { title: "Morning briefing", when: "weekday_morning", cron: "0 8 * * 1-5" },
    tools: [
      { id: "plugin:google_calendar", label: "Calendar", available: true, connected: true },
      { id: "plugin:gmail", label: "Gmail", available: true, connected: false },
      { id: "core:search-web", label: "Web search", available: false, connected: false },
    ],
    summary: { ...SUMMARY, instructions_rules: 0, instructions_words: 3 },
  },
];
const GALLERY: StartersResponse = { areas: ["coding", "personal"], starters: STARTERS, total: 2 };

const fetchMock = vi.fn();

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

function route(url: string, init?: RequestInit) {
  if (url === "/api/society/starters") return json(GALLERY);
  if (url === "/api/society/starters/install") {
    const body = JSON.parse(String(init?.body));
    return json({
      agent: { agent_id: "agent-9", name: body.name || "Imported", session_id: "society:agent-9" },
      created: true, renamed_from: null,
      first_message: body.starter_id ? "Give me a briefing for today." : "",
      routine: body.with_routine ? { id: "task-1", title: "[agent:x] Morning briefing" } : null,
      routine_error: null,
    });
  }
  if (url === "/api/society/starters/preview") {
    const body = JSON.parse(String(init?.body));
    const template = body.template as Record<string, unknown>;
    if (!template.instructions) return json({ ok: false, errors: ["the instructions are empty"], template: null, summary: null, tools: [] });
    return json({
      ok: true, errors: [],
      template: { name: template.name, title: "Keeps notes", instructions: template.instructions, require_approval: [] },
      summary: { ...SUMMARY, routines: 0, tools: 1, asks_before: 0, instructions_rules: 0, instructions_words: 3 },
      tools: [{ id: "core:search-web", label: "Web search", available: true, connected: true }],
    });
  }
  return json({}, 404);
}

function mount() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CreateAgentDialogHost />
    </QueryClientProvider>,
  );
}

function installCalls() {
  return fetchMock.mock.calls.filter(([url]) => url === "/api/society/starters/install")
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)));
}

beforeEach(() => {
  menu.options = [provider({})];
  menu.live = {};
  fetchMock.mockImplementation(route);
  seed.mockResolvedValue(true);
  vi.stubGlobal("fetch", fetchMock);
  // The routine switch measures itself; the test DOM has no ResizeObserver.
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  act(() => useCreateAgentDialog.getState().cancel());
});

describe("CreateAgentDialog: starters", () => {
  test("opens on the first starter and filters the gallery by area and search", async () => {
    mount();
    act(() => { useCreateAgentDialog.getState().request({ mode: "starter" }).catch(() => undefined); });
    expect(await screen.findByTestId("starter-code-reviewer")).toBeTruthy();
    expect(screen.getByTestId("starter-daily-briefing")).toBeTruthy();
    // The preview is never empty: the first starter is open.
    await waitFor(() => expect((screen.getByTestId("template-preview-name") as HTMLInputElement).value).toBe("Code Reviewer"));
    expect(screen.getByTestId("preview-count-instructions").textContent).toContain("3 rules · 42 words");
    expect(screen.getByTestId("starter-area-all").textContent).toContain("2");

    fireEvent.click(screen.getByTestId("starter-area-personal"));
    expect(screen.queryByTestId("starter-code-reviewer")).toBeNull();
    expect(screen.getByTestId("starter-daily-briefing")).toBeTruthy();

    fireEvent.click(screen.getByTestId("starter-area-all"));
    fireEvent.change(screen.getByTestId("starter-search"), { target: { value: "branch merge" } });
    expect(screen.getByTestId("starter-code-reviewer")).toBeTruthy();
    expect(screen.queryByTestId("starter-daily-briefing")).toBeNull();
    expect(screen.getByTestId("starter-area-personal").textContent).toContain("0");

    fireEvent.change(screen.getByTestId("starter-search"), { target: { value: "nothing like this" } });
    expect(screen.getByTestId("starter-empty")).toBeTruthy();
  });

  test("the preview counts what the starter brings and follows the picks", async () => {
    mount();
    act(() => { useCreateAgentDialog.getState().request({ mode: "starter" }).catch(() => undefined); });
    fireEvent.click(await screen.findByTestId("starter-daily-briefing"));
    await waitFor(() => expect((screen.getByTestId("template-preview-name") as HTMLInputElement).value).toBe("Daily Briefing"));
    expect(screen.getByTestId("preview-count-instructions").textContent).toContain("3 words");
    expect(screen.getByTestId("preview-count-skills").textContent).toContain("agent_create.preview.skills_all");
    // Only the connected tool starts ticked.
    expect(screen.getByTestId("preview-count-tools").textContent).toContain("1 of 3");
    expect((screen.getByTestId("preview-tool-plugin:google_calendar") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("preview-tool-plugin:gmail") as HTMLInputElement).checked).toBe(false);
    expect((screen.getByTestId("preview-tool-core:search-web") as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByTestId("preview-tool-plugin:gmail"));
    expect(screen.getByTestId("preview-count-tools").textContent).toContain("2 of 3");
    // The routine is opt-in: off, and counted only once ticked.
    expect(within(screen.getByTestId("preview-count-routines")).getByText("0")).toBeTruthy();
    fireEvent.click(screen.getByTestId("preview-routine-toggle"));
    expect(within(screen.getByTestId("preview-count-routines")).getByText("1")).toBeTruthy();
    expect(screen.getByTestId("preview-first-message").textContent).toBe("Give me a briefing for today.");
    expect(screen.getByTestId("preview-asks-before").textContent).toContain("agent_create.preview.asks_before_one");
  });

  test("creates from a starter on the dialog's seat and seeds the first message", async () => {
    mount();
    let pending!: Promise<{ agentId: string }>;
    act(() => { pending = useCreateAgentDialog.getState().request({ mode: "starter" }) as Promise<{ agentId: string }>; });
    fireEvent.click(await screen.findByTestId("starter-daily-briefing"));
    await waitFor(() => expect((screen.getByTestId("template-preview-name") as HTMLInputElement).value).toBe("Daily Briefing"));
    fireEvent.change(screen.getByTestId("template-preview-name"), { target: { value: "Morning Desk" } });
    fireEvent.click(screen.getByTestId("preview-routine-toggle"));
    await screen.findByTestId("create-agent-seat-summary");
    await waitFor(() => expect((screen.getByTestId("create-agent-submit") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("create-agent-submit"));
    await expect(pending).resolves.toMatchObject({ agentId: "agent-9", name: "Morning Desk" });
    const [body] = installCalls();
    expect(body).toMatchObject({
      starter_id: "daily-briefing",
      name: "Morning Desk",
      tools: ["plugin:google_calendar"],
      with_routine: true,
      seat: { provider: "openai", model: "gpt-5.5", execution_environment: "local" },
    });
    expect(typeof body.timezone).toBe("string");
    expect(body.seat.companion.shape).toBeTruthy();
    expect(body.seat.runtime).toBeUndefined();
    expect(spawn).toHaveBeenCalledWith("agent-9");
    expect(seed).toHaveBeenCalledWith(expect.objectContaining({ agentId: "agent-9" }), "Give me a briefing for today.");
    expect(createAgent).not.toHaveBeenCalled();
  });

  test("a starter on Hermes sends the runtime", async () => {
    mount();
    act(() => { useCreateAgentDialog.getState().request({ mode: "starter" }).catch(() => undefined); });
    await screen.findByTestId("starter-code-reviewer");
    fireEvent.click(await screen.findByTestId("create-agent-seat-summary").then((el) => within(el).getAllByRole("button")[0]));
    fireEvent.click(await screen.findByRole("radio", { name: "society.runtime.hermes" }));
    await waitFor(() => expect((screen.getByTestId("create-agent-submit") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("create-agent-submit"));
    await waitFor(() => expect(installCalls()).toHaveLength(1));
    expect(installCalls()[0]).toMatchObject({ starter_id: "code-reviewer", seat: { runtime: "hermes", provider: "openai" } });
    expect(installCalls()[0].with_routine).toBeUndefined();
  });

  test("a routine that could not be set up is said before the chat opens", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => url === "/api/society/starters/install"
      ? json({ agent: { agent_id: "agent-3", name: "Daily Briefing" }, created: true, renamed_from: null,
        first_message: "", routine: null, routine_error: "timezone_required" })
      : route(url, init));
    mount();
    let pending!: Promise<unknown>;
    act(() => { pending = useCreateAgentDialog.getState().request({ mode: "starter" }); });
    fireEvent.click(await screen.findByTestId("starter-daily-briefing"));
    fireEvent.click(screen.getByTestId("preview-routine-toggle"));
    await waitFor(() => expect((screen.getByTestId("create-agent-submit") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("create-agent-submit"));
    expect(await screen.findByTestId("create-agent-routine-error")).toBeTruthy();
    expect(useCreateAgentDialog.getState().open).toBe(true);
    fireEvent.click(screen.getByTestId("create-agent-submit"));
    await expect(pending).resolves.toMatchObject({ agentId: "agent-3" });
  });
  test("a runtime that cannot drive the provider is said in the person's language", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => url === "/api/society/starters/install"
      ? json({ detail: { reason: "runtime_provider_unsupported", detail: "Hermes cannot run this provider" } }, 422)
      : route(url, init));
    mount();
    act(() => { useCreateAgentDialog.getState().request({ mode: "starter" }).catch(() => undefined); });
    await screen.findByTestId("starter-code-reviewer");
    await waitFor(() => expect((screen.getByTestId("create-agent-submit") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("create-agent-submit"));
    expect(await screen.findByText("society.runtime.provider_unsupported")).toBeTruthy();
    expect(useCreateAgentDialog.getState().open).toBe(true);
  });

  test("the three ways in are tabs the arrow keys move through", async () => {
    mount();
    act(() => { useCreateAgentDialog.getState().request().catch(() => undefined); });
    const quick = await screen.findByTestId("create-agent-mode-quick");
    expect(quick.getAttribute("tabindex")).toBe("0");
    expect(screen.getByTestId("create-agent-mode-starter").getAttribute("tabindex")).toBe("-1");
    fireEvent.keyDown(quick, { key: "ArrowRight" });
    expect(screen.getByTestId("create-agent-mode-starter").getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(screen.getByTestId("create-agent-mode-starter"));
    fireEvent.keyDown(screen.getByTestId("create-agent-mode-starter"), { key: "End" });
    expect(screen.getByTestId("create-agent-mode-import").getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(screen.getByTestId("create-agent-mode-import"), { key: "ArrowRight" });
    expect(screen.getByTestId("create-agent-mode-quick").getAttribute("aria-selected")).toBe("true");
  });
});

describe("CreateAgentDialog: import", () => {
  test("a template handed in opens on its preview, and nothing exists before Create", async () => {
    mount();
    let pending!: Promise<unknown>;
    act(() => {
      pending = useCreateAgentDialog.getState().request({
        template: { schema: 1, name: "Note Keeper", instructions: "Keep my notes.", focus: ["core:search-web"] },
      });
    });
    await waitFor(() => expect((screen.getByTestId("template-preview-name") as HTMLInputElement).value).toBe("Note Keeper"));
    expect(screen.getByTestId("create-agent-mode-import").getAttribute("aria-selected")).toBe("true");
    expect(installCalls()).toHaveLength(0);
    fireEvent.click(screen.getByTestId("preview-tool-core:search-web"));
    await waitFor(() => expect((screen.getByTestId("create-agent-submit") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("create-agent-submit"));
    await expect(pending).resolves.toMatchObject({ agentId: "agent-9" });
    expect(installCalls()[0]).toMatchObject({
      template: { name: "Note Keeper" }, name: "Note Keeper", tools: [], seat: { provider: "openai" },
    });
    expect(seed).toHaveBeenCalledWith(expect.anything(), "");
  });

  test("pasted text that is not a usable template cannot be created", async () => {
    mount();
    act(() => { useCreateAgentDialog.getState().request({ mode: "import" }).catch(() => undefined); });
    const field = await screen.findByTestId("import-text");
    fireEvent.change(field, { target: { value: "{not json" } });
    expect(await screen.findByText("agent_create.import.invalid_json")).toBeTruthy();
    expect((screen.getByTestId("create-agent-submit") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(field, { target: { value: JSON.stringify({ kind: "agent", agent: { schema: 1, name: "X" } }) } });
    expect(await screen.findByTestId("import-errors")).toBeTruthy();
    expect((screen.getByTestId("create-agent-submit") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("create-agent-empty-preview")).toBeTruthy();
  });

  test("an edit holds Create until the new text is checked", async () => {
    mount();
    act(() => {
      useCreateAgentDialog.getState().request({
        template: { schema: 1, name: "Note Keeper", instructions: "Keep my notes." },
      }).catch(() => undefined);
    });
    await waitFor(() => expect((screen.getByTestId("template-preview-name") as HTMLInputElement).value).toBe("Note Keeper"));
    await waitFor(() => expect((screen.getByTestId("create-agent-submit") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.change(screen.getByTestId("import-text"), {
      target: { value: JSON.stringify({ schema: 1, name: "Other Keeper", instructions: "Keep other notes." }) },
    });
    // The old preview stays on screen, but it is no longer what Create would install.
    expect((screen.getByTestId("create-agent-submit") as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect((screen.getByTestId("template-preview-name") as HTMLInputElement).value).toBe("Other Keeper"));
    await waitFor(() => expect((screen.getByTestId("create-agent-submit") as HTMLButtonElement).disabled).toBe(false));
  });
});

describe("CreateAgentDialog: blank", () => {
  test("creates with a name only, and the job line becomes the mission", async () => {
    createAgent.mockResolvedValue({ agentId: "agent-1", name: "Scout" });
    mount();
    let pending!: Promise<unknown>;
    act(() => { pending = useCreateAgentDialog.getState().request(); });
    fireEvent.change(await screen.findByTestId("create-agent-name"), { target: { value: "Scout" } });
    fireEvent.change(screen.getByTestId("create-agent-job"), { target: { value: "Watches my repositories" } });
    await screen.findByTestId("create-agent-provider");
    fireEvent.click(screen.getByTestId("create-agent-submit"));
    await expect(pending).resolves.toMatchObject({ agentId: "agent-1" });
    expect(createAgent.mock.calls[0][0]).toMatchObject({ name: "Scout", mission: "Watches my repositories", runtime: "jarvis" });
    // The blank path never touches the gallery.
    expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith("/api/society/starters"))).toBe(false);
  });

  test("the runtime note explains what is fixed for life", async () => {
    mount();
    act(() => { useCreateAgentDialog.getState().request().catch(() => undefined); });
    expect((await screen.findByTestId("create-agent-runtime-note")).textContent).toBe("agent_create.runtime_note.jarvis");
    fireEvent.click(await screen.findByRole("radio", { name: "society.runtime.hermes" }));
    expect(screen.getByTestId("create-agent-runtime-note").textContent).toBe("agent_create.runtime_note.hermes");
  });

  test("closing still rejects with CreateAgentCancelled", async () => {
    mount();
    let pending!: Promise<unknown>;
    act(() => { pending = useCreateAgentDialog.getState().request({ mode: "starter" }); });
    await screen.findByTestId("starter-code-reviewer");
    fireEvent.click(screen.getByRole("button", { name: "society.create_agent.cancel" }));
    await expect(pending).rejects.toSatisfy(isCreateCancelled);
    expect(installCalls()).toHaveLength(0);
  });
});
