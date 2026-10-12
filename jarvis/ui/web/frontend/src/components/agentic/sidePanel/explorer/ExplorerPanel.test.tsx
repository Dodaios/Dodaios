import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { ExplorerPanel } from "./ExplorerPanel";
import { extractPaneDrop } from "@/components/agentic/paneDrop";
import { activateTerminalLink } from "@/lib/terminalLinks";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useCodeEditorStore } from "@/store/codeEditor";
import { parsePrintedPath, useExplorerPathRouting } from "@/store/ideExplorer";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";

const CHANGES = {
  workspace_id: "w1",
  available: true,
  branch: "main",
  truncated: false,
  reason: "",
  files: [
    {
      path: "src/app.ts",
      status: "modified",
      added: 3,
      removed: 1,
      is_directory: false,
      authors: [{ pane: "T2", history_id: "h2", agent: "codex", display_name: "Codex", last_edit_ms: 5 }],
    },
    { path: "old.md", status: "deleted", added: 0, removed: 4, is_directory: false },
  ],
};

const calls: { url: string; body: string }[] = [];

function respond(url: string): unknown {
  if (url.includes("/changes")) return CHANGES;
  if (url.includes("/text-file/version")) return { version: url.includes("src") ? null : "v1" };
  if (url.includes("/entries")) return { path: "src/new.ts", trashed: true };
  if (url.includes("/files")) {
    if (url.includes("?path=src")) {
      return { workspace_id: "w1", root_name: "app", path: "src", truncated: false, entries: [
        { name: "app.ts", path: "src/app.ts", is_directory: false, is_symlink: false },
      ] };
    }
    if (url.includes("?path=")) return { workspace_id: "w1", root_name: "app", path: "", truncated: false, entries: [] };
    return { workspace_id: "w1", root_name: "app", path: "", truncated: false, entries: [
      { name: "src", path: "src", is_directory: true, is_symlink: false },
      { name: "README.md", path: "README.md", is_directory: false, is_symlink: false },
    ] };
  }
  return {};
}

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: String(init?.body ?? "") });
    return new Response(JSON.stringify(respond(url)), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  useEventStore.setState({ activeSection: "agentic-ide" });
  useIdeChatStore.setState({ workspace: { id: "w1", name: "App", path: "/code/app" }, stagedPane: null });
  useCodeEditorStore.setState({ tabs: [], active: {}, files: {}, visible: false, reveal: null, closed: [] });
  useIdeSidePanelStore.setState({ open: false, tabs: ["agents", "changes", "files"], active: "agents" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ExplorerPanel", () => {
  it("lists what changed — deleted red, edited green — with line counts and the branch", async () => {
    render(<ExplorerPanel view="changes" />);
    const rows = await screen.findAllByTestId("explorer-change-row");
    expect(rows.map((row) => row.dataset.path)).toEqual(["src/app.ts", "old.md"]);
    expect(rows[0].textContent).toContain("+3");
    expect(rows[0].textContent).toContain("−1");
    expect(rows[0].querySelector("[data-status]")?.className).toContain("text-success");
    expect(rows[1].querySelector("[data-status]")?.className).toContain("text-destructive");
    expect(screen.getByTestId("explorer-branch").textContent).toBe("main");
  });

  it("names the coding agent that changed a file, and only where one is known", async () => {
    render(<ExplorerPanel view="changes" />);
    const rows = await screen.findAllByTestId("explorer-change-row");
    const authors = rows[0].querySelector('[data-testid="explorer-change-authors"]');
    expect(authors?.textContent).toContain("Codex");
    expect(authors?.getAttribute("title")).toContain("T2");
    expect(rows[1].querySelector('[data-testid="explorer-change-authors"]')).toBeNull();
    expect(screen.queryByRole("tablist")).toBeNull();
  });

  it("hands a terminal the absolute path when a row is dragged", async () => {
    render(<ExplorerPanel view="changes" />);
    const [row] = await screen.findAllByTestId("explorer-change-row");
    const data: Record<string, string> = {};
    const dataTransfer = {
      setData: (type: string, value: string) => { data[type] = value; },
      getData: (type: string) => data[type] ?? "",
      effectAllowed: "",
    };
    fireEvent.dragStart(row, { dataTransfer });
    expect(extractPaneDrop(dataTransfer as DataTransfer).paths).toEqual(["/code/app/src/app.ts"]);
  });

  it("opens a changed file as a diff tab in the code editor", async () => {
    render(<ExplorerPanel view="changes" />);
    const [row] = await screen.findAllByTestId("explorer-change-row");
    fireEvent.click(row);
    const { tabs, visible } = useCodeEditorStore.getState();
    expect(tabs).toMatchObject([{ path: "src/app.ts", mode: "diff", preview: true }]);
    expect(visible).toBe(true);
  });

  it("shows the folder as a lazy tree in the Folder tab", async () => {
    render(<ExplorerPanel view="files" />);
    await waitFor(() => expect(screen.getAllByTestId("explorer-tree-row")).toHaveLength(2));
    const rows = screen.getAllByTestId("explorer-tree-row");
    expect(rows.map((row) => row.dataset.path)).toEqual(["src", "README.md"]);
    // The folder holds a change, so it carries the marker while collapsed.
    await waitFor(() => expect(rows[0].querySelector(".bg-success\\/80")).not.toBeNull());
  });

  it("opens a file as a preview tab on click and keeps it on double click", async () => {
    render(<ExplorerPanel view="files" />);
    await waitFor(() => expect(screen.getAllByTestId("explorer-tree-row")).toHaveLength(2));
    const readme = screen.getAllByTestId("explorer-tree-row")[1];
    fireEvent.click(readme);
    expect(useCodeEditorStore.getState().tabs).toMatchObject([{ path: "README.md", mode: "edit", preview: true }]);
    fireEvent.doubleClick(readme);
    expect(useCodeEditorStore.getState().tabs).toMatchObject([{ path: "README.md", preview: false }]);
  });

  it("creates a new file from the header and opens it", async () => {
    render(<ExplorerPanel view="files" />);
    await waitFor(() => expect(screen.getAllByTestId("explorer-tree-row")).toHaveLength(2));
    fireEvent.click(screen.getByTestId("explorer-new-file"));
    const field = await screen.findByTestId("explorer-name-field");
    fireEvent.change(field, { target: { value: "src/new.ts" } });
    fireEvent.keyDown(field, { key: "Enter" });
    await waitFor(() => expect(useCodeEditorStore.getState().tabs).toMatchObject([{ path: "src/new.ts", preview: false }]));
    const create = calls.find((call) => call.url.endsWith("/entries"));
    expect(JSON.parse(create!.body)).toEqual({ path: "src/new.ts", kind: "file" });
  });

  it("creates a new entry in the selected folder, or beside the selected file", async () => {
    render(<ExplorerPanel view="files" />);
    await waitFor(() => expect(screen.getAllByTestId("explorer-tree-row")).toHaveLength(2));
    const row = (path: string) => screen.getAllByTestId("explorer-tree-row").find((entry) => entry.dataset.path === path)!;
    const createVia = async (button: string, name: string) => {
      fireEvent.click(screen.getByLabelText(button));
      const field = await screen.findByTestId("explorer-name-field");
      fireEvent.change(field, { target: { value: name } });
      fireEvent.keyDown(field, { key: "Enter" });
      await waitFor(() => expect(screen.queryByTestId("explorer-name-field")).toBeNull());
    };
    const sent = () => calls.filter((call) => call.url.endsWith("/entries")).map((call) => JSON.parse(call.body).path);

    fireEvent.click(row("src"));
    await waitFor(() => expect(row("src/app.ts")).toBeTruthy());
    await createVia("New file", "new.ts");
    fireEvent.click(row("src/app.ts"));
    await createVia("New folder", "lib");
    fireEvent.click(screen.getByTestId("explorer-tree"));
    await createVia("New file", "top.ts");

    await waitFor(() => expect(sent()).toEqual(["src/new.ts", "src/lib", "top.ts"]));
  });

  it("selects several rows with Ctrl+click and deletes them together", async () => {
    render(<ExplorerPanel view="files" />);
    await waitFor(() => expect(screen.getAllByTestId("explorer-tree-row")).toHaveLength(2));
    const [src, readme] = screen.getAllByTestId("explorer-tree-row");
    fireEvent.click(readme);
    fireEvent.click(src, { ctrlKey: true });
    expect(screen.getAllByTestId("explorer-tree-row").filter((row) => row.dataset.selected)).toHaveLength(2);

    fireEvent.keyDown(readme, { key: "Delete" });
    expect(screen.getByTestId("explorer-delete-dialog").textContent).toContain("2");
    fireEvent.click(screen.getByTestId("explorer-delete-confirm"));
    await waitFor(() => expect(calls.filter((call) => call.url.includes("/entries/delete"))).toHaveLength(2));
    const sent = calls.filter((call) => call.url.includes("/entries/delete")).map((call) => JSON.parse(call.body).path);
    expect(sent.sort()).toEqual(["README.md", "src"]);
  });

  it("copies with Ctrl+C and pastes into the selected folder with a free name", async () => {
    render(<ExplorerPanel view="files" />);
    await waitFor(() => expect(screen.getAllByTestId("explorer-tree-row")).toHaveLength(2));
    const [src, readme] = screen.getAllByTestId("explorer-tree-row");
    fireEvent.click(readme);
    fireEvent.keyDown(readme, { key: "c", ctrlKey: true });
    fireEvent.keyDown(src, { key: "v", ctrlKey: true });

    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/entries/copy"))).toBe(true));
    const sent = JSON.parse(calls.find((call) => call.url.endsWith("/entries/copy"))!.body);
    expect(sent).toEqual({ source: "README.md", destination: "src/README.md", unique: true });
  });

  it("moves a dragged row into the folder it is dropped on", async () => {
    render(<ExplorerPanel view="files" />);
    await waitFor(() => expect(screen.getAllByTestId("explorer-tree-row")).toHaveLength(2));
    const [src, readme] = screen.getAllByTestId("explorer-tree-row");
    const data: Record<string, string> = {};
    const dataTransfer = {
      setData: (type: string, value: string) => {
        data[type] = value;
      },
      getData: (type: string) => data[type] ?? "",
      get types() {
        return Object.keys(data);
      },
      effectAllowed: "",
      dropEffect: "",
    };
    fireEvent.dragStart(readme, { dataTransfer });
    fireEvent.dragOver(src, { dataTransfer });
    fireEvent.drop(src, { dataTransfer });

    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/entries/move"))).toBe(true));
    const sent = JSON.parse(calls.find((call) => call.url.endsWith("/entries/move"))!.body);
    expect(sent).toEqual({ source: "README.md", destination: "src/README.md" });
  });

  const openRowMenu = async (path: string) => {
    render(<ExplorerPanel view="files" />);
    await waitFor(() => expect(screen.getAllByTestId("explorer-tree-row")).toHaveLength(2));
    const row = screen.getAllByTestId("explorer-tree-row").find((entry) => entry.dataset.path === path)!;
    fireEvent.contextMenu(row, { clientX: 40, clientY: 60 });
    return { row, menu: await screen.findByTestId("explorer-menu") };
  };
  const item = (menu: HTMLElement, name: RegExp) =>
    [...menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((entry) => name.test(entry.textContent ?? ""));

  it("offers the folder actions on a right-click, with paste greyed out until something is copied", async () => {
    const { row, menu } = await openRowMenu("src");
    expect(row.dataset.selected).toBe("true");
    for (const name of [/New file/, /New folder/, /Open in terminal/, /Find in folder/, /Cut/, /Copy path/, /Copy relative path/, /Rename/, /Delete/]) {
      expect(item(menu, name), String(name)).toBeTruthy();
    }
    expect(item(menu, /Paste/)?.disabled).toBe(true);
    // Comparing is for files.
    expect(item(menu, /Select for compare/)).toBeUndefined();
  });

  it("shows an entry in the system file manager", async () => {
    const { menu } = await openRowMenu("README.md");
    fireEvent.click(item(menu, /Reveal in|Open containing folder/)!);
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("terminal-target/reveal"))).toBe(true));
    const sent = JSON.parse(calls.find((call) => call.url.endsWith("terminal-target/reveal"))!.body);
    expect(sent).toEqual({ workspace_id: "w1", target: "README.md" });
    expect(calls.some((call) => call.url.endsWith("terminal-target/open"))).toBe(false);
  });

  it("opens a terminal in the right-clicked folder", async () => {
    useIdeSidePanelStore.setState({ terminals: [] });
    const { menu } = await openRowMenu("src");
    fireEvent.click(item(menu, /Open in terminal/)!);
    expect(useIdeSidePanelStore.getState().terminals).toMatchObject([{ workspaceId: "w1", workspaceName: "src", folder: "/code/app/src" }]);
  });

  it("opens the Search tab for Find in folder", async () => {
    const { menu } = await openRowMenu("src");
    fireEvent.click(item(menu, /Find in folder/)!);
    expect(useIdeSidePanelStore.getState()).toMatchObject({ open: true, active: "search" });
  });

  it("compares a file with the one selected for compare", async () => {
    const { menu } = await openRowMenu("README.md");
    fireEvent.click(item(menu, /Select for compare/)!);
    fireEvent.click(screen.getAllByTestId("explorer-tree-row")[0]);
    await waitFor(() => expect(screen.getAllByTestId("explorer-tree-row")).toHaveLength(3));
    const other = screen.getAllByTestId("explorer-tree-row").find((entry) => entry.dataset.path === "src/app.ts")!;
    fireEvent.contextMenu(other, { clientX: 40, clientY: 90 });
    fireEvent.click(item(await screen.findByTestId("explorer-menu"), /Compare with README\.md/)!);
    const state = useCodeEditorStore.getState();
    expect(state.tabs).toMatchObject([{ path: "src/app.ts", mode: "diff", preview: false }]);
    expect(Object.values(state.diffBases)).toMatchObject([{ path: "README.md" }]);
  });

  it("copies the path with Shift+Alt+C and the relative path with Ctrl+K Ctrl+Shift+C", async () => {
    const written: string[] = [];
    vi.stubGlobal("navigator", { ...navigator, userAgent: navigator.userAgent, clipboard: { writeText: async (text: string) => void written.push(text) } });
    render(<ExplorerPanel view="files" />);
    await waitFor(() => expect(screen.getAllByTestId("explorer-tree-row")).toHaveLength(2));
    const readme = screen.getAllByTestId("explorer-tree-row")[1];
    fireEvent.keyDown(readme, { key: "C", code: "KeyC", shiftKey: true, altKey: true });
    fireEvent.keyDown(readme, { key: "k", code: "KeyK", ctrlKey: true });
    fireEvent.keyDown(readme, { key: "C", code: "KeyC", ctrlKey: true, shiftKey: true });
    expect(written).toEqual(["/code/app/README.md", "README.md"]);
  });

  it("asks before deleting and sends the file to the trash", async () => {
    render(<ExplorerPanel view="files" />);
    await waitFor(() => expect(screen.getAllByTestId("explorer-tree-row")).toHaveLength(2));
    fireEvent.keyDown(screen.getAllByTestId("explorer-tree-row")[1], { key: "Delete" });
    expect(calls.some((call) => call.url.includes("/entries/delete"))).toBe(false);
    fireEvent.click(await screen.findByTestId("explorer-delete-confirm"));
    await waitFor(() => expect(calls.some((call) => call.url.includes("/entries/delete"))).toBe(true));
    const sent = calls.find((call) => call.url.includes("/entries/delete"));
    expect(JSON.parse(sent!.body)).toEqual({ path: "README.md", permanent: false });
  });
});

describe("terminal path clicks", () => {
  it("open a printed file in the editor at its line", async () => {
    renderHook(() => useExplorerPathRouting());
    act(() =>
      activateTerminalLink(new MouseEvent("click", { button: 0, ctrlKey: true }), "README.md:12:3", { workspaceId: "w1" }),
    );
    await waitFor(() => expect(useCodeEditorStore.getState().tabs).toMatchObject([{ path: "README.md", preview: false }]));
    expect(useCodeEditorStore.getState().reveal).toMatchObject({ line: 12, column: 3 });
    expect(calls.some((call) => call.url.includes("terminal-target"))).toBe(false);
  });

  it("show a printed folder in the Folder tab", async () => {
    renderHook(() => useExplorerPathRouting());
    act(() => activateTerminalLink(new MouseEvent("click", { button: 0, ctrlKey: true }), "src/", { workspaceId: "w1" }));
    await waitFor(() => expect(useIdeSidePanelStore.getState()).toMatchObject({ open: true, active: "files" }));
    expect(useCodeEditorStore.getState().tabs).toEqual([]);
  });

  it("fall back to the OS for another workspace's pane", () => {
    renderHook(() => useExplorerPathRouting());
    activateTerminalLink(new MouseEvent("click", { button: 0, ctrlKey: true }), "src/app.ts", { workspaceId: "w9" });
    expect(useCodeEditorStore.getState().tabs).toEqual([]);
    expect(calls.some((call) => call.url.includes("terminal-target"))).toBe(true);
  });
});

describe("parsePrintedPath", () => {
  it("reads line suffixes, absolute paths and file URIs", () => {
    expect(parsePrintedPath("/code/app", "src/a.ts:4:2")).toEqual({ path: "src/a.ts", line: 4, column: 2 });
    expect(parsePrintedPath("/code/app", "src/a.ts(7,1)")).toEqual({ path: "src/a.ts", line: 7, column: 1 });
    expect(parsePrintedPath("/code/app", "/code/app/src/a.ts#L9")).toEqual({ path: "src/a.ts", line: 9, column: undefined });
    expect(parsePrintedPath("C:\\Code\\App", "c:\\code\\app\\x.py:3")).toEqual({ path: "x.py", line: 3, column: undefined });
    expect(parsePrintedPath("/code/app", "file:///code/app/b.md")).toMatchObject({ path: "b.md" });
  });

  it("refuses paths outside the workspace", () => {
    expect(parsePrintedPath("/code/app", "/etc/passwd").path).toBeNull();
    expect(parsePrintedPath("/code/app", "../secret.txt").path).toBeNull();
    expect(parsePrintedPath("/code/app", "/code/application/x").path).toBeNull();
  });
});
