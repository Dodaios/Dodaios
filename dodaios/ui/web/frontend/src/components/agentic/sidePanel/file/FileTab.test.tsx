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
    // Long lines wrap in the panel instead of scrolling sideways.
    expect(screen.getByTestId("side-file-text").className).toContain("[&_pre]:whitespace-pre-wrap");
  });

  it("opens a clicked edit on its change, numbered like the Changes view, and switches to the file", async () => {
    fetchMock
      .mockResolvedValueOnce(answer({ workspace_id: "w1", path: "C:/demo/app.py", kind: "file" }))
      .mockResolvedValueOnce(answer(textFile("import os\nprint('new')\n")));
    act(() => useSideFileStore.getState().show({ path: "C:/demo/app.py", folder: "", diff }));
    render(<FileTab />);
    expect(screen.getByTestId("side-file-body").getAttribute("data-view")).toBe("change");
    // Once the file is read, the added line carries its number in the file.
    await waitFor(() => expect(screen.getByText("@@ -2,0 +2,1 @@")).toBeTruthy());
    const row = screen.getByText("print('new')").closest("[data-kind]");
    expect(row?.getAttribute("data-kind")).toBe("add");
    expect(row?.textContent).toContain("2");
    fireEvent.click(screen.getByRole("tab", { name: "File" }));
    expect(screen.getByTestId("side-file-body").getAttribute("data-view")).toBe("file");
  });

  it("says when the file cannot be read and still offers the change", async () => {
    fetchMock.mockResolvedValueOnce(answer({ detail: "That file is unavailable." }, 404));
    act(() => useSideFileStore.getState().show({ path: "C:/demo/gone.py", folder: "", diff }));
    render(<FileTab />);
    expect(screen.getByTestId("side-file-body").getAttribute("data-view")).toBe("change");
    fireEvent.click(screen.getByRole("tab", { name: "File" }));
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

describe("files the File tab shows as themselves", () => {
  it("plays a video from the granted path", async () => {
    fetchMock.mockResolvedValueOnce(answer({ workspace_id: "w1", path: "C:/Users/me/Downloads/demo.mp4", kind: "file" }));
    act(() => useSideFileStore.getState().show({ path: "C:\\Users\\me\\Downloads\\demo.mp4", folder: "", diff: null }));
    const { container } = render(<FileTab />);
    await waitFor(() => expect(container.querySelector("video")).toBeTruthy());
    expect(container.querySelector("video")?.getAttribute("src")).toContain("demo.mp4");
    // A video is never read as text.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("offers to open a file it cannot read on the computer", async () => {
    fetchMock
      .mockResolvedValueOnce(answer({ workspace_id: "w1", path: "C:/demo/setup.exe", kind: "file" }))
      .mockResolvedValueOnce(answer(textFile(null, { binary: true })))
      .mockResolvedValueOnce(answer({ opened: true }));
    act(() => useSideFileStore.getState().show({ path: "C:/demo/setup.exe", folder: "", diff: null }));
    render(<FileTab />);
    fireEvent.click(await screen.findByRole("button", { name: /open/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const [url, init] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(url).toBe("/api/settings/open-path");
    expect(JSON.parse(String(init.body))).toEqual({ path: "C:/demo/setup.exe" });
  });
});

describe("absoluteFilePath", () => {
  it("keeps an absolute path and joins a relative one to the thread's folder", () => {
    expect(absoluteFilePath("C:\\demo\\a.py", "C:\\Repo")).toBe("C:\\demo\\a.py");
    expect(absoluteFilePath("/home/me/a.py", "/repo")).toBe("/home/me/a.py");
    expect(absoluteFilePath("src/a.py", "C:\\Repo\\")).toBe("C:\\Repo\\src\\a.py");
    expect(absoluteFilePath("./src/a.py", "/home/me/repo")).toBe("/home/me/repo/src/a.py");
    expect(absoluteFilePath("a.py", "")).toBe("a.py");
    expect(absoluteFilePath("~/Downloads/a.md", "C:\\Repo")).toBe("~/Downloads/a.md");
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
