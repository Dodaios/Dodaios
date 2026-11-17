import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatMarkdown } from "./ChatMarkdown";
import { ChatPathOpener, pathInCode } from "./chatPaths";

afterEach(cleanup);

describe("pathInCode", () => {
  it.each([
    ["todo.md", "todo.md"],
    ["package.json", "package.json"],
    [".env", ".env"],
    ["src/app.ts:42", "src/app.ts"],
    ["src/app.ts:42:7", "src/app.ts"],
    ["docs/ci-pipeline.md#L12", "docs/ci-pipeline.md"],
    ["./scripts/run.py", "./scripts/run.py"],
    ["src/components/", "src/components/"],
    ["C:\\Users\\me\\Downloads\\Dodaios Demo.mp4", "C:\\Users\\me\\Downloads\\Dodaios Demo.mp4"],
    ["C:/Users/me/Desktop", "C:/Users/me/Desktop"],
    ["~/Downloads/notes.txt", "~/Downloads/notes.txt"],
    ["/home/me/repo", "/home/me/repo"],
    ["/srv/app/main.py:3", "/srv/app/main.py"],
  ])("reads %s as a path", (code, path) => {
    expect(pathInCode(code)).toBe(path);
  });

  it.each([
    "nvidia-smi", "item.text", "useSideFileStore.getState", "v4.2.3", "example.com", "fix/bar-crisp-edges",
    "release/v4.2.3", "/api/settings/open-path", "/compact", "@/lib/utils", "https://example.com/a.md",
    "npm run build", "foo(bar.ts)", "localhost:8080", "", "a.md\nb.md",
  ])("leaves %s as code", (code) => {
    expect(pathInCode(code)).toBeNull();
  });
});

describe("paths in a thread's answer", () => {
  it("opens a path in code beside the conversation", () => {
    const open = vi.fn();
    render(<ChatPathOpener.Provider value={open}>
      <ChatMarkdown text={"Saved `todo.md`; ran `nvidia-smi`."} />
    </ChatPathOpener.Provider>);
    const links = screen.getAllByTestId("chat-path-link");
    expect(links.map((link) => link.textContent)).toEqual(["todo.md"]);
    fireEvent.click(links[0]);
    expect(open).toHaveBeenCalledWith("todo.md");
  });

  it("opens a linked local file beside the conversation instead of on the computer", () => {
    const open = vi.fn();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatPathOpener.Provider value={open}>
      <ChatMarkdown text={"See [the notes](<C:/Users/me/notes.md>)."} />
    </ChatPathOpener.Provider>);
    fireEvent.click(screen.getByText("the notes"));
    expect(open).toHaveBeenCalledWith("C:/Users/me/notes.md");
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("leaves code plain where nothing opens paths (the Dodaios chat)", () => {
    render(<ChatMarkdown text={"Saved `todo.md`."} />);
    expect(screen.queryByTestId("chat-path-link")).toBeNull();
    expect(screen.getByText("todo.md").tagName).toBe("CODE");
  });

  it("keeps a fenced block a code block", () => {
    const open = vi.fn();
    render(<ChatPathOpener.Provider value={open}>
      <ChatMarkdown text={"```\ntodo.md\n```"} />
    </ChatPathOpener.Provider>);
    expect(screen.queryByTestId("chat-path-link")).toBeNull();
  });
});
