/**
 * A connected plugin whose CLI counterpart is connected too says so (#601):
 * the CLI is used first and the plugin's tools only appear when the user
 * names the plugin. Before, the card said only "Connected · Live".
 *
 * No jest-dom in this repo — assertions use plain values.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { cliPrecedenceText, type Plugin, PluginsView } from "@/views/PluginsView";

const CATALOG = {
  version: 1,
  schema_version: "2026-05-09",
  total: 2,
  connected: 2,
  plugins: [
    {
      id: "github", display_name: "GitHub", description: "Repos and issues", category: "Developer",
      logo_slug: "github", auth: { mode: "pat_paste" }, status: "connected", live_callable: true,
      covered_by_cli: "gh", covered_by_cli_label: "GitHub CLI",
    },
    {
      id: "vercel", display_name: "Vercel", description: "Deployments", category: "Developer",
      logo_slug: "vercel", auth: { mode: "pat_paste" }, status: "connected", live_callable: true,
      covered_by_cli: null, covered_by_cli_label: null,
    },
  ],
};

function plugin(over: Partial<Plugin> = {}): Plugin {
  return {
    id: "github", name: "GitHub", description: "d", category: "Developer", logoSlug: "github",
    authMode: "pat_paste", authConfig: { mode: "pat_paste" }, status: "connected",
    longevity: "permanent", oauthClientConfigured: false, fromMarketplace: false, selfUploaded: false,
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CLI precedence hint", () => {
  it("names the CLI and the plugin on a connected plugin row", async () => {
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => ({
      ok: true, status: 200, json: async () => CATALOG,
    }) as Response) as unknown as typeof fetch;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <PluginsView />
      </QueryClientProvider>,
    );
    await screen.findByRole("button", { name: "GitHub" });
    const hints = screen.getAllByTestId("plugin-cli-precedence");
    expect(hints.map((hint) => hint.textContent)).toEqual([
      "GitHub CLI is connected and is used first; name the GitHub plugin to use it.",
    ]);
  });

  it("stays silent unless the plugin is connected and a CLI covers it", () => {
    expect(cliPrecedenceText(plugin({ coveredByCli: "GitHub CLI" }))).toBe(
      "GitHub CLI is connected and is used first; name the GitHub plugin to use it.",
    );
    expect(cliPrecedenceText(plugin())).toBeUndefined();
    expect(cliPrecedenceText(plugin({ coveredByCli: "GitHub CLI", status: "not_connected" }))).toBeUndefined();
    expect(cliPrecedenceText(plugin({ coveredByCli: "GitHub CLI", status: "needs_reauth" }))).toBeUndefined();
  });
});
