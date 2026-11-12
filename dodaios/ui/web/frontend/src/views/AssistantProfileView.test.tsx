/**
 * Component tests for the assistant's profile section.
 *
 * What these pin: the page carries the assistant's name (never a file name),
 * its vibe leads the page, the character reads from SOUL.md without repeating
 * the vibe, explicit memories say so, a note can be forgotten only while the
 * learning loop runs, plural counts are right, and the files open in place —
 * SOUL.md and the instructions as editors that save to their own endpoints.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { STANDING_LIMITS, standingTask } from "@/lib/standingTasksApi.testkit";
import { useEventStore } from "@/store/events";
import { openStandingTasks, useStandingFocus } from "@/store/standingFocus";
import { AssistantProfileView } from "@/views/AssistantProfileView";
import type { SoulProfile } from "@/views/assistant/api";

function renderWithClient(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function profile(overrides: Partial<SoulProfile> = {}): SoulProfile {
  return {
    name: "Nova",
    named: true,
    product: "Personal Jarvis",
    wake_phrase: "Hey Nova",
    learning: true,
    files: [
      {
        id: "soul",
        filename: "SOUL.md",
        exists: true,
        editable: true,
        updated_ms: Date.now(),
        chars: 120,
        content: "# My own persona\n\n## Who I am\n\n- **Name:** Nova\n- **Vibe:** Dry and direct.\n",
        character: {
          who: [
            { label: "Role", text: "Personal voice assistant." },
            { label: "Vibe", text: "Dry and direct." },
          ],
          tone: [{ label: "", text: "No corporate-speak." }],
          limits: [{ label: "", text: "No made-up facts." }],
        },
        learned: [{ id: "s1", text: "Answers in short spoken sentences.", importance: 5, origin: "review", explicit: false }],
        name_in_file: "Nova",
      },
      {
        id: "instructions",
        filename: "Nova.md",
        exists: true,
        editable: true,
        updated_ms: Date.now(),
        chars: 21,
        content: "Call me Ruben, please.",
        template: "# How Nova should work with me\n",
      },
      {
        id: "memory",
        filename: "MEMORY.md",
        exists: true,
        editable: false,
        updated_ms: Date.now(),
        chars: 60,
        entries: [
          {
            id: "m1",
            text: "2026-10-02 (asked to remember): The sister is called Lena.",
            importance: 10,
            origin: "user",
            explicit: true,
          },
        ],
      },
      { id: "user", filename: "USER.md", exists: false, editable: false, updated_ms: null, chars: 0, entries: [] },
    ],
    activity: [
      {
        ts: "2026-10-02T10:00:10+0200",
        source: "remember tool",
        target: "memory",
        operation: "add",
        text: "2026-10-02 (asked to remember): The sister is called Lena.",
        evidence: "merk dir das",
      },
    ],
    ...overrides,
  };
}

type Handler = (init?: RequestInit) => { status?: number; body: unknown };

function installFetch(routes: Record<string, Handler>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const key = `${init?.method ?? "GET"} ${url}`;
    const handler = routes[key];
    if (!handler) throw new Error(`unexpected fetch ${key}`);
    const { status = 200, body } = handler(init);
    return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
  });
  (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AssistantProfileView", () => {
  it("is titled with the assistant's name and leads with its vibe", async () => {
    installFetch({ "GET /api/soul": () => ({ body: profile() }) });
    renderWithClient(<AssistantProfileView />);

    expect(await screen.findByTestId("assistant-intro")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Nova");
    expect(screen.getByText(/woken by “Hey Nova”/)).toBeTruthy();
    expect(screen.getByTestId("assistant-vibe").textContent).toBe("Dry and direct.");
    expect(screen.getByText("1 thing remembered")).toBeTruthy();
    expect(screen.getByTestId("assistant-learning").textContent).toBe("Learning");
  });

  it("shows the character without repeating the vibe", async () => {
    installFetch({ "GET /api/soul": () => ({ body: profile() }) });
    renderWithClient(<AssistantProfileView />);

    const character = await screen.findByTestId("assistant-character");
    expect(within(character).getByText("Personal voice assistant.")).toBeTruthy();
    expect(within(character).getByText("No corporate-speak.")).toBeTruthy();
    expect(within(character).queryByText("Dry and direct.")).toBeNull();
  });

  it("lists memories with who asked, and the ledger with the person's words", async () => {
    installFetch({ "GET /api/soul": () => ({ body: profile() }) });
    renderWithClient(<AssistantProfileView />);

    const memory = await screen.findByTestId("assistant-memory");
    expect(within(memory).getByText("The sister is called Lena.")).toBeTruthy();
    expect(within(memory).getByText(/You asked/)).toBeTruthy();
    fireEvent.click(within(memory).getByRole("button", { name: /About itself/ }));
    expect(within(memory).getByText("Answers in short spoken sentences.")).toBeTruthy();

    const recent = screen.getByTestId("assistant-recent");
    expect(within(recent).getByText("Added to memory")).toBeTruthy();
    expect(within(recent).getByText("You said: “merk dir das”")).toBeTruthy();
    expect(within(recent).queryByTestId("assistant-last-review")).toBeNull();
  });

  it("says where the last review ran and how each change was billed", async () => {
    const seat = { seat: "openai-codex/gpt-5.5", seat_label: "OpenAI Codex", billing: "subscription" };
    const base = profile();
    installFetch({
      "GET /api/soul": () => ({
        body: profile({
          activity: [{ ...base.activity[0], ...seat }],
          last_review: { ts: "2026-10-02T10:05:00+0200", source: "review: call ended", outcome: "answered", changes: 1, ...seat },
        }),
      }),
    });
    renderWithClient(<AssistantProfileView />);

    const last = await screen.findByTestId("assistant-last-review");
    expect(within(last).getByText("Last review ran on OpenAI Codex")).toBeTruthy();
    expect(within(last).getByText("Billed to your subscription")).toBeTruthy();
    expect(within(screen.getByTestId("assistant-recent")).getByText("Added to memory · via subscription")).toBeTruthy();
  });

  it("says when a review gave up, without claiming a bill", async () => {
    installFetch({
      "GET /api/soul": () => ({
        body: profile({
          last_review: {
            ts: "2026-10-02T10:05:00+0200",
            source: "review: call ended",
            outcome: "dropped",
            changes: 0,
            seat: "openai/gpt-5.5",
            seat_label: "OpenAI",
            billing: "metered",
          },
        }),
      }),
    });
    renderWithClient(<AssistantProfileView />);

    const last = await screen.findByTestId("assistant-last-review");
    expect(within(last).getByText(/gave up on OpenAI after several tries/)).toBeTruthy();
    // A review that gave up billed nothing, so no billing line.
    expect(within(last).queryByText("Billed per token to your API key")).toBeNull();
  });

  it("shows each file with its own first lines and the right count", async () => {
    installFetch({ "GET /api/soul": () => ({ body: profile() }) });
    renderWithClient(<AssistantProfileView />);

    const soul = await screen.findByTestId("assistant-file-soul");
    expect(within(soul).getByText("Name: Nova")).toBeTruthy();
    expect(within(soul).queryByText(/My own persona/)).toBeNull();
    expect(within(screen.getByTestId("assistant-file-instructions")).getByText("Call me Ruben, please.")).toBeTruthy();
    const memory = screen.getByTestId("assistant-file-memory");
    expect(within(memory).getByText(/^1 note ·/)).toBeTruthy();
    expect(within(memory).getByText("The sister is called Lena.")).toBeTruthy();
    expect(within(screen.getByTestId("assistant-file-user")).getByText("Not created yet")).toBeTruthy();
  });

  it("lets the person choose how much initiative it takes", async () => {
    const initiative = {
      level: "balanced" as const,
      levels: ["off", "balanced", "high"] as ("off" | "balanced" | "high")[],
      upcoming: [{ date: "2026-10-09", text: "The user is preparing a product launch for 2026-10-09." }],
    };
    const calls = installFetch({
      "GET /api/soul": () => ({ body: profile({ initiative }) }),
      "PUT /api/soul/initiative": () => ({
        body: profile({ initiative: { ...initiative, level: "off", upcoming: [] } }),
      }),
    });
    renderWithClient(<AssistantProfileView />);

    const section = await screen.findByTestId("assistant-initiative");
    const radios = within(section).getAllByRole("radio");
    expect(radios.map((r) => r.getAttribute("aria-checked"))).toEqual(["false", "true", "false"]);
    expect(within(section).getByText(/nothing is sent, bought, deleted or started without your yes/)).toBeTruthy();
    expect(within(screen.getByTestId("assistant-initiative-upcoming")).getByText(/product launch/)).toBeTruthy();

    fireEvent.click(screen.getByTestId("assistant-initiative-off"));
    await waitFor(() =>
      expect(screen.getByTestId("assistant-initiative-off").getAttribute("aria-checked")).toBe("true"),
    );
    const put = calls.find((c) => c.url === "/api/soul/initiative");
    expect(put?.init?.method).toBe("PUT");
    expect(JSON.parse(String(put?.init?.body))).toEqual({ level: "off" });
    // Off: nothing is pointed at, so no dated plans are listed.
    await waitFor(() => expect(screen.queryByTestId("assistant-initiative-upcoming")).toBeNull());
  });

  it("hides the initiative section for a backend without the setting", async () => {
    installFetch({ "GET /api/soul": () => ({ body: profile() }) });
    renderWithClient(<AssistantProfileView />);

    await screen.findByTestId("assistant-character");
    expect(screen.queryByTestId("assistant-initiative")).toBeNull();
  });

  it("forgets a note through the soul endpoint", async () => {
    const calls = installFetch({
      "GET /api/soul": () => ({ body: profile() }),
      "DELETE /api/soul/entries/memory/m1": () => ({
        body: profile({ files: profile().files.map((f) => (f.id === "memory" ? { ...f, entries: [] } : f)) }),
      }),
    });
    renderWithClient(<AssistantProfileView />);

    const memory = await screen.findByTestId("assistant-memory");
    fireEvent.click(within(memory).getByRole("button", { name: /Forget: The sister/ }));
    await waitFor(() => expect(within(memory).getByTestId("assistant-notes-empty-memory")).toBeTruthy());
    expect(calls.some((c) => c.url === "/api/soul/entries/memory/m1" && c.init?.method === "DELETE")).toBe(true);
  });

  it("cannot forget while the learning loop is off", async () => {
    installFetch({ "GET /api/soul": () => ({ body: profile({ learning: false }) }) });
    renderWithClient(<AssistantProfileView />);

    const memory = await screen.findByTestId("assistant-memory");
    const forget = within(memory).getByRole("button", { name: /Forget: The sister/ }) as HTMLButtonElement;
    expect(forget.disabled).toBe(true);
    expect(screen.getByTestId("assistant-learning").textContent).toBe("Not learning right now");
  });

  /**
   * The pages as a backend with a running memory vault returns them: what a
   * review learned sits in the vault, and USER.md starts with the profile.
   * Regression (2026-11-12): the pages read the old notebook files alone and
   * said "0 notes" while the vault held what the assistant had learned.
   */
  function withVault(): SoulProfile {
    const base = profile();
    const now = Date.now();
    return {
      ...base,
      files: base.files.map((f) =>
        f.id === "user"
          ? {
              ...f,
              exists: true,
              store: "vault" as const,
              updated_ms: now,
              entries: [
                { id: "profile:identity.name", text: "Ruben", importance: 0, origin: "profile", explicit: false, store: "profile" as const, field: "name", at_ms: null },
                { id: "profile:work_style.focus_mode", text: "deep-work", importance: 0, origin: "profile", explicit: false, store: "profile" as const, field: "focus_mode", at_ms: null },
                { id: "profile:communication.emoji_ok", text: "false", importance: 0, origin: "profile", explicit: false, store: "profile" as const, field: "emoji_ok", at_ms: null },
                { id: "mem_1", text: "The user builds Dodaios.", importance: 5, origin: "inferred", explicit: false, store: "vault" as const, at_ms: now },
              ],
            }
          : f,
      ),
    };
  }

  it("shows what the memory vault holds and counts it, with the profile's lines first", async () => {
    installFetch({ "GET /api/soul": () => ({ body: withVault() }) });
    renderWithClient(<AssistantProfileView />);

    // One note in MEMORY.md and one learned about the person; the profile's lines are the person's own.
    expect(await screen.findByText("2 things remembered")).toBeTruthy();
    const user = screen.getByTestId("assistant-file-user");
    expect(within(user).getByText(/^4 notes · today/)).toBeTruthy();
    expect(within(user).getByText("Name: Ruben")).toBeTruthy();
    expect(within(user).getByText("Focus: Deep work")).toBeTruthy();
    expect(within(user).getByText("Emojis: No")).toBeTruthy();

    const memory = screen.getByTestId("assistant-memory");
    fireEvent.click(within(memory).getByRole("button", { name: /About you/ }));
    expect(within(memory).getByText("The user builds Dodaios.")).toBeTruthy();
    // A vault memory says when it was learned.
    expect(within(memory).getByText("today")).toBeTruthy();
  });

  it("keeps a profile line read-only and forgets a vault memory by its id", async () => {
    const calls = installFetch({
      "GET /api/soul": () => ({ body: withVault() }),
      "DELETE /api/soul/entries/user/mem_1": () => ({ body: withVault() }),
    });
    renderWithClient(<AssistantProfileView />);

    fireEvent.click(await screen.findByTestId("assistant-file-user"));
    const page = await screen.findByTestId("assistant-page-user");
    const lines = within(page).getAllByTestId("assistant-note-profile");
    expect(lines).toHaveLength(3);
    expect(within(lines[0]).getByText("From your profile")).toBeTruthy();
    expect(within(page).getAllByRole("button", { name: /^Forget:/ })).toHaveLength(1);
    const note = within(page).getByTestId("assistant-notebook-note").textContent ?? "";
    expect(note).toContain("keeps them in its memory");
    expect(note).toContain("You change them under Profile.");

    fireEvent.click(within(page).getByRole("button", { name: /Forget: The user builds/ }));
    await waitFor(() =>
      expect(calls.some((c) => c.url === "/api/soul/entries/user/mem_1" && c.init?.method === "DELETE")).toBe(true),
    );
  });

  it("does not claim a missing model for a review that answered without naming its seat", async () => {
    installFetch({
      "GET /api/soul": () => ({
        body: profile({
          last_review: { ts: "2026-11-12T21:59:24+0100", source: "review: quiet conversation", outcome: "answered", changes: 1 },
        }),
      }),
    });
    renderWithClient(<AssistantProfileView />);

    const last = await screen.findByTestId("assistant-last-review");
    expect(within(last).getByText("Last review ran")).toBeTruthy();
    expect(within(last).queryByText(/found no model/)).toBeNull();
  });

  it("edits SOUL.md in place and saves it to /api/soul/file", async () => {
    const calls = installFetch({
      "GET /api/soul": () => ({ body: profile() }),
      "PUT /api/soul/file": () => ({ body: profile() }),
    });
    renderWithClient(<AssistantProfileView />);

    const character = await screen.findByTestId("assistant-character");
    fireEvent.click(within(character).getByRole("button", { name: "Edit" }));
    const editor = (await screen.findByTestId("assistant-file-editor")) as HTMLTextAreaElement;
    expect(editor.value).toContain("## Who I am");
    const save = screen.getByTestId("assistant-file-save") as HTMLButtonElement;
    expect(save.disabled).toBe(true);

    fireEvent.change(editor, { target: { value: `${editor.value}\n- **Humor:** dry` } });
    fireEvent.click(save);
    await waitFor(() => expect(calls.some((c) => c.url === "/api/soul/file")).toBe(true));
    const put = calls.find((c) => c.url === "/api/soul/file");
    expect(JSON.parse(String(put?.init?.body)).content).toContain("- **Humor:** dry");

    fireEvent.click(screen.getByTestId("assistant-back"));
    expect(await screen.findByTestId("assistant-intro")).toBeTruthy();
  });

  it("saves the instructions file to the agent-instructions endpoint", async () => {
    const calls = installFetch({
      "GET /api/soul": () => ({ body: profile() }),
      "PUT /api/settings/agent-instructions": () => ({ body: { ok: true } }),
    });
    renderWithClient(<AssistantProfileView />);

    fireEvent.click(await screen.findByTestId("assistant-file-instructions"));
    const editor = (await screen.findByTestId("assistant-file-editor")) as HTMLTextAreaElement;
    expect(editor.value).toBe("Call me Ruben, please.");
    fireEvent.change(editor, { target: { value: "Call me Ruben. Answer in German." } });
    fireEvent.click(screen.getByTestId("assistant-file-save"));
    await waitFor(() =>
      expect(calls.some((c) => c.url === "/api/settings/agent-instructions" && c.init?.method === "PUT")).toBe(true),
    );
  });

  describe("standing tasks", () => {
    const STANDING = "/api/agent-chat/lead/standing";
    const meta = standingTask("s-meta", { title: "Meta ads campaign", goal: "Keep cost per purchase under 20 EUR." });
    const standingRoutes = {
      [`GET ${STANDING}`]: () => ({
        body: { available: true, tasks: [meta], limits: STANDING_LIMITS, autonomy: ["watch", "prepare", "act"] },
      }),
      [`GET ${STANDING}/s-meta`]: () => ({ body: { task: meta, runs: [] } }),
    };
    const initiative = { level: "balanced" as const, levels: ["off" as const, "balanced" as const, "high" as const], upcoming: [] };

    it("sit right after Initiative and open in place, with a way back", async () => {
      installFetch({ "GET /api/soul": () => ({ body: profile({ initiative }) }), ...standingRoutes });
      renderWithClient(<AssistantProfileView />);

      const section = await screen.findByTestId("assistant-standing");
      expect(within(section).getByRole("heading", { level: 2 }).textContent).toBe("Standing tasks");
      const order = screen.getAllByRole("region").map((region) => region.getAttribute("data-testid"));
      expect(order.indexOf("assistant-standing")).toBe(order.indexOf("assistant-initiative") + 1);
      expect(order.indexOf("assistant-memory")).toBe(order.indexOf("assistant-standing") + 1);

      fireEvent.click(await within(section).findByTestId("assistant-standing-open-s-meta"));
      expect(await screen.findByTestId("assistant-standing-page")).toBeTruthy();
      expect(screen.getByRole("heading", { level: 2, name: "Meta ads campaign" })).toBeTruthy();
      // The page itself steps aside, like it does for a file.
      expect(screen.queryByTestId("assistant-intro")).toBeNull();

      fireEvent.click(screen.getByTestId("assistant-standing-back"));
      expect(await screen.findByTestId("assistant-intro")).toBeTruthy();
      expect(screen.getByTestId("assistant-standing")).toBeTruthy();
    });

    it("land on the task someone asked for from outside the page", async () => {
      installFetch({ "GET /api/soul": () => ({ body: profile() }), ...standingRoutes });
      openStandingTasks("s-meta");
      expect(useEventStore.getState().activeSection).toBe("agent-instructions");
      renderWithClient(<AssistantProfileView />);

      expect(await screen.findByTestId("assistant-standing-page")).toBeTruthy();
      expect(await screen.findByRole("heading", { level: 2, name: "Meta ads campaign" })).toBeTruthy();
      // The request is taken once: going back shows the page, not the task again.
      expect(useStandingFocus.getState().target).toBeNull();
      fireEvent.click(screen.getByTestId("assistant-standing-back"));
      expect(await screen.findByTestId("assistant-standing")).toBeTruthy();
      expect(screen.queryByTestId("assistant-standing-page")).toBeNull();
    });

    it("bring the list into view when it was asked for from outside", async () => {
      installFetch({ "GET /api/soul": () => ({ body: profile() }), ...standingRoutes });
      const scrolled = vi.fn();
      const original = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = scrolled;
      try {
        openStandingTasks();
        renderWithClient(<AssistantProfileView />);
        await screen.findByTestId("assistant-standing");
        await waitFor(() => expect(scrolled).toHaveBeenCalledTimes(1));
        expect(screen.queryByTestId("assistant-standing-page")).toBeNull();
        expect(useStandingFocus.getState().target).toBeNull();
      } finally {
        Element.prototype.scrollIntoView = original;
      }
    });
  });
});
