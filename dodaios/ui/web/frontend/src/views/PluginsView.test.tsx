import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  matchesNamePrefix,
  matchesQuery,
  PatConnectDialog,
  PkceConnectDialog,
  sortPluginsByName,
  type Plugin,
  PluginsView,
} from "@/views/PluginsView";
import { PluginRow } from "@/views/plugins/PluginBrowse";

const CATALOG = {
  version: 1,
  schema_version: "2026-05-09",
  total: 2,
  connected: 1,
  plugins: [
    {
      id: "github",
      display_name: "GitHub",
      description: "Repos, issues, pull requests and Actions runs",
      category: "Developer",
      logo_slug: "github",
      logo_color: "F4F4F5",
      auth: { mode: "pat_paste" },
      status: "connected",
      live_callable: true,
    },
    {
      id: "vercel",
      display_name: "Vercel",
      description: "Deployments, runtime logs, domains and env-vars",
      category: "Developer",
      logo_slug: "vercel",
      logo_color: "F4F4F5",
      auth: { mode: "pat_paste" },
      status: "not_connected",
      live_callable: false,
    },
  ],
};

function installCatalogFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/marketplace/plugins") {
      return {
        ok: true,
        status: 200,
        json: async () => CATALOG,
      } as Response;
    }
    if (/^\/api\/marketplace\/plugins\/[^/]+\/files$/.test(url)) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ files: [{ path: "plugin.json", text: "{}", size: 2 }] }),
      } as Response;
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  (globalThis as unknown as { fetch: typeof fetch }).fetch =
    fetchMock as unknown as typeof fetch;
}

function renderPluginsView() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <PluginsView />
    </QueryClientProvider>,
  );
}

/** One directory row on its own, for the controls a row owns. */
function renderRow(
  status: Plugin["status"],
  onConnect: () => void | Promise<void>,
  onDisconnect: (id: string) => void = () => {},
) {
  const plugin: Plugin = {
    id: "row_plugin",
    name: "Row Plugin",
    description: "d",
    category: "Developer",
    logoSlug: "row",
    authMode: "pat_paste",
    authConfig: { mode: "pat_paste" },
    status,
    longevity: "permanent",
    oauthClientConfigured: false,
    fromMarketplace: false,
    selfUploaded: false,
  };
  return render(
    <ul>
      <PluginRow
        plugin={plugin}
        onOpen={() => {}}
        onConnect={onConnect}
        onDisconnect={onDisconnect}
        onRemove={() => {}}
      />
    </ul>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PluginsView lists the catalog in sections", () => {
  it("shows one row per plugin under its category, both scopes and the add menu", async () => {
    installCatalogFetchMock();

    renderPluginsView();

    // One row per catalog entry, named after the plugin.
    await screen.findByRole("button", { name: "GitHub" });
    expect(screen.getByRole("button", { name: "Vercel" })).toBeDefined();
    // The category is a section; its heading opens the full list.
    expect(screen.getByRole("button", { name: "Show all of Developer" })).toBeDefined();
    // Two scopes: what ships with the app, and what the owner added.
    expect(screen.getByRole("tab", { name: "Built in" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Yours" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Add" })).toBeDefined();
    // Nothing needs attention in this catalog, so no reconnect notice.
    expect(screen.queryByText(/reconnecting/)).toBeNull();
    // The roadmap tab carried a static "AVAILABLE" list of Codex plugins that
    // were never installable in Jarvis — it has been removed entirely.
    expect(screen.queryByRole("button", { name: /^Roadmap\b/i })).toBeNull();
    expect(screen.queryByText("ChatGPT Codex plugins")).toBeNull();
  });

  it("leads with the featured plugins and caps a section at six rows", async () => {
    const plugins = Array.from({ length: 8 }, (_, index) => ({
      id: `tool_${index}`,
      display_name: `Tool ${index}`,
      description: "d",
      category: "Developer",
      logo_slug: "tool",
      featured: index === 7,
      auth: { mode: "pat_paste" },
      status: "not_connected",
    }));
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ version: 1, schema_version: "t", total: 8, connected: 0, plugins }),
    })) as unknown as typeof fetch;

    renderPluginsView();

    const popular = await screen.findByRole("region", { name: "Popular" });
    expect(within(popular).getByRole("button", { name: "Tool 7" })).toBeDefined();
    // Popular comes before the category sections.
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Popular",
      "Developer",
    ]);
    // A plugin is on the home page once: the featured one is not repeated
    // under its category.
    expect(screen.getAllByRole("button", { name: "Tool 7" })).toHaveLength(1);
    // Six of the eight show on the home page; the heading opens all of them.
    const developer = screen.getByRole("region", { name: "Developer" });
    expect(within(developer).getAllByRole("listitem")).toHaveLength(6);
    fireEvent.click(screen.getByRole("button", { name: "Show all of Developer" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(8));
    // The breadcrumb leads back to the directory.
    fireEvent.click(screen.getByRole("button", { name: "Plugins" }));
    await screen.findByRole("region", { name: "Popular" });
  });
});

describe("PluginsView live badge", () => {
  it("shows the Live state for a connected plugin with live_callable: true", async () => {
    installCatalogFetchMock();

    renderPluginsView();

    await screen.findByRole("button", { name: "GitHub" });
    // The installed list states each connection in words.
    fireEvent.click(screen.getByRole("button", { name: "Manage installed plugins" }));

    // GitHub is connected + live_callable: true → its row says so.
    expect(await screen.findByText("Connected · Live")).toBeDefined();
    // Vercel was never connected, so the installed list does not carry it.
    expect(screen.queryByRole("button", { name: "Vercel" })).toBeNull();
  });
});

describe("PluginsView states connection in connection words", () => {
  it("says Connect/Connected, never Add/Added, so install and auth cannot mix", async () => {
    installCatalogFetchMock();

    renderPluginsView();

    await screen.findByRole("button", { name: "GitHub" });
    expect(screen.getByRole("button", { name: "Vercel" })).toBeDefined();
    // The untouched row offers a connection, the connected row names it.
    expect(screen.getByRole("button", { name: /^Connect / })).toBeDefined();
    expect(screen.getByRole("img", { name: "Connected" })).toBeDefined();
    // Disconnecting sits behind the row's menu, never one stray click away.
    expect(screen.queryByRole("menuitem", { name: "Disconnect" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^More actions for / }));
    expect(screen.getByRole("menuitem", { name: "Disconnect" })).toBeDefined();
    // No install wording on connection controls: "Added" read as
    // done-before-authed.
    expect(screen.queryByText("Added")).toBeNull();
  });
});

// Regression: `/connect/start` takes ~0.6s with no other feedback, so a user
// clicked the "+" several times and EACH click launched its own OAuth flow — a
// burst of browser tabs + multiple DCR client registrations. The button must
// lock itself (and show a spinner) while a connect is in flight, ignoring the
// extra clicks, then re-enable so a genuine retry still works.
describe("plugin row click-lock", () => {
  it("ignores extra clicks while a connect is in flight", async () => {
    let release: () => void = () => {};
    const onConnect = vi.fn(
      () => new Promise<void>((resolve) => { release = resolve; }),
    );
    renderRow("not_connected", onConnect);
    const btn = screen.getByRole("button", { name: /^Connect / });

    fireEvent.click(btn);
    fireEvent.click(btn); // second click while the first is still pending
    fireEvent.click(btn); // third

    // Only the first click started a flow; the rest were swallowed by the lock.
    expect(onConnect).toHaveBeenCalledTimes(1);
    const busy = await screen.findByRole("button", { name: "Connecting Row Plugin" });
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: /^Connect / })).toBeNull();

    await act(async () => {
      release();
    });
    expect(
      (screen.getByRole("button", { name: /^Connect / }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("re-enables after the connect resolves so a retry still works", async () => {
    const onConnect = vi.fn(() => Promise.resolve());
    renderRow("not_connected", onConnect);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Connect / }));
    });
    const btn = screen.getByRole("button", { name: /^Connect / });
    expect((btn as HTMLButtonElement).disabled).toBe(false);
    await act(async () => {
      fireEvent.click(btn);
    });

    expect(onConnect).toHaveBeenCalledTimes(2);
  });
});

// A revoked / expired plugin (status needs_reauth) must NOT look like a never-
// connected one. It surfaces a distinct "Reconnect" affordance that re-runs the
// same connect flow — the one-click repair for a dead token.
describe("plugin row names", () => {
  it("names its controls after the plugin and reads its text as the description", () => {
    renderRow("not_connected", () => {});
    const row = screen.getByRole("button", { name: "Row Plugin" });
    const details = document.getElementById(row.getAttribute("aria-describedby") ?? "");
    expect(details?.textContent).toBe("d");
    expect(screen.getByRole("button", { name: "Connect Row Plugin" })).toBeDefined();
  });

  it("names the reconnect and menu controls of a broken row after the plugin", () => {
    renderRow("needs_reauth", () => {});
    expect(screen.getByRole("button", { name: "Reconnect Row Plugin" })).toBeDefined();
    expect(screen.getByRole("button", { name: "More actions for Row Plugin" })).toBeDefined();
  });
});

describe("plugin row reconnect state", () => {
  it("renders a Reconnect button for needs_reauth that triggers onConnect", async () => {
    const onConnect = vi.fn(() => Promise.resolve());
    renderRow("needs_reauth", onConnect);
    const btn = screen.getByRole("button", { name: /^Reconnect / });
    expect(btn).toBeDefined();
    await act(async () => {
      fireEvent.click(btn);
    });
    expect(onConnect).toHaveBeenCalledTimes(1);
  });

  it("never shows a plain Connect button or a Connected mark for needs_reauth", () => {
    renderRow("needs_reauth", () => {});
    expect(screen.queryByRole("button", { name: /^Connect / })).toBeNull();
    expect(screen.queryByRole("img", { name: "Connected" })).toBeNull();
  });

  it("keeps Disconnect for a connected plugin behind the row menu", () => {
    const onDisconnect = vi.fn();
    renderRow("connected", () => {}, onDisconnect);
    expect(screen.queryByRole("button", { name: /^Connect / })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^More actions for / }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Disconnect" }));
    expect(onDisconnect).toHaveBeenCalledWith("row_plugin");
  });
});

// Hitting a 28px "+" is the wrong ask for "I want this plugin". The whole card
// starts the same connect flow — except a connected one, where a stray click
// must never disconnect anything.
describe("plugin row click", () => {
  it("opens the detail page, whose Connect button starts the connect flow", async () => {
    installCatalogFetchMock();

    renderPluginsView();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Vercel" })).toBeDefined();
    });
    expect(screen.queryByRole("dialog")).toBeNull();

    // A row opens the detail page — it never starts a flow by itself.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Vercel" }));
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Plugins" })).toBeDefined();
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("Deployments, runtime logs, domains and env-vars")).toBeDefined();

    // Vercel is not_connected + pat_paste → the paste dialog IS its connect flow.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    });
    await waitFor(() => expect(screen.getByRole("dialog")).toBeDefined());
  });

  it("leaves a connected plugin alone — no dialog, no disconnect request", async () => {
    installCatalogFetchMock();

    renderPluginsView();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "GitHub" })).toBeDefined();
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "GitHub" }));
    });

    // The detail page states the connection; nothing destructive fires.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Plugins" })).toBeDefined();
    });
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    const urls = (
      globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.map((c: unknown[]) => String(c[0]));
    // Only reads: the catalog and the plugin's own files — never a DELETE.
    expect(
      urls.every(
        (u: string) => u === "/api/marketplace/plugins" || u === "/api/marketplace/plugins/github/files",
      ),
    ).toBe(true);
  });
});

describe("PkceConnectDialog own-client + production hint", () => {
  const gmail = {
    id: "gmail",
    name: "Gmail",
    description: "Mail",
    category: "Communication",
    logoSlug: "gmail",
    authMode: "oauth_pkce_loopback",
    authConfig: { mode: "oauth_pkce_loopback" },
    status: "not_connected",
    oauthClientConfigured: true,
  } as unknown as Parameters<typeof PkceConnectDialog>[0]["plugin"];

  it("keeps developer setup collapsed for ordinary browser sign-in", () => {
    render(<PkceConnectDialog plugin={gmail} onClose={() => {}} onProceed={() => {}} />);
    expect(screen.queryByLabelText(/client id/i)).toBeNull();
    expect(screen.queryByRole("link", { name: /google cloud console/i })).toBeNull();
  });

  it("proceeds without writing secrets when no client is entered", async () => {
    const fetchMock = vi.fn();
    (globalThis as unknown as { fetch: typeof fetch }).fetch =
      fetchMock as unknown as typeof fetch;
    const onProceed = vi.fn(() => Promise.resolve());
    render(
      <PkceConnectDialog plugin={gmail} onClose={() => {}} onProceed={onProceed} />,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^continue$/i }));
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(onProceed).toHaveBeenCalledTimes(1);
  });

  it("writes google_oauth_client_id/secret then proceeds when a client is entered", async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    (globalThis as unknown as { fetch: typeof fetch }).fetch =
      fetchMock as unknown as typeof fetch;
    const onProceed = vi.fn(() => Promise.resolve());
    render(
      <PkceConnectDialog plugin={gmail} onClose={() => {}} onProceed={onProceed} />,
    );
    fireEvent.click(screen.getByText(/use your own oauth client/i));
    fireEvent.change(screen.getByLabelText(/client id/i), {
      target: { value: "myid.apps.googleusercontent.com" },
    });
    fireEvent.change(screen.getByLabelText(/client secret/i), {
      target: { value: "GOCSPX-x" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^continue$/i }));
    });
    expect(calls).toContain("/api/secrets/google_oauth_client_id");
    expect(calls).toContain("/api/secrets/google_oauth_client_secret");
    expect(onProceed).toHaveBeenCalledTimes(1);
  });

  it("blocks a placeholder-only provider until a client id is entered", () => {
    const slack = {
      ...gmail,
      id: "slack",
      name: "Slack",
      oauthClientFamily: "slack",
      oauthClientConfigured: false,
    };
    render(
      <PkceConnectDialog plugin={slack} onClose={() => {}} onProceed={() => {}} />,
    );

    expect(screen.getByText(/pending publisher setup/i)).toBeDefined();
    expect(
      (screen.getByRole("button", { name: /^continue$/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    // Publisher-pending setup is expanded up front: the client form is the
    // way to connect today, not a hidden expert override.
    expect(screen.getByLabelText(/client id/i)).toBeDefined();
  });

  it("guides a publisher-pending provider through console, redirect URI and client", async () => {
    const slack = {
      ...gmail,
      id: "slack",
      name: "Slack",
      oauthClientFamily: "slack",
      oauthClientConfigured: false,
      browserReady: false,
      authConfig: {
        mode: "oauth_pkce_loopback" as const,
        callback_port: 3118,
        callback_path: "/oauth/callback",
      },
    } as unknown as Parameters<typeof PkceConnectDialog>[0]["plugin"];
    const calls: { url: string; body: string }[] = [];
    (globalThis as unknown as { fetch: typeof fetch }).fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ) => {
      calls.push({ url: String(input), body: String(init?.body ?? "") });
      return { ok: true, status: 200, json: async () => ({ opened: true }) } as Response;
    }) as unknown as typeof fetch;
    render(
      <PkceConnectDialog plugin={slack} onClose={() => {}} onProceed={() => {}} />,
    );

    // Step 1 opens the provider app console in the browser.
    fireEvent.click(
      screen.getByRole("button", { name: /open the slack app console/i }),
    );
    await waitFor(() =>
      expect(
        calls.some(
          (c) => {
            if (c.url !== "/api/settings/open-external") return false;
            const opened = new URL(JSON.parse(c.body).url as string);
            return opened.hostname === "api.slack.com" && opened.pathname === "/apps";
          },
        ),
      ).toBe(true),
    );
    // The exact redirect URI to register, and the client field, are visible
    // without opening any collapsed section first.
    expect(
      screen.getByText("http://127.0.0.1:3118/oauth/callback"),
    ).toBeDefined();
    expect(screen.getByLabelText(/client id/i)).toBeDefined();
  });
});

describe("PluginsView opens the PKCE pre-connect dialog", () => {
  it("shows the own-client dialog instead of starting OAuth immediately", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/marketplace/plugins") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            version: 1,
            schema_version: "t",
            total: 1,
            connected: 0,
            plugins: [
              {
                id: "gmail",
                display_name: "Gmail",
                description: "Mail",
                category: "Communication",
                logo_slug: "gmail",
                auth: { mode: "oauth_pkce_loopback" },
                status: "not_connected",
                live_callable: false,
              },
            ],
          }),
        } as Response;
      }
      // A /connect/start hit here would mean OAuth fired immediately (the old
      // behaviour) — make that an explicit failure.
      throw new Error(`unexpected fetch ${url}`);
    });
    (globalThis as unknown as { fetch: typeof fetch }).fetch =
      fetchMock as unknown as typeof fetch;

    renderPluginsView();
    // Wait for the real row's Connect button rather than the "Gmail" text: the
    // button only exists once the catalog row has actually rendered.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^Connect / }),
      ).toBeDefined(),
    );

    fireEvent.click(screen.getByRole("button", { name: /^Connect / }));

    await waitFor(() =>
      expect(screen.getByRole("dialog")).toBeDefined(),
    );
    expect(screen.getByText(/Connect Gmail/i)).toBeDefined();
  });
});

describe("PluginsView publishes OAuth success immediately", () => {
  it("opens a provisioned browser login at once and shows Gmail as connected", async () => {
    let catalogReads = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/marketplace/plugins") {
        catalogReads += 1;
        if (catalogReads > 1) {
          return new Promise<Response>(() => {});
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({
            version: 1,
            schema_version: "t",
            total: 1,
            connected: 0,
            plugins: [
              {
                id: "gmail",
                display_name: "Gmail",
                description: "Mail",
                category: "Communication",
                logo_slug: "gmail",
                auth: { mode: "oauth_pkce_loopback" },
                status: "not_connected",
                live_callable: false,
                oauth_client_configured: true,
              },
            ],
          }),
        } as Response;
      }
      if (url.endsWith("/connect/start")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            flow_id: "gmail-flow",
            plugin_id: "gmail",
            kind: "browser_redirect",
            open_url: "https://accounts.example.test/authorize",
            expires_at_ms: null,
          }),
        } as Response;
      }
      if (url === "/api/settings/open-external") {
        return {
          ok: true,
          status: 200,
          json: async () => ({ opened: true }),
        } as Response;
      }
      if (url.endsWith("/connect/poll/gmail-flow")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ state: "connected", plugin_id: "gmail" }),
        } as Response;
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    (globalThis as unknown as { fetch: typeof fetch }).fetch =
      fetchMock as unknown as typeof fetch;

    renderPluginsView();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Connect / })).toBeDefined(),
    );
    // A provisioned browser flow opens the provider at once — no intermediate
    // setup form. (Unprovisioned flows still show the pre-connect dialog.)
    fireEvent.click(screen.getByRole("button", { name: /^Connect / }));

    await screen.findByText("Gmail connected");
    expect(
      screen.getByRole("img", { name: "Connected" }),
    ).toBeDefined();
    expect(catalogReads).toBeGreaterThan(1);
  });

  it("names the callback address while waiting so a silent provider is diagnosable", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/marketplace/plugins") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            version: 1,
            schema_version: "t",
            total: 1,
            connected: 0,
            plugins: [
              {
                id: "slack",
                display_name: "Slack",
                description: "Chat",
                category: "Communication",
                logo_slug: "slack",
                auth: { mode: "oauth_pkce_loopback" },
                status: "not_connected",
                live_callable: false,
                oauth_client_configured: true,
              },
            ],
          }),
        } as Response;
      }
      if (url.endsWith("/connect/start")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            flow_id: "slack-flow",
            plugin_id: "slack",
            kind: "browser_redirect",
            open_url: "https://slack.com/oauth/v2/authorize",
            redirect_uri: "http://127.0.0.1:3118/oauth/callback",
            expires_at_ms: null,
          }),
        } as Response;
      }
      if (url === "/api/settings/open-external") {
        return {
          ok: true,
          status: 200,
          json: async () => ({ opened: true }),
        } as Response;
      }
      if (url.endsWith("/connect/poll/slack-flow")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ state: "pending", flow_id: "slack-flow" }),
        } as Response;
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    (globalThis as unknown as { fetch: typeof fetch }).fetch =
      fetchMock as unknown as typeof fetch;

    renderPluginsView();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Connect / })).toBeDefined(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^Connect / }));

    // The pending dialog names the exact address the provider must call
    // back — previously it spun silently when the provider never did.
    await screen.findByText(/to call back at/i);
    expect(
      screen.getByText("http://127.0.0.1:3118/oauth/callback"),
    ).toBeDefined();
    expect(
      screen.getByRole("button", { name: /open slack again/i }),
    ).toBeDefined();
  });
});

function installImmediateConnectionFetch(
  plugin: Record<string, unknown>,
  startPayload?: Record<string, unknown>,
) {
  const probe = { catalogReads: 0 };
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/marketplace/plugins") {
      probe.catalogReads += 1;
      if (probe.catalogReads > 1) return new Promise<Response>(() => {});
      return {
        ok: true,
        status: 200,
        json: async () => ({
          version: 1,
          schema_version: "t",
          total: 1,
          connected: 0,
          plugins: [plugin],
        }),
      } as Response;
    }
    if (url.endsWith("/connect/pat")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ status: "connected" }),
      } as Response;
    }
    if (url.endsWith("/connect/start") && startPayload) {
      return {
        ok: true,
        status: 200,
        json: async () => startPayload,
      } as Response;
    }
    if (url === "/api/settings/open-external") {
      return {
        ok: true,
        status: 200,
        json: async () => ({ opened: true }),
      } as Response;
    }
    if (url.includes("/connect/poll/")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ state: "connected", plugin_id: plugin.id }),
      } as Response;
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  (globalThis as unknown as { fetch: typeof fetch }).fetch =
    fetchMock as unknown as typeof fetch;
  return probe;
}

describe("PluginsView publishes every supported connection path immediately", () => {
  it("publishes a PAT connection before catalog revalidation finishes", async () => {
    const probe = installImmediateConnectionFetch({
      id: "token_service",
      display_name: "Token Service",
      description: "Token-authenticated service",
      category: "Developer",
      logo_slug: "keybase",
      auth: {
        mode: "pat_paste",
        token_creation_url: "https://tokens.example.test",
        token_prefix: "",
        instruction_md: "Create a token.",
      },
      status: "not_connected",
      live_callable: false,
    });

    renderPluginsView();
    fireEvent.click(await screen.findByRole("button", { name: /^Connect / }));
    fireEvent.change(await screen.findByPlaceholderText("Token"), {
      target: { value: "test-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));

    await screen.findByRole("img", { name: "Connected" });
    expect(probe.catalogReads).toBeGreaterThan(1);
  });

  it("publishes a DCR browser-OAuth connection before revalidation finishes", async () => {
    const probe = installImmediateConnectionFetch(
      {
        id: "dcr_service",
        display_name: "DCR Service",
        description: "Dynamic OAuth service",
        category: "Productivity",
        logo_slug: "oauth",
        auth: { mode: "hosted_mcp_oauth_dcr" },
        status: "not_connected",
        live_callable: false,
      },
      {
        flow_id: "dcr-flow",
        plugin_id: "dcr_service",
        kind: "browser_redirect",
        open_url: "https://oauth.example.test/authorize",
        expires_at_ms: null,
      },
    );

    renderPluginsView();
    fireEvent.click(await screen.findByRole("button", { name: /^Connect / }));

    await screen.findByText("DCR Service connected");
    expect(screen.getByRole("img", { name: "Connected" })).toBeDefined();
    expect(probe.catalogReads).toBeGreaterThan(1);
  });

  it("publishes a device-flow connection before revalidation finishes", async () => {
    const probe = installImmediateConnectionFetch(
      {
        id: "device_service",
        display_name: "Device Service",
        description: "Device-code OAuth service",
        category: "Developer",
        logo_slug: "auth0",
        auth: { mode: "oauth_device_flow" },
        oauth_client_configured: true,
        status: "not_connected",
        live_callable: false,
      },
      {
        flow_id: "device-flow",
        plugin_id: "device_service",
        kind: "device_flow",
        open_url: null,
        user_code: "ABCD-EFGH",
        verification_uri: "https://device.example.test",
        verification_uri_complete: null,
        expires_at_ms: Date.now() + 300_000,
      },
    );

    renderPluginsView();
    fireEvent.click(await screen.findByRole("button", { name: /^Connect / }));

    await screen.findByText("Device Service connected");
    expect(screen.getByRole("img", { name: "Connected" })).toBeDefined();
    expect(probe.catalogReads).toBeGreaterThan(1);
  });
});

describe("PluginsView keeps revoked plugins visible", () => {
  it("names a needs_reauth plugin up front and lists it as installed with a Reconnect control", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/marketplace/plugins") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            version: 1,
            schema_version: "t",
            total: 1,
            connected: 0,
            plugins: [
              {
                id: "gmail",
                display_name: "Gmail",
                description: "Mail",
                category: "Communication",
                logo_slug: "gmail",
                auth: { mode: "oauth_pkce_loopback" },
                status: "needs_reauth",
                live_callable: false,
              },
            ],
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch ${String(input)}`);
    });
    (globalThis as unknown as { fetch: typeof fetch }).fetch =
      fetchMock as unknown as typeof fetch;

    renderPluginsView();

    // The directory says which connection broke before anything else.
    await screen.findByText("Gmail needs reconnecting");
    // Its row is a Reconnect, never a plain "+" as if it was never connected.
    expect(screen.getByRole("button", { name: /^Reconnect / })).toBeDefined();
    expect(screen.queryByRole("button", { name: /^Connect / })).toBeNull();

    // The installed list still carries it — a dead token does not drop the
    // plugin back among the never-connected ones.
    fireEvent.click(screen.getByRole("button", { name: "Manage installed plugins" }));
    await screen.findByText("Reconnect needed");
    expect(screen.getByRole("button", { name: "Gmail" })).toBeDefined();
    expect(screen.getByRole("button", { name: /^Reconnect / })).toBeDefined();
  });
});

describe("PatConnectDialog asks for a self-hosted server address", () => {
  const selfHosted = {
    id: "home_assistant",
    name: "Home Assistant",
    description: "Smart home",
    category: "Home & Devices",
    logoSlug: "homeassistant",
    authMode: "pat_paste" as const,
    authConfig: {
      mode: "pat_paste",
      token_creation_url: "https://example.test/token",
      token_prefix: "",
      instruction_md: "Create a long-lived token.",
      instance_url: {
        label: "Your Home Assistant address",
        placeholder: "http://192.168.1.20:8123",
        help_md: "The address you use in your browser.",
      },
    },
    status: "not_connected" as const,
    longevity: "permanent" as const,
  };

  it("cannot submit without the address, then passes it through", () => {
    const onSubmit = vi.fn();
    render(
      <PatConnectDialog
        plugin={selfHosted as never}
        onClose={() => {}}
        onSubmit={onSubmit}
        isPending={false}
        errorMessage={null}
      />,
    );

    const token = screen.getByPlaceholderText("Token");
    fireEvent.change(token, { target: { value: "llat-secret" } });

    // A self-hosted plugin cannot be reached at all without its address, so
    // Connect stays disabled rather than failing a round-trip later.
    const connect = screen.getByRole("button", { name: /connect/i });
    expect((connect as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText("http://192.168.1.20:8123"), {
      target: { value: "http://192.168.1.20:8123/lovelace/0" },
    });
    fireEvent.click(screen.getByRole("button", { name: /connect/i }));

    expect(onSubmit).toHaveBeenCalledWith(
      "llat-secret",
      null,
      "http://192.168.1.20:8123/lovelace/0",
    );
  });
});

describe("PluginsView category sections are data-driven", () => {
  function catalogWith(plugins: unknown[], categoryOrder?: string[]) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/marketplace/plugins") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            version: 1,
            schema_version: "t",
            total: plugins.length,
            connected: 0,
            category_order: categoryOrder,
            plugins,
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch ${String(input)}`);
    });
    (globalThis as unknown as { fetch: typeof fetch }).fetch =
      fetchMock as unknown as typeof fetch;
  }

  const row = (id: string, category: string, extra: Record<string, unknown> = {}) => ({
    id,
    display_name: id,
    description: "d",
    category,
    logo_slug: id,
    auth: { mode: "pat_paste" },
    status: "not_connected",
    live_callable: false,
    ...extra,
  });

  it("renders a category the frontend has never heard of instead of crashing", async () => {
    // The previous fixed record threw on `byCat[category].push(...)`, which
    // blanked the entire view behind its error boundary. A backend-only
    // taxonomy change must not be able to do that.
    catalogWith(
      [row("mystery", "Something Brand New"), row("known", "Developer")],
      ["Developer"],
    );

    renderPluginsView();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "mystery" })).toBeDefined();
    });
    expect(screen.getByText("Something Brand New")).toBeDefined();
    // Its heading opens the section like any other, fed by the same data.
    fireEvent.click(screen.getByRole("button", { name: "Show all of Something Brand New" }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "known" })).toBeNull();
    });
    expect(screen.getByRole("button", { name: "mystery" })).toBeDefined();
  });

  it("orders sections by the catalog's category_order", async () => {
    catalogWith(
      [row("b", "Second"), row("a", "First")],
      ["First", "Second"],
    );

    renderPluginsView();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "a" })).toBeDefined();
    });
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "First",
      "Second",
    ]);
  });

  it("states how long the connection lasts before the user connects", async () => {
    catalogWith([
      row("forever", "Developer", { longevity: "permanent" }),
      row("limited", "Developer", {
        longevity: "provider_limited",
        longevity_note: "Google asks again every 7 days in Testing mode.",
      }),
    ]);

    renderPluginsView();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "limited" })).toBeDefined();
    });
    // The detail page carries the longevity fact sheet.
    fireEvent.click(screen.getByRole("button", { name: "limited" }));
    await waitFor(() => {
      expect(screen.getByText("Sign in again periodically")).toBeDefined();
    });
    expect(screen.getByText("Google asks again every 7 days in Testing mode.")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Plugins" }));
    fireEvent.click(await screen.findByRole("button", { name: "forever" }));
    await waitFor(() => {
      expect(screen.getByText("Stays connected")).toBeDefined();
    });
  });
});

describe("plugin search matches more than the display name", () => {
  const plugin = (extra: Record<string, unknown> = {}): Plugin => ({
    id: "stripe",
    name: "Stripe",
    description: "Payments, customers, invoices and balance",
    category: "Developer",
    logoSlug: "stripe",
    authMode: "pat_paste",
    authConfig: { mode: "pat_paste" },
    status: "not_connected",
    longevity: "permanent",
    oauthClientConfigured: false,
    fromMarketplace: false,
    selfUploaded: false,
    ...extra,
  });

  it("matches everything when the query is blank or whitespace", () => {
    expect(matchesQuery(plugin(), "")).toBe(true);
    expect(matchesQuery(plugin(), "   ")).toBe(true);
  });

  it("matches on the description, so a capability word finds the plugin", () => {
    // The old name-only match returned nothing here — the word "payments"
    // never appears in "Stripe".
    expect(matchesQuery(plugin(), "payments")).toBe(true);
  });

  it("matches on the category and on the catalog id", () => {
    expect(matchesQuery(plugin(), "developer")).toBe(true);
    expect(matchesQuery(plugin({ name: "Google Drive", id: "google_drive" }), "google_drive")).toBe(
      true,
    );
  });

  const gmail = () =>
    plugin({
      id: "gmail",
      name: "Gmail",
      description: "Read and send mail from your inbox",
      category: "Calendar & Mail",
    });

  it("matches the vendor family, so 'google' finds Gmail", () => {
    // "Google" appears nowhere in Gmail's name, description, category or id —
    // only in the OAuth client family it shares with Drive and Calendar.
    expect(matchesQuery(gmail(), "google")).toBe(true);
  });

  it("ANDs the words, so a second word narrows instead of widening", () => {
    const drive = plugin({
      id: "google_drive",
      name: "Google Drive",
      description: "Files Jarvis creates or you share with it",
      category: "Files & Photos",
    });
    expect(matchesQuery(gmail(), "google mail")).toBe(true);
    expect(matchesQuery(drive, "google mail")).toBe(false);
  });

  it("ignores case and rejects a word that appears in no field", () => {
    expect(matchesQuery(plugin(), "INVOICES")).toBe(true);
    expect(matchesQuery(plugin(), "kubernetes")).toBe(false);
  });
});

describe("plugin prefix search lists G-starting plugins A-Z", () => {
  const make = (name: string, extra: Record<string, unknown> = {}): Plugin => ({
    id: name.toLowerCase().replace(/[^a-z0-9]+/g, "_"),
    name,
    description: "d",
    category: "Developer",
    logoSlug: "x",
    authMode: "pat_paste",
    authConfig: { mode: "pat_paste" },
    status: "not_connected",
    longevity: "permanent",
    oauthClientConfigured: false,
    fromMarketplace: false,
    selfUploaded: false,
    ...extra,
  });

  it("matches only names starting with the query, case-insensitive", () => {
    const gmail = make("Gmail");
    expect(matchesNamePrefix(gmail, "G")).toBe(true);
    expect(matchesNamePrefix(gmail, "g")).toBe(true);
    expect(matchesNamePrefix(gmail, "Gmail")).toBe(true);
    expect(matchesNamePrefix(make("AgentMail"), "G")).toBe(false);
    expect(matchesNamePrefix(make("Cal.com"), "g")).toBe(false);
    expect(matchesNamePrefix(make("Outlook Mail & Calendar"), "g")).toBe(false);
  });

  it("orders AA before AZ and sorts case-insensitively", () => {
    const names = ["AZ", "AA", "Gmail", "Google Drive", "Google Calendar"].map((n) => make(n));
    const sorted = [...names].sort(sortPluginsByName).map((p) => p.name);
    expect(sorted).toEqual(["AA", "AZ", "Gmail", "Google Calendar", "Google Drive"]);
  });

  it("matches the vendor family prefix, so 'google' still finds Gmail", () => {
    const gmail = make("Gmail", { id: "gmail" });
    expect(matchesNamePrefix(gmail, "google")).toBe(true);
  });
});

describe("PluginsView search and scope controls", () => {
  const search = () => screen.getByRole("searchbox", { name: "Search plugins…" });

  it("offers the two scopes as tabs under the header", async () => {
    installCatalogFetchMock();
    renderPluginsView();

    await waitFor(() => {
      expect(screen.getByRole("tablist", { name: "Plugin directory" })).toBeDefined();
    });
    for (const label of ["Built in", "Yours"]) {
      expect(screen.getByRole("tab", { name: label })).toBeDefined();
    }
  });

  it("invites adding a plugin when the owner has added none", async () => {
    installCatalogFetchMock();
    renderPluginsView();

    await screen.findByRole("button", { name: "GitHub" });
    fireEvent.click(screen.getByRole("tab", { name: "Yours" }));

    expect(screen.getByText("Nothing added yet")).toBeDefined();
    expect(screen.queryByRole("button", { name: "GitHub" })).toBeNull();
    expect(screen.getByRole("button", { name: "Custom connector (URL)" })).toBeDefined();
  });

  it("hides the match count and clear button until a search is active", async () => {
    installCatalogFetchMock();
    renderPluginsView();

    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Connected" })).toBeDefined();
    });
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
    expect(screen.queryByText(/matches$/)).toBeNull();

    fireEvent.change(search(), { target: { value: "deployments" } });

    // Vercel's description carries "Deployments"; GitHub's does not.
    await waitFor(() => {
      expect(screen.getByText("1 matches")).toBeDefined();
    });
    expect(screen.getByRole("button", { name: "Vercel" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "GitHub" })).toBeNull();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeDefined();
    // A search lists results flat: the scope tabs step aside.
    expect(screen.queryByRole("tablist", { name: "Plugin directory" })).toBeNull();
  });

  it("restores the full list when the search is cleared", async () => {
    installCatalogFetchMock();
    renderPluginsView();

    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Connected" })).toBeDefined();
    });
    fireEvent.change(search(), { target: { value: "kubernetes" } });
    await waitFor(() => {
      expect(screen.getByText("0 matches")).toBeDefined();
    });
    expect(screen.getByText("No plugin matches the current filters.")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Show all plugins" }));

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
    });
    expect(screen.getByRole("img", { name: "Connected" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Vercel" })).toBeDefined();
  });

  it("explains an empty installed list instead of blanking", async () => {
    // With nothing connected the installed list is empty. That path used to
    // render nothing at all — no message, no way back.
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/marketplace/plugins") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ...CATALOG,
            connected: 0,
            plugins: CATALOG.plugins.map((p) => ({
              ...p,
              status: "not_connected",
              live_callable: false,
            })),
          }),
        } as Response;
      }
      throw new Error(`unexpected fetch ${String(input)}`);
    });
    (globalThis as unknown as { fetch: typeof fetch }).fetch =
      fetchMock as unknown as typeof fetch;
    renderPluginsView();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "GitHub" })).toBeDefined();
    });

    fireEvent.click(screen.getByRole("button", { name: "Manage installed plugins" }));

    await waitFor(() => {
      expect(screen.getByText("No plugins connected yet")).toBeDefined();
    });
    fireEvent.click(screen.getByRole("button", { name: "Plugins" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "GitHub" })).toBeDefined();
    });
  });

  it("never claims nothing is connected while a search is hiding the plugins", async () => {
    installCatalogFetchMock();
    renderPluginsView();

    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Connected" })).toBeDefined();
    });
    fireEvent.click(screen.getByRole("button", { name: "Manage installed plugins" }));
    fireEvent.change(search(), { target: { value: "kubernetes" } });

    await waitFor(() => {
      expect(screen.getByText(/No plugin matches/)).toBeDefined();
    });
    expect(screen.queryByText("No plugins connected yet")).toBeNull();
  });

  it("lists every plugin exactly once — no promo strip, no Coming-soon decoy", async () => {
    // The carousel used to put GitHub on screen a second time, and the
    // Coming-soon strip listed names that had long had real catalog entries.
    // A featured plugin leads under Popular and is not repeated below.
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        ...CATALOG,
        plugins: CATALOG.plugins.map((p) => ({ ...p, featured: p.id === "github" })),
      }),
    })) as unknown as typeof fetch;
    renderPluginsView();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "GitHub" })).toBeDefined();
    });
    expect(screen.getAllByText("GitHub")).toHaveLength(1);
    expect(screen.getAllByText("Vercel")).toHaveLength(1);
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Popular",
      "Developer",
    ]);
    expect(screen.queryByText("Coming soon")).toBeNull();
  });
});

describe("PluginsView breadcrumbs", () => {
  it("returns to the directory home from a plugin opened in search results", async () => {
    installCatalogFetchMock();
    renderPluginsView();

    await screen.findByRole("button", { name: "GitHub" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search plugins…" }), {
      target: { value: "deploy" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Vercel" }));
    const crumbs = within(await screen.findByRole("navigation", { name: "Breadcrumb" }));
    fireEvent.click(crumbs.getByRole("button", { name: "Plugins" }));

    // The crumb says "Plugins" and leads to the directory, not back into the search.
    await screen.findByRole("tablist", { name: "Plugin directory" });
    expect((screen.getByRole("searchbox", { name: "Search plugins…" }) as HTMLInputElement).value).toBe("");
    expect(screen.getByRole("button", { name: "GitHub" })).toBeDefined();
  });

  it("closes a section whose last plugin went away while it was open", async () => {
    const added = {
      id: "acme",
      display_name: "Acme",
      description: "Own connector",
      category: "Custom",
      logo_slug: "acme",
      auth: { mode: "hosted_mcp_open" },
      status: "not_connected",
      source: "local",
    };
    let reads = 0;
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => {
      reads += 1;
      const plugins = reads === 1 ? [...CATALOG.plugins, added] : CATALOG.plugins;
      return { ok: true, status: 200, json: async () => ({ ...CATALOG, plugins }) };
    }) as unknown as typeof fetch;
    renderPluginsView();

    fireEvent.click(await screen.findByRole("tab", { name: "Yours" }));
    fireEvent.click(screen.getByRole("button", { name: "Show all of Added by you" }));
    await screen.findByRole("navigation", { name: "Breadcrumb" });

    // The connector is removed elsewhere; the next catalog read no longer has it.
    fireEvent.click(screen.getByRole("button", { name: "Refresh catalog" }));
    await screen.findByRole("tablist", { name: "Plugin directory" });
    expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).toBeNull();
    expect(screen.getByText("Nothing added yet")).toBeDefined();
  });
});
