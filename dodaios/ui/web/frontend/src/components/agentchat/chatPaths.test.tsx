import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatMarkdown } from "./ChatMarkdown";
import { ChatFileIcon, ChatPathOpener, fileRefInCode, pathInCode } from "./chatPaths";

afterEach(cleanup);

describe("pathInCode", () => {
  it.each([
    ["todo.md", "todo.md"],
    ["package.json", "package.json"],
    [".env", ".env"],
    ["src/app.ts:42", "src/app.ts"],
    ["src/app.ts:42:7", "src/app.ts"],
    ["src/app.ts:42-64", "src/app.ts"],
    ["src/app.ts#L42C7", "src/app.ts"],
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

describe("fileRefInCode", () => {
  it.each([
    ["src/app.ts", { path: "src/app.ts" }],
    ["memory/vault/legacy_import.py:321", { path: "memory/vault/legacy_import.py", line: 321 }],
    ["src/app.ts:42:7", { path: "src/app.ts", line: 42, column: 7 }],
    ["src/app.ts:42-64", { path: "src/app.ts", line: 42, endLine: 64 }],
    ["docs/ci.md#L12-L20", { path: "docs/ci.md", line: 12, endLine: 20 }],
    ["docs/ci.md#L12C3", { path: "docs/ci.md", line: 12, column: 3 }],
    ["main.c(7,2)", { path: "main.c", line: 7, column: 2 }],
  ])("reads %s with its place in the file", (code, ref) => {
    expect(fileRefInCode(code)).toEqual(ref);
  });

  it("is null for code", () => {
    expect(fileRefInCode("localhost:8080")).toBeNull();
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

  it("draws a path as a file reference: glyph, name and line, never as code", () => {
    const open = vi.fn();
    const Glyph = ({ path }: { path: string }) => <svg data-testid="glyph" data-path={path} />;
    render(<ChatPathOpener.Provider value={open}><ChatFileIcon.Provider value={Glyph}>
      <ChatMarkdown text={"See `core/config.py:3134` and `wiki/obsidian-vault/`."} />
    </ChatFileIcon.Provider></ChatPathOpener.Provider>);
    const [file, folder] = screen.getAllByTestId("chat-path-link");
    expect(file.textContent).toBe("config.py · L3134");
    expect(file.querySelector("code")).toBeNull();
    expect(file.dataset.fileRef).toBe("file");
    expect(screen.getByTestId("glyph").dataset.path).toBe("core/config.py");
    // A folder wears the folder glyph and its own name.
    expect(folder.textContent).toBe("obsidian-vault");
    expect(folder.dataset.fileRef).toBe("folder");
    fireEvent.click(file);
    expect(open).toHaveBeenCalledWith("core/config.py", 3134);
  });

  it("tells two files of the same name apart by their folders", () => {
    render(<ChatPathOpener.Provider value={vi.fn()}>
      <ChatMarkdown text={"`society/memory.py:3` differs from `core/memory.py`; `state.py` is alone."} />
    </ChatPathOpener.Provider>);
    expect(screen.getAllByTestId("chat-path-link").map((link) => link.textContent))
      .toEqual(["memory.py · society · L3", "memory.py · core", "state.py"]);
  });

  it("draws a link worded as its file as a reference, at the linked line", () => {
    const open = vi.fn();
    render(<ChatPathOpener.Provider value={open}>
      <ChatMarkdown text={"In [app.ts:42](src/app.ts#L42), see [the notes](<C:/Users/me/notes.md>)."} />
    </ChatPathOpener.Provider>);
    const [reference] = screen.getAllByTestId("chat-path-link");
    expect(reference.textContent).toBe("app.ts · L42");
    fireEvent.click(reference);
    expect(open).toHaveBeenCalledWith("src/app.ts", 42);
    // A link worded as prose stays a link.
    expect(screen.getByText("the notes").closest("[data-testid=chat-path-link]")).toBeNull();
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
