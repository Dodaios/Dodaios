import { describe, expect, it } from "vitest";
import { chatLinkAction, chatUrlTransform, nativePathFromMarkdownUrl, pageRefFromChatHref, pageRefFromMarkdownUrl } from "./chatLinks";

describe("chat file links", () => {
  it.each([
    ["C:/Users/me/Clip.mp4", "C:/Users/me/Clip.mp4"],
    ["C:\\Users\\me\\Clip.mp4", "C:\\Users\\me\\Clip.mp4"],
    ["file:///C:/Users/me/My%20Clip.mp4", "C:/Users/me/My Clip.mp4"],
    ["file://C:/Users/me/Clip.mp4", "C:/Users/me/Clip.mp4"],
    ["file://localhost/home/me/clip.mp4", "/home/me/clip.mp4"],
    ["~/Downloads/clip.mp4", "~/Downloads/clip.mp4"],
    ["/home/me/Videos/clip.mp4", "/home/me/Videos/clip.mp4"],
  ])("keeps %s as a local path", (raw, expected) => {
    expect(nativePathFromMarkdownUrl(raw)).toBe(expected);
    expect(chatUrlTransform(raw)).toBe("#jarvis-local=" + encodeURIComponent(expected));
  });

  it.each([
    "https://example.test/clip.mp4",
    "javascript:alert(1)",
    "  JavaScript:alert(1)",
    "VBScript:msgbox(1)",
    "data:text/html,<script>alert(1)</script>",
    "file://server/share/clip.mp4",
    "/api/outputs/run/files/clip.mp4/download",
  ])("does not treat %s as a local file", raw => {
    expect(nativePathFromMarkdownUrl(raw)).toBeNull();
  });

  it.each(["notes.md", "shot.png", "folder/clip.mp4"])("opens a linked filename %s", name => {
    expect(chatUrlTransform(name)).toBe("#jarvis-local=" + encodeURIComponent(name));
    expect(chatLinkAction(chatUrlTransform(name))).toEqual({ type: "local", path: name });
  });

  it("opens a preserved local path and still sends web links out", () => {
    const href = chatUrlTransform("C:/Users/me/Clip.mp4");
    expect(chatLinkAction(href)).toEqual({ type: "local", path: "C:/Users/me/Clip.mp4" });
    expect(chatLinkAction("https://example.test/clip.mp4")).toEqual({
      type: "external",
      url: "https://example.test/clip.mp4",
    });
  });

  it("uses the visible filename when the address itself was emptied", () => {
    expect(chatLinkAction("", "photo.png")).toEqual({ type: "local", path: "photo.png" });
    expect(chatLinkAction("")).toEqual({ type: "stay" });
    expect(chatLinkAction("javascript:alert(1)")).toEqual({ type: "stay" });
    expect(chatLinkAction("/api/outputs/run/download")).toEqual({ type: "allow" });
  });
});

describe("chat page links", () => {
  const PAGE = "20261113T104000__report__ab12::tasks/report/artifacts/files/plan-v1.html";

  it.each([
    [`artifact:${PAGE}`, PAGE],
    ["/api/outputs/run-1/files/tasks/t/artifacts/files/a%20b.html/page", "run-1::tasks/t/artifacts/files/a b.html"],
    ["/api/outputs/run-1/files/tasks/t/artifacts/files/a.html/page?theme=dark", "run-1::tasks/t/artifacts/files/a.html"],
    ["http://127.0.0.1:47821/api/outputs/run-1/files/x/notes.md/view", "run-1::x/notes.md"],
  ])("reads %s as a page in the Artifacts section", (raw, expected) => {
    expect(pageRefFromMarkdownUrl(raw)).toBe(expected);
    // The address survives the Markdown renderer and never loads in this window.
    const href = chatUrlTransform(raw);
    expect(href.startsWith("#jarvis-page=")).toBe(true);
    expect(pageRefFromChatHref(href)).toBe(expected);
  });

  it.each([
    "https://example.test/api/outputs/run-1/files/a.html/page",
    "/api/outputs/run-1/files/a.html/download?disposition=attachment",
    "artifact:no-separator",
    "artifact:run 1::a.html",
    "thread:ab12cd",
  ])("leaves %s alone", (raw) => {
    expect(pageRefFromMarkdownUrl(raw)).toBeNull();
    expect(pageRefFromChatHref(chatUrlTransform(raw))).toBeNull();
  });
});
