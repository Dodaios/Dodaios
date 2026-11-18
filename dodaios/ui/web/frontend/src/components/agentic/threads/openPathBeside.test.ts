import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useIdeChatStore } from "@/store/ideChat";
import { useSideFileStore } from "@/store/sideFile";
import { openPathBeside } from "./openPathBeside";

function answer(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const missing = () => answer({ detail: "That file is unavailable." }, 404);
const asked = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.map(([, init]) => JSON.parse(String((init as RequestInit).body)).path as string);

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
      .mockResolvedValueOnce(answer({ workspace_id: "w1", path: found, kind: "file" }));
    await openPathBeside("Downloads\\demo\\clip.mp4", "C:\\Repo");
    expect(asked(fetchMock)).toEqual(["C:\\Repo\\Downloads\\demo\\clip.mp4", "~/Downloads/demo/clip.mp4"]);
    // The File tab reads and names the real file, not one under the project.
    expect(useSideFileStore.getState().file?.path).toBe(found);
  });

  it("does not look in the home folder for a full path", async () => {
    fetchMock.mockResolvedValueOnce(missing());
    await openPathBeside("C:\\Elsewhere\\gone.txt", "C:\\Repo");
    expect(asked(fetchMock)).toEqual(["C:\\Elsewhere\\gone.txt"]);
    expect(useSideFileStore.getState().file?.path).toBe("C:\\Elsewhere\\gone.txt");
  });
});
