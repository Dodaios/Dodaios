/**
 * Settings → Self-building: the switch, the level per kind and a cap each
 * write one PUT with only what changed; an out-of-range number is clamped to
 * the range the backend reported.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { SelfBuildGroup } from "@/views/settings/SelfBuildGroup";
import { setUiLanguage } from "@/i18n";

const SETTINGS = {
  enabled: true,
  silent_days: 7,
  memory: "trial",
  skill: "suggest",
  routine: "suggest",
  agent: "suggest",
  code: "suggest",
  trial_days: 14,
  trial_uses: 10,
  max_builds_per_day: 3,
  max_agents_per_week: 1,
  max_open_trials: 5,
  max_code_runs_per_day: 1,
  max_rejections: 2,
  code_land_repos: ["octo/app"],
};

function installFetch() {
  const puts: unknown[] = [];
  let current = { ...SETTINGS };
  const payload = () => ({
    settings: current,
    levels: ["off", "suggest", "trial", "full"],
    bounds: { max_builds_per_day: { min: 0, max: 50 } },
  });
  (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/self-build/settings" && init?.method === "PUT") {
      const body = JSON.parse(String(init.body));
      puts.push(body);
      current = { ...current, ...body };
    } else if (url !== "/api/self-build/settings") {
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    }
    return { ok: true, status: 200, json: async () => payload() } as Response;
  }) as unknown as typeof fetch;
  return puts;
}

function renderGroup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SelfBuildGroup />
    </QueryClientProvider>,
  );
}

describe("SelfBuildGroup", () => {
  beforeEach(() => setUiLanguage("en"));
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("writes only what changed", async () => {
    const puts = installFetch();
    renderGroup();
    const skills = await screen.findByTestId("self-build-autonomy-skill");
    fireEvent.click(within(skills).getByRole("radio", { name: "Trial" }));
    await waitFor(() => expect(puts).toEqual([{ skill: "trial" }]));

    fireEvent.click(within(screen.getByTestId("self-build-enabled")).getByRole("switch"));
    await waitFor(() => expect(puts.at(-1)).toEqual({ enabled: false }));
  });

  it("clamps a cap to the range the backend reported", async () => {
    const puts = installFetch();
    renderGroup();
    const field = within(await screen.findByTestId("self-build-limit-max_builds_per_day")).getByRole("spinbutton");
    fireEvent.change(field, { target: { value: "500" } });
    fireEvent.blur(field);
    await waitFor(() => expect(puts).toEqual([{ max_builds_per_day: 50 }]));
  });

  it("adds and removes a repository that merges on its own, with a warning in sight", async () => {
    const puts = installFetch();
    renderGroup();
    const row = await screen.findByTestId("self-build-land-repos");
    expect(row.textContent).toMatch(/without you looking at the pull request/);
    fireEvent.change(within(row).getByRole("textbox"), { target: { value: "me/tool" } });
    fireEvent.click(within(row).getByRole("button", { name: "Add repository" }));
    await waitFor(() => expect(puts.at(-1)).toEqual({ code_land_repos: ["octo/app", "me/tool"] }));
    fireEvent.click(within(row).getByRole("button", { name: "Remove octo/app" }));
    await waitFor(() => expect(puts.at(-1)).toEqual({ code_land_repos: ["me/tool"] }));
  });
});
