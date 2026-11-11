import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DiffFile } from "@/components/agentchat/toolDiff";
import { useIdeChatStore } from "@/store/ideChat";
import { absoluteFilePath, useSideFileStore } from "@/store/sideFile";
import { FileTab, fileLanguage } from "./FileTab";

const diff: DiffFile[] = [{
  path: "C:/demo/app.py", added: 1, removed: 0, created: false, truncated: 0,
  lines: [{ kind: "add", text: "print('new')" }],
}];

function answer(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const textFile = (text: string | null, over: Record<string, unknown> = {}) => ({
  workspace_id: "w1", path: "C:/demo/app.py", text, version: "v1", size: 10,
  encoding: "utf-8", eol: "\n", binary: false, too_large: false, ...over,
});

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  useSideFileStore.setState({ file: null, nonce: 0 });
  useIdeChatStore.setState({ workspace: { id: "w1", name: "Repo", path: "C:/Repo" } });
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the side panel's File tab", () => {
  it("asks for a click while no file is picked", () => {
    render(<FileTab />);
    expect(screen.getByText("Click a file in a thread's work to read it here.")).toBeTruthy();
  });

  it("grants the clicked file and shows its text", async () => {
    fetchMock
      .mockResolvedValueOnce(answer({ workspace_id: "w1", path: "C:/demo/app.py", kind: "file" }))
      .mockResolvedValueOnce(answer(textFile("print('hello')\n")));
    act(() => useSideFileStore.getState().show({ path: "app.py", folder: "C:\\demo", diff: null }));
    render(<FileTab />);
    await waitFor(() => expect(screen.getByText(/print\('hello'\)/)).toBeTruthy());
    expect(screen.getByTestId("side-file-name").textContent).toBe("app.py");
    // The relative path is read from the thread's folder.
    const [grantUrl, grantInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(grantUrl).toBe("/api/agentic-ide/workspaces/w1/outside-files");
    expect(JSON.parse(String(grantInit.body))).toEqual({ path: "C:\\demo\\app.py" });
    expect(String(fetchMock.mock.calls[1][0])).toContain("/text-file?path=C%3A%2Fdemo%2Fapp.py");
    // Without a change from the click there is nothing to switch to.
    expect(screen.queryByRole("tab")).toBeNull();
  });

  it("switches between the file and the change the click came from", async () => {
    fetchMock
      .mockResolvedValueOnce(answer({ workspace_id: "w1", path: "C:/demo/app.py", kind: "file" }))
      .mockResolvedValueOnce(answer(textFile("print('new')\n")));
    act(() => useSideFileStore.getState().show({ path: "C:/demo/app.py", folder: "", diff }));
    render(<FileTab />);
    await waitFor(() => expect(screen.getByTestId("side-file-body").getAttribute("data-view")).toBe("file"));
    fireEvent.click(screen.getByRole("tab", { name: "Change" }));
    expect(screen.getByTestId("side-file-body").getAttribute("data-view")).toBe("change");
    expect(screen.getByText("print('new')")).toBeTruthy();
  });

  it("says when the file cannot be read and still offers the change", async () => {
    fetchMock.mockResolvedValueOnce(answer({ detail: "That file is unavailable." }, 404));
    act(() => useSideFileStore.getState().show({ path: "C:/demo/gone.py", folder: "", diff }));
    render(<FileTab />);
    await waitFor(() => expect(screen.getByText(/This file cannot be read/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Show the change" }));
    expect(screen.getByTestId("side-file-body").getAttribute("data-view")).toBe("change");
  });

  it("names a binary file instead of drawing it", async () => {
    fetchMock
      .mockResolvedValueOnce(answer({ workspace_id: "w1", path: "C:/demo/a.bin", kind: "file" }))
      .mockResolvedValueOnce(answer(textFile(null, { binary: true })));
    act(() => useSideFileStore.getState().show({ path: "C:/demo/a.bin", folder: "", diff: null }));
    render(<FileTab />);
    await waitFor(() => expect(screen.getByText(/This file is not text/)).toBeTruthy());
  });
});

describe("absoluteFilePath", () => {
  it("keeps an absolute path and joins a relative one to the thread's folder", () => {
    expect(absoluteFilePath("C:\\demo\\a.py", "C:\\Repo")).toBe("C:\\demo\\a.py");
    expect(absoluteFilePath("/home/me/a.py", "/repo")).toBe("/home/me/a.py");
    expect(absoluteFilePath("src/a.py", "C:\\Repo\\")).toBe("C:\\Repo\\src\\a.py");
    expect(absoluteFilePath("./src/a.py", "/home/me/repo")).toBe("/home/me/repo/src/a.py");
    expect(absoluteFilePath("a.py", "")).toBe("a.py");
  });
});

describe("fileLanguage", () => {
  it("reads the highlighter's language from the file name", () => {
    expect(fileLanguage("C:/x/app.PY")).toBe("python");
    expect(fileLanguage("src/view.tsx")).toBe("tsx");
    expect(fileLanguage("Makefile")).toBe("");
    expect(fileLanguage(".env")).toBe("");
  });
});
