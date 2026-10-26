/**
 * Agent templates in the storefront: their own shelf and filter, a drawer that
 * shows the instructions and the safe defaults BEFORE the install button, an
 * install that lands on the team, and the import of an exported file.
 *
 * No jest-dom in this repo — assertions use toBeTruthy()/toBeNull().
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/views/ChatsView", () => ({
  ViewHeader: ({ title, right }: { title: string; right?: React.ReactNode }) => (
    <header>
      <h2>{title}</h2>
      {right}
    </header>
  ),
}));
vi.mock("@/lib/openExternal", () => ({ openExternalUrl: vi.fn() }));

import { MarketplaceView } from "@/views/MarketplaceView";
import { useCreateAgentDialog } from "@/components/society/create/createAgentStore";
import type { SocietyAgent } from "@/components/society/data";
import type { CommunityResponse } from "@/views/PluginsCommunity";

const TEMPLATE = {
  schema: 1 as const,
  name: "Inbox Butler",
  title: "Keeps the inbox at zero",
  instructions: "Sort new mail into Action, Waiting and Read later.",
  tier: "specialist" as const,
  effort: "",
  focus: ["plugin:gmail"],
  grant_mode: "all" as const,
  grants: [],
  denies: [],
  skills: null,
  require_approval: ["plugin:gmail:send"],
  knowledge_scope: "shared" as const,
  avatar: { companion: { shape: "circle", color: "#3366ff" } },
};

const INDEX: CommunityResponse = {
  status: "fresh",
  plugins: [],
  skills: [],
  agents: [
    {
      name: "inbox-butler",
      title: "Inbox Butler",
      description: "Sorts the inbox and drafts the answers that matter.",
      publisher: "octocat",
      version: "1.0.0",
      categories: ["email"],
      source_url: "https://github.com/Dodaios/marketplace/tree/main/agents/inbox-butler",
      agent: TEMPLATE,
      valid: true,
      installed: false,
    },
  ],
};

function installFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
    if (url === "/api/marketplace/community" && method === "GET") return ok(INDEX);
    if (url === "/api/marketplace/publish/identity") return ok({ enabled: true, signed_in: false });
    if (url.endsWith("/contents")) {
      return ok({ kind: "agent", name: "inbox-butler", title: "Inbox Butler", root: "agents/inbox-butler", files: [] });
    }
    if (url === "/api/marketplace/community/install/inbox-butler" && method === "POST") {
      return ok({ ok: true, kind: "agent", id: "inbox-butler", title: "Inbox Butler", ready: true });
    }
    if (url === "/api/society/templates/install" && method === "POST") {
      // Like the server: a whole submission is unwrapped to its template.
      const body = JSON.parse(String(init?.body)) as {
        template: { name?: string; agent?: { name?: string } };
      };
      const template = body.template.agent ?? body.template;
      return ok({
        agent: { agent_id: "imported", name: template.name ?? "Imported" },
        created: true,
        renamed_from: null,
      });
    }
    throw new Error(`unexpected fetch: ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MarketplaceView />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("MarketplaceView — agents", () => {
  it("lists agents on their own shelf with their own filter", async () => {
    installFetchMock();
    renderView();
    expect(await screen.findByText("Inbox Butler")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Agents 1/ })).toBeTruthy();
  });

  it("shows the instructions and the safe defaults before installing", async () => {
    const fetchMock = installFetchMock();
    renderView();
    fireEvent.click(await screen.findByText("Inbox Butler"));

    expect(await screen.findByText(/Sort new mail into Action/)).toBeTruthy();
    expect(screen.getByText(/Runs on your own model/)).toBeTruthy();
    expect(screen.getByText("plugin:gmail:send")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Install" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url) === "/api/marketplace/community/install/inbox-butler" &&
            (init as RequestInit | undefined)?.method === "POST",
        ),
      ).toBe(true),
    );
    expect(await screen.findByText(/on your team now/)).toBeTruthy();
  });

  it("previews an exported template file in the New-agent dialog before it becomes a teammate", async () => {
    const fetchMock = installFetchMock();
    renderView();
    await screen.findByText("Inbox Butler");

    const input = screen.getByTestId("marketplace-import-agent-input") as HTMLInputElement;
    const file = new File([JSON.stringify({ kind: "agent", agent: { ...TEMPLATE, name: "Scribe" } })], "scribe.agent.json", {
      type: "application/json",
    });
    fireEvent.change(input, { target: { files: [file] } });

    // The dialog opens on the import preview; nothing is installed yet.
    await waitFor(() => expect(useCreateAgentDialog.getState().open).toBe(true));
    expect(useCreateAgentDialog.getState().initial).toMatchObject({
      mode: "import",
      template: { kind: "agent", agent: { name: "Scribe" } },
    });
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/install"))).toBe(false);

    // The person confirms in the dialog: the marketplace lands on the new teammate.
    act(() => useCreateAgentDialog.getState().finish({ agentId: "agent-scribe", name: "Scribe" } as SocietyAgent));
    expect(await screen.findByText(/Scribe installed/)).toBeTruthy();
  });

  it("a closed import dialog installs nothing and shows no error", async () => {
    const fetchMock = installFetchMock();
    renderView();
    await screen.findByText("Inbox Butler");
    const input = screen.getByTestId("marketplace-import-agent-input") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File([JSON.stringify(TEMPLATE)], "t.agent.json")] } });
    await waitFor(() => expect(useCreateAgentDialog.getState().open).toBe(true));
    act(() => useCreateAgentDialog.getState().cancel());
    await waitFor(() => expect(useCreateAgentDialog.getState().open).toBe(false));
    expect(screen.queryByText(/could not be imported/)).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/install"))).toBe(false);
  });

  it("names the problem when an imported file is not JSON", async () => {
    installFetchMock();
    renderView();
    await screen.findByText("Inbox Butler");

    const input = screen.getByTestId("marketplace-import-agent-input") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["not json"], "notes.txt")] } });

    expect(await screen.findByText(/could not be imported: notes.txt/)).toBeTruthy();
  });
});
