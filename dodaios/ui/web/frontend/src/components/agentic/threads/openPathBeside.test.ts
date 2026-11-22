import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { forgetFileList } from "@/components/agentic/editor/fileListCache";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeExplorerStore } from "@/store/ideExplorer";
import { useSideFileStore } from "@/store/sideFile";
import { openPathBeside } from "./openPathBeside";

function answer(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const missing = () => answer({ detail: "That file is unavailable." }, 404);
const listing = (paths: string[]) => answer({ workspace_id: "w1", paths, truncated: false });
/** The paths asked for, in order; the project's file listing reads as "list". */
const asked = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.map(([url, init]) => (String(url).endsWith("/file-list")
    ? "list"
    : JSON.parse(String((init as RequestInit).body)).path as string));

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  forgetFileList("w1");
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
    expect(asked(fetchMock)).toEqual(["C:\\Repo\\Downloads\\demo\\clip.mp4", "list", "~/Downloads/demo/clip.mp4"]);
    // The File tab reads and names the real file, not one under the project.
    expect(useSideFileStore.getState().file?.path).toBe(found);
  });

  it("finds the project file an answer named from inside a package, and opens it at the named line", async () => {
    useIdeChatStore.setState({ workspace: { id: "w1", name: "Dodaios", path: "/Users/me/Dodaios" } });
    fetchMock
      .mockResolvedValueOnce(missing())
      .mockResolvedValueOnce(listing(["dodaios/core/config.py", "tests/unit/test_config.py"]))
      .mockResolvedValueOnce(answer({ workspace_id: "w1", path: "dodaios/core/config.py", kind: "file" }));
    await openPathBeside("core/config.py", "/Users/me/Dodaios", 3134);
    expect(asked(fetchMock)).toEqual(["/Users/me/Dodaios/core/config.py", "list", "/Users/me/Dodaios/dodaios/core/config.py"]);
    expect(useSideFileStore.getState().file).toEqual({
      path: "/Users/me/Dodaios/dodaios/core/config.py", folder: "/Users/me/Dodaios", diff: null, line: 3134,
    });
  });

  it("shows a project folder an answer named from inside a package in the Files tab", async () => {
    useIdeChatStore.setState({ workspace: { id: "w1", name: "Dodaios", path: "/Users/me/Dodaios" } });
    fetchMock
      .mockResolvedValueOnce(missing())
      .mockResolvedValueOnce(listing(["web/src/components/arcade/Arcade.tsx"]))
      .mockResolvedValueOnce(answer({ workspace_id: "w1", path: "web/src/components/arcade", kind: "directory" }));
    await openPathBeside("components/arcade/", "/Users/me/Dodaios");
    expect(asked(fetchMock)).toEqual(["/Users/me/Dodaios/components/arcade/", "list", "/Users/me/Dodaios/web/src/components/arcade"]);
    expect(useIdeExplorerStore.getState().revealed).toMatchObject({ workspaceId: "w1", path: "web/src/components/arcade" });
    expect(useSideFileStore.getState().file).toBeNull();
  });

  it("does not guess between two project files that both fit", async () => {
    useIdeChatStore.setState({ workspace: { id: "w1", name: "Dodaios", path: "/Users/me/Dodaios" } });
    fetchMock
      .mockResolvedValueOnce(missing())
      .mockResolvedValueOnce(listing(["a/memory.py", "b/memory.py"]))
      .mockResolvedValueOnce(missing());
    await openPathBeside("memory.py", "/Users/me/Dodaios");
    expect(asked(fetchMock)).toEqual(["/Users/me/Dodaios/memory.py", "list", "~/memory.py"]);
    expect(useSideFileStore.getState().file?.path).toBe("memory.py");
  });

  it("does not look in the home folder for a full path", async () => {
    fetchMock.mockResolvedValueOnce(missing());
    await openPathBeside("C:\\Elsewhere\\gone.txt", "C:\\Repo");
    expect(asked(fetchMock)).toEqual(["C:\\Elsewhere\\gone.txt"]);
    expect(useSideFileStore.getState().file?.path).toBe("C:\\Elsewhere\\gone.txt");
  });
});
