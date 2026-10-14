import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import type { IdeProject } from "@/lib/agenticIdeApi";
import { TeamThreadDraft } from "./TeamThreadDraft";

vi.mock("@/i18n", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/i18n")>()),
  useT: () => (key: string) => key,
  fill: (template: string, vars: Record<string, unknown>) => `${template} ${JSON.stringify(vars)}`,
}));

// Plain stand-ins for the pickers, so a test can pick an option by its words.
vi.mock("@/components/ui/select", () => ({
  BrandedSelect: ({ options, onValueChange, testId, value, disabled }: {
    options: { value: string; label: string }[]; onValueChange: (value: string) => void; testId: string; value: string; disabled?: boolean;
  }) => <div data-testid={testId} data-value={value} data-disabled={disabled ? "true" : "false"}>
    {options.map((option) => <button key={option.value} type="button" onClick={() => onValueChange(option.value)}>{option.label}</button>)}
  </div>,
}));
vi.mock("@/components/ui/combobox", () => ({
  Combobox: ({ groups, onChange, testId, value, fallbackLabel }: {
    groups: { id: string; label?: string; options: { value: string; label: string; hint?: string }[] }[];
    onChange: (value: string) => void; testId: string; value: string; fallbackLabel?: string;
  }) => <div data-testid={testId} data-value={value} data-label={fallbackLabel}>
    {groups.map((group) => <div key={group.id} data-testid={`${testId}-group-${group.id}`}>
      {group.options.map((option) => <button key={option.value} type="button" onClick={() => onChange(option.value)}>
        {option.label}{option.hint ? ` (${option.hint})` : ""}
      </button>)}
    </div>)}
  </div>,
}));

const project: IdeProject = { id: "p1", name: "shop", path: "/work/shop" } as IdeProject;

const SEATS = {
  seats: [
    {
      provider: "claude-api", label: "Claude", family: "claude", runner: "claude-cli", agent: "claude", model: "", ready: true, local: false,
      models: ["claude-opus-5-5", "claude-sonnet-5-5"],
      model_options: [
        { id: "claude-opus-5-5", label: "Claude Opus 5.5", efforts: [] },
        { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5", efforts: ["low", "medium"] },
      ],
      efforts: ["low", "medium", "high"],
    },
    {
      provider: "openai-codex", label: "Codex", family: "openai", runner: "codex-cli", agent: "codex", model: "", ready: true, local: false,
      models: [], model_options: [], efforts: [],
    },
    {
      provider: "gemini", label: "Gemini", family: "gemini", runner: "api", agent: "", model: "", ready: true, local: false,
      models: [], model_options: [], efforts: [],
    },
    {
      provider: "grok-build", label: "Grok", family: "xai", runner: "grok-cli", agent: "grok-build", model: "", ready: false, local: false,
      models: [], model_options: [], efforts: [],
    },
  ],
  default: [{ provider: "claude-api", model: "" }, { provider: "openai-codex", model: "" }],
  min_members: 2,
  max_members: 8,
  max_turns: { 2: 40, 3: 40, 4: 40, 5: 50, 6: 60, 7: 70, 8: 80 },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount() {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body as string) : undefined });
    if (url.endsWith("/seats")) return { ok: true, json: async () => SEATS };
    return { ok: true, json: async () => ({ team_id: "t9", members: [], entries: [] }) };
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><TeamThreadDraft project={project} /></QueryClientProvider>);
  return calls;
}

const pick = (testId: string, words: string) => fireEvent.click(within(screen.getByTestId(testId)).getByText(words, { exact: false }));
const posted = (calls: ReturnType<typeof mount>) => calls.find((call) => call.method === "POST")?.body;

it("lets the person set each member's seat, model and effort", async () => {
  const calls = mount();
  await screen.findByTestId("team-draft-member-1");

  // Every row says what it is set to; the model starts on the seat's default.
  expect(screen.getByTestId("team-draft-select-0").dataset.value).toBe("claude-api");
  expect(screen.getByTestId("team-draft-model-0").dataset.value).toBe("");
  // A seat without a model list keeps its default and offers no effort.
  expect(screen.getByTestId("team-draft-model-1").dataset.disabled).toBe("true");
  expect(screen.queryByTestId("team-draft-effort-1")).toBeNull();
  // Coding agents and key providers are listed apart; a seat that is not ready is not offered.
  expect(screen.getByTestId("team-draft-select-0-group-agents").textContent).toBe("ClaudeCodex");
  expect(screen.getByTestId("team-draft-select-0-group-providers").textContent).toBe("Gemini");

  pick("team-draft-model-0", "Claude Opus 5.5");
  pick("team-draft-effort-0", "high");
  // The second member becomes a provider reached with a key.
  pick("team-draft-select-1", "Gemini");
  expect(screen.getByTestId("team-draft-select-1").dataset.value).toBe("gemini");

  fireEvent.change(screen.getByTestId("team-draft-task"), { target: { value: "Add a retry" } });
  fireEvent.click(screen.getByTestId("team-draft-start"));
  await waitFor(() => expect(posted(calls)).toEqual({
    task: "Add a retry",
    cwd: "/work/shop",
    seats: [
      { provider: "claude-api", model: "claude-opus-5-5", effort: "high" },
      { provider: "gemini", model: "" },
    ],
  }));
});

it("asks which seat joins, and the same seat may join twice on another model", async () => {
  const calls = mount();
  await screen.findByTestId("team-draft-member-1");

  // Nothing joins until the person picks it.
  expect(screen.queryByTestId("team-draft-member-2")).toBeNull();
  expect(screen.getByTestId("team-draft-add").dataset.label).toBe("team_threads.draft.add");
  // The picker says how often a seat already sits in the team.
  expect(within(screen.getByTestId("team-draft-add")).getByText(/Claude \(team_threads\.draft\.in_team \{"count":1\}\)/)).toBeTruthy();
  pick("team-draft-add", "Claude");
  expect(screen.getByTestId("team-draft-select-2").dataset.value).toBe("claude-api");
  pick("team-draft-model-2", "Claude Sonnet 5.5");
  // The new model's own levels apply.
  expect(within(screen.getByTestId("team-draft-effort-2")).queryByText("high")).toBeNull();
  pick("team-draft-effort-2", "medium");
  pick("team-draft-model-0", "Claude Opus 5.5");

  fireEvent.change(screen.getByTestId("team-draft-task"), { target: { value: "Add a retry" } });
  fireEvent.click(screen.getByTestId("team-draft-start"));
  await waitFor(() => expect(posted(calls)).toEqual({
    task: "Add a retry",
    cwd: "/work/shop",
    seats: [
      { provider: "claude-api", model: "claude-opus-5-5" },
      { provider: "openai-codex", model: "" },
      { provider: "claude-api", model: "claude-sonnet-5-5", effort: "medium" },
    ],
  }));
});

it("drops an effort the newly picked model does not offer", async () => {
  mount();
  await screen.findByTestId("team-draft-member-1");

  pick("team-draft-effort-0", "high");
  expect(screen.getByTestId("team-draft-effort-0").dataset.value).toBe("high");
  pick("team-draft-model-0", "Claude Sonnet 5.5");
  expect(screen.getByTestId("team-draft-effort-0").dataset.value).toBe("");
});

it("grows into a swarm of up to eight members and says what that costs", async () => {
  mount();
  await screen.findByTestId("team-draft-member-1");
  expect(screen.getByText(/team_threads\.draft\.bounds \{"turns":40\}/)).toBeTruthy();
  expect(screen.queryByTestId("team-draft-swarm")).toBeNull();

  for (let count = 3; count <= 8; count += 1) pick("team-draft-add", count % 2 ? "Codex" : "Gemini");
  expect(screen.getByTestId("team-draft-member-7")).toBeTruthy();
  expect(screen.getByTestId("team-draft-count").textContent).toContain('{"count":8,"max":8}');
  // Full: no picker, and the bound the server uses for eight.
  expect(screen.queryByTestId("team-draft-add")).toBeNull();
  expect(screen.getByTestId("team-draft-full")).toBeTruthy();
  expect(screen.getByTestId("team-draft-swarm")).toBeTruthy();
  expect(screen.getByText(/team_threads\.draft\.bounds \{"turns":80\}/)).toBeTruthy();

  // Planner and builder: the first two by position, six reviewers.
  fireEvent.click(screen.getByTestId("team-draft-mode-planner_builder"));
  expect([0, 1, 2, 7].map((index) => screen.getByTestId(`team-draft-role-${index}`).dataset.value))
    .toEqual(["planner", "builder", "reviewer", "reviewer"]);

  // A member leaves; the team can grow again.
  fireEvent.click(screen.getByTestId("team-draft-remove-7"));
  expect(screen.queryByTestId("team-draft-member-7")).toBeNull();
  expect(screen.getByTestId("team-draft-add")).toBeTruthy();
});
