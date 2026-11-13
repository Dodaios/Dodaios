/**
 * The Nodes library page.
 *
 * Contracts worth pinning:
 * - it opens on "All": every card but the runs without a page, last changed
 *   first, under the "Make something new" row; the tabs carry their counts,
 * - a tab, the type filter, the order and the view are remembered
 *   (`jarvis.nodes.*`); the search is not,
 * - the new-row steps aside as soon as the reader searches, filters or
 *   leaves "All",
 * - a card opens by click and by Enter; arrow keys walk the cards; a star
 *   is its own button and feeds the Favorites tab,
 * - a right-click opens the card's own menu and never reaches the app-wide
 *   one; Delete on a focused card asks before anything is deleted,
 * - a card can be dragged to the assistant's dock and carries its run,
 * - a request made in the dialog leaves a placeholder that leads the grid
 *   until a new card of that type arrives,
 * - loading, an empty library, an empty tab and a failed load each have
 *   their own state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { MISSION_DND_MIME } from "@/lib/missionDnd";
import type { NodeCard } from "./nodeModel";
import { NodesLibrary } from "./NodesLibrary";
import { useNodesLibrary } from "./useNodesLibrary";

const chat = vi.hoisted(() => ({
  requestNewNode: vi.fn(async (_type: string, _text: string) => undefined),
  askDodaiosToChange: vi.fn(async () => undefined),
}));
// The real module opens the chat store; the library only needs its two calls.
vi.mock("./askDodaios", () => chat);
// The covers are another component's business (and its own tests).
vi.mock("./NodeCover", () => ({
  NodeCover: ({ card, peek }: { card: NodeCard; peek?: boolean }) => (
    <div data-testid="node-cover" data-node-type={card.type} data-peek={peek || undefined} />
  ),
}));

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
    version: 1,
    status: "ready",
    kept_current: false,
    refreshing: false,
    every_minutes: 0,
    request: "",
    preview: null,
    ...over,
  };
}

const BRIEF = card("brief", { id: "n-brief", title: "Website brief", type: "docs", updated_at: 500 });
const DECK = card("deck", { id: "n-deck", title: "Quarterly review", type: "slides", updated_at: 400 });
const SHEET = card("sheet", {
  id: "n-sheet",
  title: "Budget",
  type: "sheets",
  updated_at: 300,
  kept_current: true,
  refreshing: true,
});
const LOGO = card("logo", {
  title: "Logo sketch",
  type: "design",
  origin: "file",
  path: "logo-sketch.png",
  visual_kind: "image",
  updated_at: 200,
});
const RUN = card("run:tidy", {
  title: "Tidy the downloads",
  type: "output",
  origin: "run",
  path: null,
  visual_kind: null,
  updated_at: 600,
});
const SAMPLE = [BRIEF, DECK, SHEET, LOGO, RUN];

interface Api {
  nodes: NodeCard[];
  fail?: boolean;
  hang?: boolean;
  created?: NodeCard;
}

function installFetch(api: Api) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url === "/api/nodes" && method === "GET") {
      if (api.hang) return new Promise<never>(() => undefined);
      if (api.fail) return { ok: false, status: 500, json: async () => ({ detail: "down" }) };
      return { ok: true, status: 200, json: async () => ({ nodes: api.nodes, scanned_runs: 5, skipped_runs: 0 }) };
    }
    if (url === "/api/nodes" && method === "POST") {
      return { ok: true, status: 200, json: async () => api.created ?? BRIEF };
    }
    if (url.includes("/capabilities")) {
      return { ok: true, status: 200, json: async () => ({ native_file_actions: false, platform: "linux" }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function Harness({ onOpen }: { onOpen: (card: NodeCard) => void }) {
  const library = useNodesLibrary();
  return <NodesLibrary library={library} onOpen={onOpen} />;
}

function renderLibrary() {
  const onOpen = vi.fn<(card: NodeCard) => void>();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <Harness onOpen={onOpen} />
    </QueryClientProvider>,
  );
  return { onOpen, client };
}

const cards = () => screen.getAllByTestId("node-card");
const shownKeys = () => screen.queryAllByTestId("node-card").map((element) => element.getAttribute("data-node-key"));
const tab = (id: string) => screen.getByTestId(`nodes-tab-${id}`);

beforeEach(() => {
  window.localStorage.clear();
  chat.requestNewNode.mockReset();
  chat.requestNewNode.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("NodesLibrary", () => {
  it("opens on All: the cards last changed first, under the new-row, with counts on the tabs", async () => {
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");

    expect(screen.getByTestId("nodes-title").textContent).toBe("Nodes");
    expect(shownKeys()).toEqual(["brief", "deck", "sheet", "logo"]);
    expect(screen.getByTestId("nodes-type-row")).toBeTruthy();
    expect(screen.getAllByTestId("node-cover")).toHaveLength(4);

    expect(tab("all").getAttribute("aria-pressed")).toBe("true");
    expect(tab("runs").getAttribute("aria-pressed")).toBe("false");
    expect(["all", "favorites", "kept", "runs"].map((id) => tab(id).getAttribute("data-count"))).toEqual([
      "4",
      "0",
      "1",
      "1",
    ]);
  });

  it("says what a card is: its name, its state and its type", async () => {
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");

    const sheet = cards()[2];
    expect(sheet.textContent).toContain("Budget");
    expect(within(sheet).getByTestId("node-card-state").getAttribute("data-state")).toBe("kept");
    expect(sheet.textContent).toContain("Sheets");
    expect(sheet.getAttribute("data-node-type")).toBe("sheets");
    // A card that is not kept current says nothing about it.
    expect(within(cards()[0]).queryByTestId("node-card-state")).toBeNull();
  });

  it("shows the runs without a page under Runs, without the shelf of types, and remembers the tab", async () => {
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");

    fireEvent.click(tab("runs"));
    expect(shownKeys()).toEqual(["run:tidy"]);
    expect(screen.queryByTestId("nodes-type-row")).toBeNull();
    expect(window.localStorage.getItem("jarvis.nodes.tab")).toBe("runs");

    fireEvent.click(tab("kept"));
    expect(shownKeys()).toEqual(["sheet"]);
  });

  it("comes back with the tab and the view the reader left it in", async () => {
    window.localStorage.setItem("jarvis.nodes.tab", "kept");
    window.localStorage.setItem("jarvis.nodes.view", "list");
    installFetch({ nodes: SAMPLE });
    renderLibrary();

    await screen.findByTestId("nodes-list");
    expect(screen.queryByTestId("nodes-grid")).toBeNull();
    expect(tab("kept").getAttribute("aria-pressed")).toBe("true");
    expect(shownKeys()).toEqual(["sheet"]);
  });

  it("searches in place: the field opens focused, narrows the cards, and Escape clears it", async () => {
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");

    fireEvent.click(screen.getByTestId("nodes-search"));
    const field = screen.getByTestId("nodes-search-field") as HTMLInputElement;
    expect(document.activeElement).toBe(field);

    fireEvent.change(field, { target: { value: "budget" } });
    expect(shownKeys()).toEqual(["sheet"]);
    // The shelf stays: a search can be narrowed to a type as well.
    expect(screen.getByTestId("nodes-type-row")).toBeTruthy();

    fireEvent.keyDown(screen.getByTestId("nodes-search-field"), { key: "Escape" });
    expect(screen.queryByTestId("nodes-search-field")).toBeNull();
    expect(shownKeys()).toEqual(["brief", "deck", "sheet", "logo"]);
    expect(document.activeElement).toBe(screen.getByTestId("nodes-search"));
  });

  it("says so when a search finds nothing, and offers the way back", async () => {
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");

    fireEvent.click(screen.getByTestId("nodes-search"));
    fireEvent.change(screen.getByTestId("nodes-search-field"), { target: { value: "zebra" } });
    expect(screen.getByTestId("nodes-no-matches").textContent).toContain("zebra");
    expect(screen.queryByTestId("nodes-grid")).toBeNull();

    fireEvent.click(screen.getByTestId("nodes-show-all"));
    expect(shownKeys()).toEqual(["brief", "deck", "sheet", "logo"]);
  });

  it("filters by one type and remembers it", async () => {
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");

    fireEvent.click(screen.getByTestId("nodes-filter"));
    const panel = screen.getByTestId("nodes-filter-panel");
    expect(within(panel).getAllByRole("menuitemradio")).toHaveLength(8 + 3);
    expect(screen.getByTestId("nodes-filter-type-all").getAttribute("aria-checked")).toBe("true");

    fireEvent.click(screen.getByTestId("nodes-filter-type-sheets"));
    expect(screen.queryByTestId("nodes-filter-panel")).toBeNull();
    expect(shownKeys()).toEqual(["sheet"]);
    // The shelf shows the same choice: its tile is the picked one.
    expect(screen.getByTestId("nodes-type-sheets").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("nodes-filter").getAttribute("data-active")).toBe("true");
    expect(window.localStorage.getItem("jarvis.nodes.type")).toBe("sheets");

    // A type nothing was made of yet: one sentence, and "show all" lifts the filter.
    fireEvent.click(screen.getByTestId("nodes-filter"));
    fireEvent.click(screen.getByTestId("nodes-filter-type-motion"));
    expect(screen.getByTestId("nodes-no-matches").textContent).toContain("Clips");
    fireEvent.click(screen.getByTestId("nodes-show-all"));
    expect(shownKeys()).toEqual(["brief", "deck", "sheet", "logo"]);
    expect(screen.getByTestId("nodes-type-motion").getAttribute("aria-pressed")).toBe("false");
  });

  it("leaves the type filter out of the Runs tab", async () => {
    window.localStorage.setItem("jarvis.nodes.type", "sheets");
    window.localStorage.setItem("jarvis.nodes.tab", "runs");
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");

    expect(shownKeys()).toEqual(["run:tidy"]);
    fireEvent.click(screen.getByTestId("nodes-filter"));
    // Only the three orders are on offer here.
    expect(within(screen.getByTestId("nodes-filter-panel")).getAllByRole("menuitemradio")).toHaveLength(3);
  });

  it("orders by name when asked", async () => {
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");

    fireEvent.click(screen.getByTestId("nodes-filter"));
    expect(screen.getByTestId("nodes-sort-changed").getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByTestId("nodes-sort-name"));
    expect(shownKeys()).toEqual(["sheet", "logo", "deck", "brief"]);
    expect(window.localStorage.getItem("jarvis.nodes.sort")).toBe("name");
  });

  it("stars a card with its own button, and Favorites shows the starred ones", async () => {
    installFetch({ nodes: SAMPLE });
    const { onOpen } = renderLibrary();
    await screen.findByTestId("nodes-grid");

    const star = screen.getAllByTestId("node-card-star")[1];
    expect(star.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(star);
    expect(screen.getAllByTestId("node-card-star")[1].getAttribute("aria-pressed")).toBe("true");
    // The star is not the card: nothing opened.
    expect(onOpen).not.toHaveBeenCalled();
    expect(tab("favorites").getAttribute("data-count")).toBe("1");

    fireEvent.click(tab("favorites"));
    expect(shownKeys()).toEqual(["deck"]);

    // "F" on the card takes the star away again; the tab is then empty.
    fireEvent.keyDown(cards()[0], { key: "f" });
    expect(screen.getByTestId("nodes-no-matches")).toBeTruthy();
    fireEvent.click(screen.getByTestId("nodes-show-all"));
    expect(tab("all").getAttribute("aria-pressed")).toBe("true");
  });

  it("opens a card by click and by Enter", async () => {
    installFetch({ nodes: SAMPLE });
    const { onOpen } = renderLibrary();
    await screen.findByTestId("nodes-grid");

    fireEvent.click(cards()[0]);
    expect(onOpen).toHaveBeenLastCalledWith(BRIEF);
    fireEvent.keyDown(cards()[1], { key: "Enter" });
    expect(onOpen).toHaveBeenLastCalledWith(DECK);
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("walks the cards with the arrow keys", async () => {
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");

    const [first, second, third, last] = cards();
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(document.activeElement).toBe(second);
    fireEvent.keyDown(second, { key: "ArrowDown" });
    expect(document.activeElement).toBe(third);
    fireEvent.keyDown(third, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(second);
    fireEvent.keyDown(second, { key: "End" });
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(last, { key: "Home" });
    expect(document.activeElement).toBe(first);
  });

  it("is the same cards as a list one toggle away", async () => {
    installFetch({ nodes: SAMPLE });
    const { onOpen } = renderLibrary();
    await screen.findByTestId("nodes-grid");

    const toggle = screen.getByTestId("nodes-view-toggle");
    expect(toggle.getAttribute("data-view")).toBe("grid");
    fireEvent.click(toggle);
    expect(screen.getByTestId("nodes-list")).toBeTruthy();
    expect(screen.queryByTestId("nodes-grid")).toBeNull();
    expect(shownKeys()).toEqual(["brief", "deck", "sheet", "logo"]);
    expect(window.localStorage.getItem("jarvis.nodes.view")).toBe("list");

    fireEvent.click(cards()[3]);
    expect(onOpen).toHaveBeenLastCalledWith(LOGO);
    fireEvent.click(screen.getByTestId("nodes-view-toggle"));
    expect(screen.getByTestId("nodes-grid")).toBeTruthy();
  });

  it("opens the card's menu on a right-click and from its more button", async () => {
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");
    // The app-wide Cut/Copy/Paste menu listens on document.
    const appMenu = vi.fn();
    document.addEventListener("contextmenu", appMenu);

    try {
      fireEvent.contextMenu(cards()[0], { clientX: 40, clientY: 60 });
    } finally {
      document.removeEventListener("contextmenu", appMenu);
    }
    expect(screen.getByRole("menu")).toBeTruthy();
    expect(screen.getByTestId("node-menu-rename")).toBeTruthy();
    // The right-click stopped at the card.
    expect(appMenu).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();

    // An adopted picture: the same menu without what only a typed node can do.
    fireEvent.click(screen.getAllByTestId("node-card-menu")[3]);
    expect(screen.getByRole("menu")).toBeTruthy();
    expect(screen.queryByTestId("node-menu-rename")).toBeNull();
    expect(screen.getByTestId("node-menu-download")).toBeTruthy();
  });

  it("asks before deleting when Delete is pressed on a card, and not at all for one still being built", async () => {
    const wip = card("build:wip", {
      title: "Sales by region",
      type: "design",
      origin: "build",
      path: null,
      visual_kind: null,
      status: "building",
    });
    const fetchMock = installFetch({ nodes: [wip, ...SAMPLE] });
    renderLibrary();
    await screen.findByTestId("nodes-grid");
    const deleted = () =>
      fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE").map(([input]) => String(input));

    expect(shownKeys().slice(0, 2)).toEqual(["build:wip", "brief"]);
    // Its worker may be writing into that very folder: the key does nothing.
    fireEvent.keyDown(cards()[0], { key: "Delete" });
    expect(screen.queryByTestId("node-confirm-delete")).toBeNull();

    fireEvent.keyDown(cards()[1], { key: "Delete" });
    const question = await screen.findByTestId("node-confirm-delete");
    expect(question.textContent).toContain("Website brief");
    // Nothing is gone before the answer.
    expect(deleted()).toEqual([]);

    fireEvent.click(screen.getByTestId("node-confirm-delete-confirm"));
    await waitFor(() => expect(deleted()).toEqual(["/api/nodes/n-brief"]));
    await waitFor(() => expect(screen.queryByTestId("node-confirm-delete")).toBeNull());
  });

  it("lets a card be dragged to the assistant's dock, carrying its run", async () => {
    installFetch({ nodes: [card("report", { title: "Q3 report", slug: "run-q3", request: "Write the Q3 report" }), LOGO] });
    renderLibrary();
    await screen.findByTestId("nodes-grid");

    const [report, logo] = cards();
    expect(report.getAttribute("draggable")).toBe("true");
    const setData = vi.fn();
    fireEvent.dragStart(report, { dataTransfer: { setData, setDragImage: vi.fn(), effectAllowed: "" } });
    expect(setData).toHaveBeenCalledTimes(1);
    const [mime, json] = setData.mock.calls[0];
    expect(mime).toBe(MISSION_DND_MIME);
    // The run is what the dock takes, named by what was asked for.
    expect(JSON.parse(json)).toMatchObject({ slug: "run-q3", utterance: "Write the Q3 report", status: "success" });
    fireEvent.dragEnd(report);

    // A card whose run recorded no request goes by its name.
    setData.mockClear();
    fireEvent.dragStart(logo, { dataTransfer: { setData, setDragImage: vi.fn(), effectAllowed: "" } });
    expect(JSON.parse(setData.mock.calls[0][1])).toMatchObject({ slug: "logo", utterance: "Logo sketch" });
    fireEvent.dragEnd(logo);
  });

  it("keeps a placeholder first in the grid until the requested node arrives", async () => {
    const api: Api = { nodes: SAMPLE };
    installFetch(api);
    const { onOpen, client } = renderLibrary();
    await screen.findByTestId("nodes-grid");

    fireEvent.click(screen.getByTestId("nodes-new"));
    const dialog = await screen.findByTestId("new-node-dialog");
    fireEvent.click(within(dialog).getByTestId("new-node-type-sheets"));
    fireEvent.change(within(dialog).getByTestId("new-node-request"), {
      target: { value: "A budget for this year by month and by team" },
    });
    fireEvent.click(within(dialog).getByTestId("new-node-create"));

    await waitFor(() => expect(shownKeys()[0]).toMatch(/^pending:/));
    expect(chat.requestNewNode).toHaveBeenCalledWith("sheets", "A budget for this year by month and by team");
    expect(screen.queryByTestId("new-node-dialog")).toBeNull();

    const placeholder = cards()[0];
    expect(placeholder.getAttribute("data-status")).toBe("building");
    expect(placeholder.getAttribute("data-node-type")).toBe("sheets");
    expect(placeholder.textContent).toContain("A budget for this year by…");
    expect(within(placeholder).getByTestId("node-card-state").getAttribute("data-state")).toBe("building");
    expect(shownKeys().slice(1)).toEqual(["brief", "deck", "sheet", "logo"]);
    // A promise, not a node: it does not open, and it has no star and no menu.
    fireEvent.click(placeholder);
    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.getAllByTestId("node-card-star")).toHaveLength(4);

    api.nodes = [card("new-sheet", { id: "n-new", title: "Budget 2026", type: "sheets", updated_at: 900 }), ...SAMPLE];
    await client.invalidateQueries({ queryKey: ["nodes"] });
    await waitFor(() => expect(shownKeys()).toEqual(["new-sheet", "brief", "deck", "sheet", "logo"]));
  });

  it("shows six skeleton cards while the library has not answered", async () => {
    installFetch({ nodes: [], hang: true });
    renderLibrary();

    const skeleton = await screen.findByTestId("nodes-skeleton");
    expect(skeleton.getAttribute("aria-busy")).toBe("true");
    expect(skeleton.children).toHaveLength(6);
    // No invented zeros on the tabs.
    expect(tab("runs").getAttribute("data-count")).toBeNull();
    expect(screen.queryByTestId("nodes-grid")).toBeNull();
  });

  it("invites to make something when the library is empty", async () => {
    installFetch({ nodes: [] });
    renderLibrary();

    const empty = await screen.findByTestId("nodes-empty");
    expect(screen.getByTestId("nodes-type-row")).toBeTruthy();
    // The one action of an empty library: make the first node.
    fireEvent.click(within(empty).getByTestId("nodes-new"));
    expect(await screen.findByTestId("new-node-dialog")).toBeTruthy();
    // Nothing to pick from, nothing to search: the tabs and tools are left out.
    expect(screen.queryByTestId("nodes-tab-all")).toBeNull();
    expect(screen.queryByTestId("nodes-search")).toBeNull();
  });

  it("says that the library could not be loaded, and tries again on request", async () => {
    const api: Api = { nodes: SAMPLE, fail: true };
    installFetch(api);
    renderLibrary();

    const error = await screen.findByTestId("nodes-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(screen.queryByTestId("nodes-type-row")).toBeNull();

    api.fail = false;
    fireEvent.click(within(error).getByRole("button"));
    await screen.findByTestId("nodes-grid");
    expect(shownKeys()).toEqual(["brief", "deck", "sheet", "logo"]);
  });

  it("lets a card's page scroll once the pointer rests on it, not while it only passes", async () => {
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");
    const card = cards()[0];
    const cover = within(card).getByTestId("node-cover");

    // Passing over the library sets nothing moving.
    fireEvent.pointerEnter(card);
    fireEvent.pointerLeave(card);
    await new Promise((resolve) => setTimeout(resolve, 520));
    expect(cover.getAttribute("data-peek")).toBeNull();

    fireEvent.pointerEnter(card);
    expect(cover.getAttribute("data-peek")).toBeNull();
    await waitFor(() => expect(cover.getAttribute("data-peek")).toBe("true"), { timeout: 2000 });

    fireEvent.pointerLeave(card);
    expect(cover.getAttribute("data-peek")).toBeNull();
  });

  it("shows the nodes of a type when its tile is picked, and never makes one", async () => {
    const fetchMock = installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");
    // How many of each type the tab holds, beside the names.
    expect(screen.getByTestId("nodes-type-count-sheets").textContent).toBe("1");

    fireEvent.click(screen.getByTestId("nodes-type-sheets"));
    expect(shownKeys()).toEqual(["sheet"]);
    expect(screen.getByTestId("nodes-type-sheets").getAttribute("aria-pressed")).toBe("true");
    expect(window.localStorage.getItem("jarvis.nodes.type")).toBe("sheets");
    // A tile is a way in: no dialog, and nothing was sent anywhere.
    expect(screen.queryByTestId("new-node-dialog")).toBeNull();
    expect(fetchMock.mock.calls.every(([, init]) => (init?.method ?? "GET") === "GET")).toBe(true);

    // The picked tile again: everything is back.
    fireEvent.click(screen.getByTestId("nodes-type-sheets"));
    expect(shownKeys()).toEqual(["brief", "deck", "sheet", "logo"]);
    expect(window.localStorage.getItem("jarvis.nodes.type")).toBe("all");
  });

  it("starts a new node with the type the reader is looking at", async () => {
    installFetch({ nodes: SAMPLE });
    renderLibrary();
    await screen.findByTestId("nodes-grid");

    fireEvent.click(screen.getByTestId("nodes-new"));
    let dialog = await screen.findByTestId("new-node-dialog");
    expect(within(dialog).getByTestId("new-node-type-docs").getAttribute("aria-checked")).toBe("true");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("new-node-dialog")).toBeNull());

    // An empty shelf says so and offers the one next step.
    fireEvent.click(screen.getByTestId("nodes-type-motion"));
    fireEvent.click(within(screen.getByTestId("nodes-no-matches")).getByTestId("nodes-new-of-type"));
    dialog = await screen.findByTestId("new-node-dialog");
    expect(within(dialog).getByTestId("new-node-type-motion").getAttribute("aria-checked")).toBe("true");
  });
});
