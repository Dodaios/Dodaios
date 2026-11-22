import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useIdeChatStore } from "@/store/ideChat";
import { useIdeExplorerStore } from "@/store/ideExplorer";
import { useSideFileStore } from "@/store/sideFile";
import { openPathBeside } from "./openPathBeside";

function answer(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const missing = () => answer({ detail: "That file is unavailable." }, 404);
/** The file search's answer: files, and folders as `path/`. */
const listing = (paths: string[]) => answer({
  trigger: "@", truncated: false,
  items: paths.map((value) => ({ value, label: value, hint: "", kind: value.endsWith("/") ? "folder" : "file", group: "" })),
});
/** The paths asked for, in order; a search in the thread's folder reads as "search <folder> <name>". */
const asked = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.map(([url, init]) => {
    if (!String(url).includes("/typeahead?")) return JSON.parse(String((init as RequestInit).body)).path as string;
    const query = new URL(String(url), "http://x").searchParams;
    return `search ${query.get("cwd")} ${query.get("q")}`;
  });

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  useSideFileStore.setState({ file: null, nonce: 0 });
  useIdeChatStore.setState({ workspace: { id: "w1", name: "Repo", path: "C:\\Repo" } });
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => { vi.unstubAllGlobals(); });

describe("a path an answer names", () => {
  it("opens from the thread's folder when it is there", async () => {
    fetchMock.mockResolvedValueOnce(answer({ workspace_id: "w1", path: "src/app.py", kind: "file" }));
    await openPathBeside("src\\app.py", "C:\\Repo");
    expect(asked(fetchMock)).toEqual(["C:\\Repo\\src\\app.py"]);
    expect(useSideFileStore.getState().file).toEqual({ path: "src\\app.py", folder: "C:\\Repo", diff: null });
  });

  it("is looked for in the home folder when the project does not have it, and shows where it was found", async () => {
    const found = "C:\\Users\\me\\Downloads\\demo\\clip.mp4";
    fetchMock
      .mockResolvedValueOnce(missing())
      .mockResolvedValueOnce(listing(["src/app.py"]))
      .mockResolvedValueOnce(answer({ workspace_id: "w1", path: found, kind: "file" }));
    await openPathBeside("Downloads\\demo\\clip.mp4", "C:\\Repo");
    expect(asked(fetchMock)).toEqual(["C:\\Repo\\Downloads\\demo\\clip.mp4", "search C:\\Repo clip.mp4", "~/Downloads/demo/clip.mp4"]);
    // The File tab reads and names the real file, not one under the project.
    expect(useSideFileStore.getState().file?.path).toBe(found);
  });

  it("finds the project file an answer named from inside a package, and opens it at the named line", async () => {
    // The open workspace is another project's: the search reads the thread's own folder.
    useIdeChatStore.setState({ workspace: { id: "w1", name: "Library", path: "/Users/me/Library" } });
    fetchMock
      .mockResolvedValueOnce(missing())
      .mockResolvedValueOnce(listing(["dodaios/core/config.py", "tests/unit/test_config.py"]))
      .mockResolvedValueOnce(answer({ workspace_id: "w1", path: "dodaios/core/config.py", kind: "file" }));
    await openPathBeside("core/config.py", "/Users/me/Dodaios", 3134);
    expect(asked(fetchMock)).toEqual(["/Users/me/Dodaios/core/config.py", "search /Users/me/Dodaios config.py", "/Users/me/Dodaios/dodaios/core/config.py"]);
    expect(useSideFileStore.getState().file).toEqual({
      path: "/Users/me/Dodaios/dodaios/core/config.py", folder: "/Users/me/Dodaios", diff: null, line: 3134,
    });
  });

  it("shows a project folder an answer named from inside a package in the Files tab", async () => {
    useIdeChatStore.setState({ workspace: { id: "w1", name: "Dodaios", path: "/Users/me/Dodaios" } });
    fetchMock
      .mockResolvedValueOnce(missing())
      .mockResolvedValueOnce(listing(["web/src/components/arcade/", "web/src/components/arcade/Arcade.tsx"]))
      .mockResolvedValueOnce(answer({ workspace_id: "w1", path: "web/src/components/arcade", kind: "directory" }));
    await openPathBeside("components/arcade/", "/Users/me/Dodaios");
    expect(asked(fetchMock)).toEqual(["/Users/me/Dodaios/components/arcade/", "search /Users/me/Dodaios arcade", "/Users/me/Dodaios/web/src/components/arcade"]);
    expect(useIdeExplorerStore.getState().revealed).toMatchObject({ workspaceId: "w1", path: "web/src/components/arcade" });
    expect(useSideFileStore.getState().file).toBeNull();
  });

  it("opens a project folder the open workspace has no tree for on the computer", async () => {
    // The open workspace is another project's, so its Files tab cannot show the folder.
    useIdeChatStore.setState({ workspace: { id: "w1", name: "web", path: "/Users/me/web" } });
    fetchMock
      .mockResolvedValueOnce(missing())
      .mockResolvedValueOnce(listing(["web/src/components/arcade/", "web/src/components/arcade/Arcade.tsx"]))
      .mockResolvedValueOnce(missing())
      .mockResolvedValueOnce(missing())
      .mockResolvedValueOnce(answer({ opened: true }));
    await openPathBeside("components/arcade/", "/Users/me/Dodaios");
    expect(asked(fetchMock)).toEqual([
      "/Users/me/Dodaios/components/arcade/", "search /Users/me/Dodaios arcade",
      "/Users/me/Dodaios/web/src/components/arcade", "~/components/arcade/", "/Users/me/Dodaios/web/src/components/arcade",
    ]);
    expect(String(fetchMock.mock.calls[4][0])).toBe("/api/settings/open-path");
    expect(useSideFileStore.getState().file).toBeNull();
  });

  it("does not guess between two project files that both fit", async () => {
    useIdeChatStore.setState({ workspace: { id: "w1", name: "Dodaios", path: "/Users/me/Dodaios" } });
    fetchMock
      .mockResolvedValueOnce(missing())
      .mockResolvedValueOnce(listing(["a/memory.py", "b/memory.py"]))
      .mockResolvedValueOnce(missing());
    await openPathBeside("memory.py", "/Users/me/Dodaios");
    expect(asked(fetchMock)).toEqual(["/Users/me/Dodaios/memory.py", "search /Users/me/Dodaios memory.py", "~/memory.py"]);
    expect(useSideFileStore.getState().file?.path).toBe("memory.py");
  });

  it("does not look in the home folder for a full path", async () => {
    fetchMock.mockResolvedValueOnce(missing());
    await openPathBeside("C:\\Elsewhere\\gone.txt", "C:\\Repo");
    expect(asked(fetchMock)).toEqual(["C:\\Elsewhere\\gone.txt"]);
    expect(useSideFileStore.getState().file?.path).toBe("C:\\Elsewhere\\gone.txt");
  });
});
