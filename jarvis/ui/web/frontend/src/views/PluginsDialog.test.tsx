import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PluginsDialog } from "./PluginsDialog";

const catalog = {
  version: 1, schema_version: "test", total: 3, connected: 1,
  category_order: ["Developer", "Calendar & Mail"],
  plugins: [
    { id: "github", display_name: "GitHub", description: "Repositories and pull requests", category: "Developer", logo_slug: "github", featured: true, status: "not_connected", auth: { mode: "pat_paste", instruction_md: "Create a token", token_creation_url: "https://github.com/settings/tokens" } },
    { id: "gmail", display_name: "Gmail", description: "Search and read your mail", category: "Calendar & Mail", logo_slug: "gmail", status: "connected", auth: { mode: "pat_paste" } },
    { id: "outlook", display_name: "Outlook", description: "Microsoft mail and calendar", category: "Calendar & Mail", logo_slug: "outlook", status: "not_connected", auth: { mode: "pat_paste", instruction_md: "Connect your account", token_creation_url: "https://example.com" } },
  ],
};

function setup() {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(catalog))));
  const onClose = vi.fn();
  const query = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={query}><PluginsDialog onClose={onClose} /></QueryClientProvider>);
  return { onClose };
}
/** The page beside the sidebar; the sidebar lists installed plugins by the same names. */
const pane = () => within(screen.getByTestId("plugin-catalog-dialog").querySelector<HTMLElement>("[data-plugin-pane]")!);
const installedList = () => within(screen.getByRole("list", { name: "Installed" }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("opens on the directory with its sections, descriptions and an always visible search", async () => {
  setup();
  await pane().findByRole("button", { name: "Gmail" });
  expect(pane().getByText("Search and read your mail")).toBeDefined();
  // Featured picks lead and are not repeated: GitHub is Developer's only plugin,
  // so that section has nothing left to show on the home page.
  expect(pane().getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual(["Popular", "Calendar & Mail"]);
  expect(pane().getAllByRole("button", { name: "GitHub" })).toHaveLength(1);
  fireEvent.change(pane().getByRole("searchbox"), { target: { value: "Microsoft" } });
  await pane().findByRole("button", { name: "Outlook" });
  expect(pane().queryByRole("button", { name: "Gmail" })).toBeNull();
});

it("lists what is installed in the sidebar and opens a plugin page from there", async () => {
  setup();
  const gmail = await installedList().findByRole("button", { name: "Gmail" });
  // Only what was connected or added: the untouched plugins stay in the directory.
  expect(installedList().getAllByRole("listitem")).toHaveLength(1);
  fireEvent.click(gmail);
  const crumbs = within(await pane().findByRole("navigation", { name: "Breadcrumb" }));
  expect(crumbs.getByText("Gmail").getAttribute("aria-current")).toBe("page");
  expect(gmail.getAttribute("aria-current")).toBe("page");
  // "Plugins" in the sidebar always returns to the directory's home page.
  const areas = within(screen.getByRole("navigation", { name: "Plugins, MCPs & Skills" }));
  fireEvent.click(areas.getByRole("button", { name: "Plugins" }));
  await pane().findByRole("region", { name: "Popular" });
  expect(gmail.getAttribute("aria-current")).toBeNull();
});

it("opens a section's full list without leaving the window", async () => {
  setup();
  await pane().findByRole("button", { name: "Gmail" });
  const dialog = screen.getByTestId("plugin-catalog-dialog");
  fireEvent.click(pane().getByRole("button", { name: "Show all of Calendar & Mail" }));
  await waitFor(() => expect(pane().queryByRole("button", { name: "GitHub" })).toBeNull());
  expect(pane().getByRole("button", { name: "Gmail" })).toBeDefined();
  expect(pane().getByRole("button", { name: "Outlook" })).toBeDefined();
  const areas = within(screen.getByRole("navigation", { name: "Plugins, MCPs & Skills" }));
  expect(areas.getAllByRole("button").map((area) => area.textContent)).toEqual(["Plugins", "MCPs", "Skills"]);
  expect(dialog.scrollTop).toBe(0);
});

it("closes credential setup with Escape without closing the plugin window", async () => {
  const { onClose } = setup();
  const [github] = await pane().findAllByRole("button", { name: "GitHub" });
  const row = github.closest("li")!;
  fireEvent.click(within(row).getByRole("button", { name: /^Connect / }));
  await screen.findByRole("dialog", { name: "Connect GitHub" });
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Connect GitHub" })).toBeNull());
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog", { name: "Plugins" })).toBeDefined();
});

it("closes an open menu with Escape without closing the plugin window", async () => {
  const { onClose } = setup();
  await pane().findByRole("button", { name: "Gmail" });
  fireEvent.click(pane().getByRole("button", { name: "Add" }));
  expect(screen.getByRole("menu", { name: "Add" })).toBeDefined();
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("menu", { name: "Add" })).toBeNull());
  expect(onClose).not.toHaveBeenCalled();
  // With nothing open inside, Escape closes the window itself.
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
});

it("opens a plugin picked in the sidebar even while the community page is open", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/community")) {
      return new Response(JSON.stringify({ status: "fresh", revision: 1, generated_at: null, plugins: [], skills: [], agents: [] }));
    }
    return new Response(JSON.stringify(catalog));
  }));
  const query = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={query}><PluginsDialog onClose={vi.fn()} /></QueryClientProvider>);
  await pane().findByRole("button", { name: "Gmail" });
  fireEvent.click(pane().getByRole("button", { name: "Add" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "From the community marketplace" }));
  await waitFor(() => {
    const crumbs = within(pane().getByRole("navigation", { name: "Breadcrumb" }));
    expect(crumbs.getByText("From the community marketplace").getAttribute("aria-current")).toBe("page");
  });

  fireEvent.click(installedList().getByRole("button", { name: "Gmail" }));

  // The plugin page replaces the community page instead of the click doing nothing.
  await waitFor(() => {
    const crumbs = within(pane().getByRole("navigation", { name: "Breadcrumb" }));
    expect(crumbs.getByText("Gmail").getAttribute("aria-current")).toBe("page");
  });
});

