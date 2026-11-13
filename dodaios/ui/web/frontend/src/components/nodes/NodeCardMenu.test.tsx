/**
 * The card menu of the Nodes library, and what its items lead to.
 *
 * Contracts worth pinning:
 * - what the menu offers follows the card: a typed node can be renamed,
 *   duplicated, changed through the assistant and reverted; a card with a
 *   file can be opened in the browser and saved; "Show in folder" exists on
 *   the desktop only; a card still being built cannot be deleted,
 * - it is a keyboard menu: the first item has the focus, arrows walk the
 *   items, Escape and Tab leave it, focus goes back to where it came from,
 * - rename, duplicate, revert and delete call the nodes API (an adopted
 *   file and a run are deleted through the run archive instead), and the
 *   library is read again afterwards,
 * - a delete the server refuses with 409 says "still being worked on" in
 *   the question itself, which stays open.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { useArtifactFavorites } from "@/hooks/useArtifactFavorites";
import { NodeCardMenu, cardBrowserUrl, useNodeCardActions, type NodeCardMenuProps } from "./NodeCardMenu";
import type { NodeCard } from "./nodeModel";

const chat = vi.hoisted(() => ({
  requestNewNode: vi.fn(async () => undefined),
  askDodaiosToChange: vi.fn(async (_card: unknown) => undefined),
}));
vi.mock("./askDodaios", () => chat);

const external = vi.hoisted(() => ({ openExternalUrl: vi.fn(async (_url: string) => true) }));
vi.mock("@/lib/openExternal", () => external);

function card(key: string, over: Partial<NodeCard> = {}): NodeCard {
  return {
    key,
    id: null,
    type: "docs",
    origin: "node",
    title: key,
    slug: key,
    path: "index.html",
    visual_kind: "page",
    created_at: 1_000,
    updated_at: 1_000,
    size: 10,
    version: 2,
    status: "ready",
    kept_current: false,
    refreshing: false,
    every_minutes: 0,
    request: "",
    preview: null,
    ...over,
  };
}

const BRIEF = card("brief", { id: "n-brief", title: "Website brief" });
const LOGO = card("logo", {
  title: "Logo sketch",
  type: "design",
  origin: "file",
  path: "art/logo sketch.png",
  visual_kind: "image",
  version: 0,
});
const RUN = card("run:tidy", {
  title: "Tidy the downloads",
  type: "output",
  origin: "run",
  slug: "tidy",
  path: null,
  visual_kind: null,
  version: 0,
});
const BUILDING = card("build:sales", {
  title: "Sales by region",
  type: "data",
  origin: "build",
  slug: "sales",
  path: null,
  visual_kind: null,
  status: "building",
  version: 0,
});

interface Call {
  url: string;
  method: string;
  body: unknown;
}

type Respond = (url: string, method: string) => { status: number; body?: unknown } | undefined;

function installFetch(respond: Respond = () => undefined, desktop = false): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method, body: typeof init?.body === "string" ? JSON.parse(init.body) : null });
      const custom = respond(url, method);
      const status = custom?.status ?? 200;
      const fallback = url.includes("/capabilities") ? { native_file_actions: desktop, platform: "darwin" } : {};
      return { ok: status < 400, status, json: async () => custom?.body ?? fallback };
    }),
  );
  return calls;
}

function handlers() {
  return {
    onDismiss: vi.fn(),
    onOpen: vi.fn(),
    onToggleFavorite: vi.fn(),
    onRename: vi.fn(),
    onDuplicate: vi.fn(),
    onAsk: vi.fn(),
    onRevert: vi.fn(),
    onOpenExternal: vi.fn(),
    onDownload: vi.fn(),
    onReveal: vi.fn(),
    onDelete: vi.fn(),
  };
}

function renderMenu(target: NodeCard, over: Partial<NodeCardMenuProps> = {}) {
  const spies = handlers();
  render(<NodeCardMenu card={target} x={10} y={10} favorite={false} canReveal={false} {...spies} {...over} />);
  return spies;
}

const items = () => screen.getAllByRole("menuitem").map((item) => item.getAttribute("data-testid"));
const item = (id: string) => screen.getByTestId(`node-menu-${id}`) as HTMLButtonElement;

function Harness({ target, onOpen }: { target: NodeCard; onOpen: (card: NodeCard) => void }) {
  const { favorites, toggle } = useArtifactFavorites();
  const actions = useNodeCardActions({ favorites, onToggleFavorite: toggle, onOpen });
  return (
    <>
      <button
        type="button"
        data-testid="trigger"
        onClick={(event) => actions.openMenu(target, 10, 10, event.currentTarget)}
      >
        menu
      </button>
      <button type="button" data-testid="delete-key" onClick={() => actions.askDelete(target)}>
        delete
      </button>
      {actions.layer}
    </>
  );
}

function renderActions(target: NodeCard) {
  const onOpen = vi.fn<(card: NodeCard) => void>();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <Harness target={target} onOpen={onOpen} />
    </QueryClientProvider>,
  );
  return { onOpen, invalidate };
}

function openMenu() {
  fireEvent.click(screen.getByTestId("trigger"));
}

beforeEach(() => {
  window.localStorage.clear();
  chat.askDodaiosToChange.mockClear();
  external.openExternalUrl.mockClear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("NodeCardMenu: what it offers", () => {
  it("offers a typed node everything", () => {
    renderMenu(BRIEF);
    expect(screen.getByRole("menu")).toBeTruthy();
    expect(items()).toEqual([
      "node-menu-open",
      "node-menu-favorite",
      "node-menu-rename",
      "node-menu-duplicate",
      "node-menu-ask",
      "node-menu-revert",
      "node-menu-open-external",
      "node-menu-download",
      "node-menu-delete",
    ]);
    expect(item("delete").disabled).toBe(false);
  });

  it("offers an adopted file what a file can do", () => {
    renderMenu(LOGO);
    expect(items()).toEqual([
      "node-menu-open",
      "node-menu-favorite",
      "node-menu-open-external",
      "node-menu-download",
      "node-menu-delete",
    ]);
  });

  it("offers a run without a page only the basics", () => {
    renderMenu(RUN);
    expect(items()).toEqual(["node-menu-open", "node-menu-favorite", "node-menu-delete"]);
  });

  it("adds Show in folder on the desktop", () => {
    renderMenu(RUN, { canReveal: true });
    expect(items()).toEqual(["node-menu-open", "node-menu-favorite", "node-menu-reveal", "node-menu-delete"]);
  });

  it("will not delete a card that is still being built", () => {
    renderMenu(BUILDING, { canReveal: true });
    expect(items()).toEqual(["node-menu-open", "node-menu-favorite", "node-menu-delete"]);
    expect(item("delete").disabled).toBe(true);
    // The reason is there for whoever wonders.
    expect(item("delete").getAttribute("title")).toBeTruthy();
  });

  it("names the favorite item by what it will do", () => {
    renderMenu(BRIEF);
    const add = item("favorite").textContent;
    cleanup();
    renderMenu(BRIEF, { favorite: true });
    expect(item("favorite").textContent).not.toBe(add);
  });

  it("reports each choice to its handler", () => {
    const spies = renderMenu(BRIEF, { canReveal: true });
    fireEvent.click(item("open"));
    fireEvent.click(item("favorite"));
    fireEvent.click(item("rename"));
    fireEvent.click(item("duplicate"));
    fireEvent.click(item("ask"));
    fireEvent.click(item("revert"));
    fireEvent.click(item("open-external"));
    fireEvent.click(item("download"));
    fireEvent.click(item("reveal"));
    fireEvent.click(item("delete"));
    const { onDismiss, ...choices } = spies;
    for (const spy of Object.values(choices)) expect(spy).toHaveBeenCalledTimes(1);
    expect(onDismiss).not.toHaveBeenCalled();
  });
});

describe("NodeCardMenu: keyboard", () => {
  it("starts on the first item and walks with the arrows", () => {
    renderMenu(RUN);
    expect(document.activeElement).toBe(item("open"));
    fireEvent.keyDown(item("open"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(item("favorite"));
    fireEvent.keyDown(item("favorite"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(item("delete"));
    // Past the end is the beginning, and the other way round.
    fireEvent.keyDown(item("delete"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(item("open"));
    fireEvent.keyDown(item("open"), { key: "ArrowUp" });
    expect(document.activeElement).toBe(item("delete"));
    fireEvent.keyDown(item("delete"), { key: "Home" });
    expect(document.activeElement).toBe(item("open"));
    fireEvent.keyDown(item("open"), { key: "End" });
    expect(document.activeElement).toBe(item("delete"));
  });

  it("skips an item that is disabled", () => {
    renderMenu(BUILDING);
    fireEvent.keyDown(item("open"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(item("favorite"));
    fireEvent.keyDown(item("favorite"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(item("open"));
  });

  it("leaves on Escape and on Tab", () => {
    const spies = renderMenu(RUN);
    fireEvent.keyDown(item("open"), { key: "Escape" });
    expect(spies.onDismiss).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(item("open"), { key: "Tab" });
    expect(spies.onDismiss).toHaveBeenCalledTimes(2);
  });

  it("leaves on a press outside, not on one inside", () => {
    const spies = renderMenu(RUN);
    fireEvent.pointerDown(item("open"));
    expect(spies.onDismiss).not.toHaveBeenCalled();
    fireEvent.pointerDown(document.body);
    expect(spies.onDismiss).toHaveBeenCalledTimes(1);
  });
});

describe("useNodeCardActions", () => {
  it("opens from the menu, and hands the focus back when the menu leaves", async () => {
    installFetch();
    const { onOpen } = renderActions(BRIEF);
    openMenu();
    expect(screen.getByRole("menu")).toBeTruthy();
    fireEvent.keyDown(item("open"), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(screen.getByTestId("trigger"));

    openMenu();
    fireEvent.click(item("open"));
    expect(onOpen).toHaveBeenCalledWith(BRIEF);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("stars and unstars through the menu", () => {
    installFetch();
    renderActions(BRIEF);
    openMenu();
    const add = item("favorite").textContent;
    fireEvent.click(item("favorite"));
    expect(JSON.parse(window.localStorage.getItem("jarvis.artifacts.favorites") ?? "[]")).toEqual(["brief"]);
    openMenu();
    expect(item("favorite").textContent).not.toBe(add);
    fireEvent.click(item("favorite"));
    expect(JSON.parse(window.localStorage.getItem("jarvis.artifacts.favorites") ?? "[]")).toEqual([]);
  });

  it("renames a node through its dialog", async () => {
    const calls = installFetch();
    const { invalidate } = renderActions(BRIEF);
    openMenu();
    fireEvent.click(item("rename"));

    const dialog = await screen.findByTestId("node-rename-dialog");
    expect(dialog).toBeTruthy();
    const field = screen.getByTestId("node-rename-field") as HTMLInputElement;
    expect(field.value).toBe("Website brief");
    const save = screen.getByTestId("node-rename-save") as HTMLButtonElement;
    // The same name is nothing to save.
    expect(save.disabled).toBe(true);

    fireEvent.change(field, { target: { value: "  Relaunch brief " } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);

    await waitFor(() => expect(screen.queryByTestId("node-rename-dialog")).toBeNull());
    expect(calls.find((call) => call.method === "PATCH")).toEqual({
      url: "/api/nodes/n-brief",
      method: "PATCH",
      body: { title: "Relaunch brief" },
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["nodes"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["outputs"] });
  });

  it("keeps the rename dialog open when the server refuses", async () => {
    installFetch((_url, method) => (method === "PATCH" ? { status: 500 } : undefined));
    renderActions(BRIEF);
    openMenu();
    fireEvent.click(item("rename"));
    await screen.findByTestId("node-rename-dialog");
    fireEvent.change(screen.getByTestId("node-rename-field"), { target: { value: "Relaunch brief" } });
    fireEvent.click(screen.getByTestId("node-rename-save"));

    await screen.findByRole("alert");
    expect(screen.getByTestId("node-rename-dialog")).toBeTruthy();
    expect((screen.getByTestId("node-rename-field") as HTMLInputElement).value).toBe("Relaunch brief");
  });

  it("duplicates and reverts through the nodes API", async () => {
    const calls = installFetch();
    const { invalidate } = renderActions(BRIEF);
    openMenu();
    fireEvent.click(item("duplicate"));
    await waitFor(() =>
      expect(calls.find((call) => call.url === "/api/nodes/n-brief/duplicate")).toEqual({
        url: "/api/nodes/n-brief/duplicate",
        method: "POST",
        body: {},
      }),
    );

    openMenu();
    fireEvent.click(item("revert"));
    await waitFor(() =>
      expect(calls.find((call) => call.url === "/api/nodes/n-brief/revert")?.method).toBe("POST"),
    );
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["nodes"] }));
  });

  it("hands a change request to the assistant's conversation", () => {
    installFetch();
    renderActions(BRIEF);
    openMenu();
    fireEvent.click(item("ask"));
    expect(chat.askDodaiosToChange).toHaveBeenCalledWith(BRIEF);
  });

  it("opens a page in the browser on its sandboxed URL, a picture on its inline one", () => {
    installFetch();
    renderActions(BRIEF);
    openMenu();
    fireEvent.click(item("open-external"));
    expect(external.openExternalUrl).toHaveBeenCalledTimes(1);
    expect(external.openExternalUrl.mock.calls[0][0]).toContain("/api/outputs/brief/files/index.html/page?theme=");

    expect(cardBrowserUrl(LOGO, "dark")).toBe(
      "/api/outputs/logo/files/art/logo%20sketch.png/download?disposition=inline",
    );
    expect(cardBrowserUrl(RUN, "dark")).toBeNull();
  });

  it("shows a file in its folder on the desktop", async () => {
    const calls = installFetch(undefined, true);
    renderActions(LOGO);
    openMenu();
    fireEvent.click(await screen.findByTestId("node-menu-reveal"));
    await waitFor(() =>
      expect(calls.find((call) => call.url.endsWith("/reveal"))).toEqual({
        url: "/api/outputs/logo/files/art/logo%20sketch.png/reveal",
        method: "POST",
        body: null,
      }),
    );
  });

  it("asks before deleting, names the node, and deletes a typed node through the nodes API", async () => {
    const calls = installFetch();
    const { invalidate } = renderActions(BRIEF);
    openMenu();
    fireEvent.click(item("delete"));

    const question = await screen.findByTestId("node-confirm-delete");
    expect(question.textContent).toContain("Website brief");
    // Nothing is gone before the answer.
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);

    fireEvent.click(screen.getByTestId("node-confirm-delete-confirm"));
    await waitFor(() => expect(screen.queryByTestId("node-confirm-delete")).toBeNull());
    expect(calls.filter((call) => call.method === "DELETE").map((call) => call.url)).toEqual([
      "/api/nodes/n-brief",
    ]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["nodes"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["outputs"] });
  });

  it("deletes an adopted file as that file, and a run as the whole run", async () => {
    const calls = installFetch();
    renderActions(LOGO);
    fireEvent.click(screen.getByTestId("delete-key"));
    await screen.findByTestId("node-confirm-delete");
    fireEvent.click(screen.getByTestId("node-confirm-delete-confirm"));
    await waitFor(() => expect(screen.queryByTestId("node-confirm-delete")).toBeNull());
    expect(calls.filter((call) => call.method === "DELETE").map((call) => call.url)).toEqual([
      "/api/outputs/logo/files/art/logo%20sketch.png",
    ]);

    cleanup();
    calls.length = 0;
    renderActions(RUN);
    fireEvent.click(screen.getByTestId("delete-key"));
    await screen.findByTestId("node-confirm-delete");
    fireEvent.click(screen.getByTestId("node-confirm-delete-confirm"));
    await waitFor(() => expect(screen.queryByTestId("node-confirm-delete")).toBeNull());
    expect(calls.filter((call) => call.method === "DELETE").map((call) => call.url)).toEqual(["/api/outputs/tidy"]);
  });

  it("says that it is still being worked on when the server answers 409", async () => {
    installFetch((_url, method) => (method === "DELETE" ? { status: 409, body: { detail: "running" } } : undefined));
    renderActions(BRIEF);
    fireEvent.click(screen.getByTestId("delete-key"));
    await screen.findByTestId("node-confirm-delete");
    fireEvent.click(screen.getByTestId("node-confirm-delete-confirm"));

    const running = (await screen.findByTestId("node-delete-error")).textContent;
    expect(running).toBeTruthy();
    // The question stays, so the sentence is read where the delete was asked for.
    expect(screen.getByTestId("node-confirm-delete")).toBeTruthy();

    // Any other refusal reads differently, for an adopted file as well.
    cleanup();
    installFetch((_url, method) => (method === "DELETE" ? { status: 500 } : undefined));
    renderActions(LOGO);
    fireEvent.click(screen.getByTestId("delete-key"));
    await screen.findByTestId("node-confirm-delete");
    fireEvent.click(screen.getByTestId("node-confirm-delete-confirm"));
    const failed = (await screen.findByTestId("node-delete-error")).textContent;
    expect(failed).toBeTruthy();
    expect(failed).not.toBe(running);

    cleanup();
    installFetch((_url, method) => (method === "DELETE" ? { status: 409 } : undefined));
    renderActions(LOGO);
    fireEvent.click(screen.getByTestId("delete-key"));
    await screen.findByTestId("node-confirm-delete");
    fireEvent.click(screen.getByTestId("node-confirm-delete-confirm"));
    expect((await screen.findByTestId("node-delete-error")).textContent).toBe(running);
  });

  it("does not offer to delete what is still being built", () => {
    installFetch();
    renderActions(BUILDING);
    fireEvent.click(screen.getByTestId("delete-key"));
    expect(screen.queryByTestId("node-confirm-delete")).toBeNull();
  });
});
