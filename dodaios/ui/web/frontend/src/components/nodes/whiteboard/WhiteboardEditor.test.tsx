/**
 * The whiteboard editor on the stage, with the editor package replaced by a
 * stand-in (the real one needs a canvas).
 *
 * Contracts worth pinning:
 * - the board opens on its scene (`GET /scene`), restored for the editor
 *   (text measured, bindings repaired) and with its pictures fetched,
 * - a change is saved after a short pause (`PUT /scene`), and at once when
 *   the window hides,
 * - a merged answer and a revision someone else made are reconciled into
 *   the editor outside its undo history,
 * - the editor follows the app's theme and language, has no AI tools, no web
 *   embeds and no theme switch of its own, and greets in the app's words,
 * - a key pressed in the canvas never reaches the app's window shortcuts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import type { BoardElement, SceneRead } from "./boardApi";

const pkg = vi.hoisted(() => {
  const state = {
    props: null as null | Record<string, unknown>,
    elements: [] as Array<Record<string, unknown>>,
    api: null as null | Record<string, ReturnType<typeof vi.fn>>,
  };
  const restoreElements = vi.fn((elements: Array<Record<string, unknown>> | null) =>
    (elements ?? []).map((element) => ({ ...element, restored: true })),
  );
  const reconcileElements = vi.fn((local: Array<Record<string, unknown>>, remote: Array<Record<string, unknown>>) => {
    const byId = new Map(local.map((element) => [element.id, element]));
    for (const element of remote) {
      const mine = byId.get(element.id);
      if (!mine || (element.version as number) > (mine.version as number)) byId.set(element.id, element);
    }
    return [...byId.values()];
  });
  return { state, restoreElements, reconcileElements };
});

const external = vi.hoisted(() => ({ openExternalUrl: vi.fn(async (_url: string) => undefined) }));
vi.mock("@/lib/openExternal", () => external);
vi.mock("@excalidraw/excalidraw/index.css", () => ({}));
vi.mock("./whiteboard.css", () => ({}));
vi.mock("@excalidraw/excalidraw", async () => {
  const React = await import("react");
  const named = (name: string) => {
    const component = ({ children }: { children?: ReactNode }) =>
      React.createElement("div", { "data-part": name }, children);
    return component;
  };
  const Excalidraw = (props: Record<string, unknown>) => {
    pkg.state.props = props;
    React.useEffect(() => {
      const initial = props.initialData as { elements: Array<Record<string, unknown>> };
      pkg.state.elements = initial.elements;
      const api = {
        getSceneElementsIncludingDeleted: vi.fn(() => pkg.state.elements),
        getSceneElements: vi.fn(() => pkg.state.elements.filter((element) => !element.isDeleted)),
        scrollToContent: vi.fn(),
        getAppState: vi.fn(() => ({ viewBackgroundColor: "#ffffff", gridModeEnabled: false })),
        updateScene: vi.fn((data: { elements?: Array<Record<string, unknown>> }) => {
          if (data.elements) pkg.state.elements = data.elements;
        }),
        addFiles: vi.fn(),
        setActiveTool: vi.fn(),
      };
      pkg.state.api = api;
      (props.excalidrawAPI as (api: unknown) => void)(api);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    const top = (props.renderTopRightUI as (() => ReactNode) | undefined)?.();
    return React.createElement(
      "div",
      { className: "excalidraw", "data-testid": "fake-excalidraw", tabIndex: 0 },
      top,
      props.children as ReactNode,
    );
  };
  const MainMenu = Object.assign(named("main-menu"), {
    Separator: named("separator"),
    DefaultItems: new Proxy({}, { get: (_target, key) => named(`menu-${String(key)}`) }),
  });
  const Center = Object.assign(named("welcome-center"), {
    Heading: named("welcome-heading"),
    Menu: named("welcome-menu"),
    MenuItemLoadScene: named("welcome-load"),
    MenuItemHelp: named("welcome-help"),
  });
  const WelcomeScreen = Object.assign(named("welcome"), {
    Center,
    Hints: { MenuHint: named("hint-menu"), ToolbarHint: named("hint-toolbar"), HelpHint: named("hint-help") },
  });
  return {
    Excalidraw,
    MainMenu,
    WelcomeScreen,
    CaptureUpdateAction: { IMMEDIATELY: "IMMEDIATELY", NEVER: "NEVER", EVENTUALLY: "EVENTUALLY" },
    FONT_FAMILY: { Virgil: 1, Helvetica: 2, Cascadia: 3, Excalifont: 5, Nunito: 6 },
    restoreElements: pkg.restoreElements,
    reconcileElements: pkg.reconcileElements,
  };
});

import WhiteboardEditor, { settleBoard } from "./WhiteboardEditor";
import { SAVE_DEBOUNCE_MS } from "./boardSync";

function el(id: string, version = 1, over: Partial<BoardElement> = {}): BoardElement {
  return { id, type: "rectangle", version, versionNonce: version, isDeleted: false, ...over };
}

function sceneRead(elements: BoardElement[], updatedAt = 100, files: SceneRead["scene"]["files"] = {}): SceneRead {
  return {
    version: 1,
    updated_at: updatedAt,
    scene: { format: "scene", elements, appState: { viewBackgroundColor: "#fff3bf", gridModeEnabled: true }, files },
  };
}

interface Server {
  scene: SceneRead;
  put?: (body: { scene: { elements: BoardElement[] } }) => unknown;
}

function installServer(server: Server) {
  let revision = server.scene.updated_at;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/nodes/b1/scene" && (!init?.method || init.method === "GET")) {
      return new Response(JSON.stringify(server.scene), { status: 200 });
    }
    if (url === "/api/nodes/b1/scene" && init?.method === "PUT") {
      const body = JSON.parse(String(init.body));
      const answer = server.put?.(body) ?? { version: 2, updated_at: ++revision, merged: false };
      return new Response(JSON.stringify(answer), { status: 200 });
    }
    if (url === "/api/nodes/b1/files" && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      return new Response(JSON.stringify({ id: body.id, mimeType: "image/png" }), { status: 200 });
    }
    if (url.startsWith("/api/nodes/b1/files/")) {
      return new Response(new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" }), {
        status: 200,
        headers: { "Content-Type": "image/png" },
      });
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function puts(fetchMock: ReturnType<typeof installServer>) {
  return fetchMock.mock.calls.filter(([url, init]) => String(url) === "/api/nodes/b1/scene" && init?.method === "PUT");
}

/** The editor reports a change, as the real one does with every edit. */
function change(elements: Array<Record<string, unknown>>, files: Record<string, unknown> = {}) {
  pkg.state.elements = elements;
  const onChange = pkg.state.props?.onChange as (e: unknown, a: unknown, f: unknown) => void;
  act(() => onChange(elements, { viewBackgroundColor: "#fff3bf", gridModeEnabled: true, activeTool: { type: "selection" } }, files));
}

async function openBoard(props: { revision?: number | null } = {}) {
  const view = render(<WhiteboardEditor nodeId="b1" title="Launch plan" revision={props.revision ?? null} />);
  await screen.findByTestId("fake-excalidraw");
  await waitFor(() => expect(pkg.state.api).not.toBeNull());
  return view;
}

beforeEach(() => {
  pkg.state.props = null;
  pkg.state.api = null;
  pkg.state.elements = [];
  pkg.restoreElements.mockClear();
  pkg.reconcileElements.mockClear();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("WhiteboardEditor", () => {
  it("opens the board on its scene, restored for the editor, with its pictures", async () => {
    const image = el("img", 1, { type: "image", fileId: "f1" });
    const fetchMock = installServer({
      scene: sceneRead([el("a"), image], 100, { f1: { id: "f1", mimeType: "image/png", created: 3 } }),
    });
    await openBoard();

    expect(window.EXCALIDRAW_ASSET_PATH).toBe("/assets/excalidraw/");
    expect(pkg.restoreElements).toHaveBeenCalledWith(
      [el("a"), image],
      null,
      { refreshDimensions: true, repairBindings: true },
    );
    const initial = pkg.state.props?.initialData as { elements: unknown[]; appState: unknown; scrollToContent: boolean };
    expect(initial.elements).toHaveLength(2);
    expect(initial.appState).toEqual({ viewBackgroundColor: "#fff3bf", gridModeEnabled: true });
    expect(initial.scrollToContent).toBe(true);

    await waitFor(() => expect(pkg.state.api?.addFiles).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/nodes/b1/files/f1")).toBe(true);
    const [files] = pkg.state.api!.addFiles.mock.calls[0] as [Array<{ id: string; dataURL: string; mimeType: string }>];
    expect(files[0]).toMatchObject({ id: "f1", mimeType: "image/png", created: 3 });
    expect(files[0].dataURL.startsWith("data:image/png;base64,")).toBe(true);
  });

  it("says so when the board cannot be opened, and tries again", async () => {
    let fail = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        fail ? new Response("{}", { status: 500 }) : new Response(JSON.stringify(sceneRead([])), { status: 200 }),
      ),
    );
    render(<WhiteboardEditor nodeId="b1" title="x" revision={null} />);
    await screen.findByTestId("whiteboard-load-failed");
    fail = false;
    fireEvent.click(screen.getByRole("button"));
    await screen.findByTestId("fake-excalidraw");
  });

  it("follows the app: theme, language, no AI, no web embeds, no theme switch, its own welcome", async () => {
    installServer({ scene: sceneRead([]) });
    // The app paints dark (outside a theme provider the class on <html> says so).
    document.documentElement.classList.add("dark");
    try {
      await openBoard();
    } finally {
      document.documentElement.classList.remove("dark");
    }
    const props = pkg.state.props!;
    expect(props.theme).toBe("dark");
    expect(props.langCode).toBe("en");
    expect(props.aiEnabled).toBe(false);
    expect((props.validateEmbeddable as (link: string) => boolean)("https://www.youtube.com/watch?v=x")).toBe(false);
    expect((props.UIOptions as { canvasActions: { toggleTheme: boolean } }).canvasActions.toggleTheme).toBe(false);
    expect(props.name).toBe("Launch plan");
    expect(screen.getByText("Draw, write and connect. This board saves itself.")).toBeTruthy();
    // The main menu is our own selection: no social links, no theme switch.
    const menu = document.querySelector('[data-part="main-menu"]')!;
    const items = [...menu.querySelectorAll("[data-part]")].map((node) => node.getAttribute("data-part"));
    expect(items).not.toContain("menu-Socials");
    expect(items).not.toContain("menu-ToggleTheme");
    expect(items).not.toContain("menu-LiveCollaborationTrigger");
    expect(items).toContain("menu-SaveAsImage");
  });

  it("saves a change after a short pause, and at once when the window hides", async () => {
    const fetchMock = installServer({ scene: sceneRead([el("a")]) });
    await openBoard();
    vi.useFakeTimers({ shouldAdvanceTime: true });

    change([{ ...el("a", 2) }]);
    expect(puts(fetchMock)).toHaveLength(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS + 50);
    });
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    const body = JSON.parse(String(puts(fetchMock)[0][1]?.body));
    expect(body.scene.format).toBe("scene");
    expect(body.scene.elements.map((e: BoardElement) => [e.id, e.version])).toEqual([["a", 2]]);
    await screen.findByText("Saved");

    change([{ ...el("a", 3) }]);
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(2));
  });

  it("saves what is waiting when the board is closed", async () => {
    const fetchMock = installServer({ scene: sceneRead([]) });
    const view = await openBoard();
    change([{ ...el("new") }]);
    view.unmount();
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
  });

  it("uploads a new picture before the save that names it", async () => {
    const fetchMock = installServer({ scene: sceneRead([]) });
    await openBoard();
    change([{ ...el("img", 1, { type: "image", fileId: "pic" }) }], {
      pic: { id: "pic", dataURL: "data:image/png;base64,iVBORw0KGgo=", mimeType: "image/png", created: 9 },
    });
    act(() => {
      window.dispatchEvent(new Event("blur"));
    });
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    const urls = fetchMock.mock.calls.map(([url, init]) => `${init?.method ?? "GET"} ${String(url)}`);
    expect(urls.indexOf("POST /api/nodes/b1/files")).toBeGreaterThan(-1);
    expect(urls.indexOf("POST /api/nodes/b1/files")).toBeLessThan(urls.indexOf("PUT /api/nodes/b1/scene"));
    const upload = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/nodes/b1/files" && init?.method === "POST");
    expect(JSON.parse(String(upload?.[1]?.body))).toEqual({ dataURL: "data:image/png;base64,iVBORw0KGgo=", id: "pic" });
    const body = JSON.parse(String(puts(fetchMock)[0][1]?.body));
    expect(body.scene.files).toEqual({ pic: { id: "pic", mimeType: "image/png", created: 9 } });
  });

  it("reconciles a merged answer into the editor, outside the undo history", async () => {
    const theirs = el("theirs", 1);
    installServer({
      scene: sceneRead([el("a")]),
      put: (body) => ({ version: 3, updated_at: 150, merged: true, scene: { format: "scene", elements: [...body.scene.elements, theirs], appState: {}, files: {} } }),
    });
    await openBoard();
    change([{ ...el("a", 2) }, { ...el("drawing", 1) }]);
    act(() => {
      window.dispatchEvent(new Event("blur"));
    });
    await waitFor(() => expect(pkg.state.api?.updateScene).toHaveBeenCalledTimes(1));
    const update = pkg.state.api!.updateScene.mock.calls[0][0] as { elements: Array<{ id: string }>; captureUpdate: string };
    expect(update.captureUpdate).toBe("NEVER");
    expect(update.elements.map((e) => e.id).sort()).toEqual(["a", "drawing", "theirs"]);
    // The server's elements were restored without the local ones.
    expect(pkg.restoreElements).toHaveBeenLastCalledWith(expect.any(Array), null, { refreshDimensions: true, repairBindings: true });
  });

  it("draws in a revision someone else made, keeping what the person is drawing", async () => {
    const server: Server = { scene: sceneRead([el("a")], 100) };
    installServer(server);
    const view = await openBoard({ revision: 100 });
    change([{ ...el("a") }, { ...el("mine", 1) }]);

    // The revision it opened at is not news.
    expect(pkg.state.api?.updateScene).not.toHaveBeenCalled();

    server.scene = sceneRead([el("a", 2), el("assistant", 1)], 200);
    view.rerender(<WhiteboardEditor nodeId="b1" title="Launch plan" revision={200} />);
    await waitFor(() => expect(pkg.state.api?.updateScene).toHaveBeenCalledTimes(1));
    const update = pkg.state.api!.updateScene.mock.calls[0][0] as { elements: Array<{ id: string; version: number }>; captureUpdate: string };
    expect(update.captureUpdate).toBe("NEVER");
    expect(update.elements.map((e) => e.id).sort()).toEqual(["a", "assistant", "mine"]);
    expect(update.elements.find((e) => e.id === "a")?.version).toBe(2);
  });

  it("keeps the canvas's keys away from the app's window shortcuts", async () => {
    installServer({ scene: sceneRead([]) });
    await openBoard();
    const onWindowKey = vi.fn();
    window.addEventListener("keydown", onWindowKey);
    try {
      fireEvent.keyDown(screen.getByTestId("fake-excalidraw"), { key: "Escape" });
      fireEvent.keyDown(screen.getByTestId("fake-excalidraw"), { key: "ArrowRight" });
      expect(onWindowKey).not.toHaveBeenCalled();
      // Outside the board the app's keys work as before.
      fireEvent.keyDown(document.body, { key: "Escape" });
      expect(onWindowKey).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener("keydown", onWindowKey);
    }
  });

  it("opens a web link from the board in the person's browser", async () => {
    installServer({ scene: sceneRead([]) });
    await openBoard();
    const event = new CustomEvent("excalidraw-link", { cancelable: true, detail: { nativeEvent: new MouseEvent("click") } });
    (pkg.state.props?.onLinkOpen as (element: unknown, event: CustomEvent) => void)({ link: "https://example.com/a" }, event);
    expect(event.defaultPrevented).toBe(true);
    expect(external.openExternalUrl).toHaveBeenCalledWith("https://example.com/a");
  });
});

describe("opening a board", () => {
  it("measures the texts again once their fonts are in, then fits the whole board in view", async () => {
    const load = vi.fn(async () => []);
    vi.stubGlobal("document", Object.assign(document, { fonts: { load } }));
    const elements: Array<Record<string, unknown>> = [
      { id: "box", type: "rectangle", version: 3, versionNonce: 7, isDeleted: false },
      { id: "label", type: "text", text: "Customer signs up", fontFamily: 5, version: 2, versionNonce: 9, isDeleted: false },
    ];
    const editor = {
      getSceneElements: vi.fn(() => elements),
      getSceneElementsIncludingDeleted: vi.fn(() => elements),
      updateScene: vi.fn(),
      scrollToContent: vi.fn(),
    };
    await settleBoard(editor as never, () => true);
    expect(load).toHaveBeenCalledWith('20px "Excalifont"', "Customer signs up");
    expect(editor.updateScene).toHaveBeenCalledWith(expect.objectContaining({ captureUpdate: "NEVER" }));
    expect(editor.scrollToContent).toHaveBeenCalledWith(undefined, { fitToContent: true, animate: false });
    vi.unstubAllGlobals();
  });

  it("leaves a board alone that was closed while its fonts loaded", async () => {
    const editor = {
      getSceneElements: vi.fn(() => [{ id: "t", type: "text", text: "x", fontFamily: 5 }]),
      getSceneElementsIncludingDeleted: vi.fn(() => []),
      updateScene: vi.fn(),
      scrollToContent: vi.fn(),
    };
    await settleBoard(editor as never, () => false);
    expect(editor.updateScene).not.toHaveBeenCalled();
    expect(editor.scrollToContent).not.toHaveBeenCalled();
  });
});
