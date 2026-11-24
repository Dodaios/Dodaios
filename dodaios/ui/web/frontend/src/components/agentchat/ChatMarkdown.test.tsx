import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatMarkdown, mediaKind, normalizeMediaMarkup, safeMediaUrl } from "./ChatMarkdown";
import { isRemoteMedia, PictureDisplayContext } from "./MediaPreview";

// The diagram library needs a real layout engine; what it is asked to draw is checked here.
const renderMermaid = vi.hoisted(() => vi.fn());
vi.mock("@/lib/mermaidRender", () => ({ renderMermaid }));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  renderMermaid.mockReset();
});

describe("chat visual fences", () => {
  it.each(["HTML", "htm", "text/html"])("previews %s instead of leaving source", async language => {
    render(<ChatMarkdown text={`\`\`\`${language}\n<div>Visual card</div>\n\`\`\``} />);
    expect((await screen.findByTestId("inline-html-frame")).getAttribute("srcdoc")).toContain("Visual card");
  });

  it.each(["SVG", "xml", "image/svg+xml", ""])("previews SVG with the %s label", async language => {
    render(<ChatMarkdown text={`\`\`\`${language}\n<svg width="80" height="40"><rect width="80" height="40"/></svg>\n\`\`\``} />);
    const frame = await screen.findByTestId("inline-html-frame");
    // Drawn in the sandboxed frame, and able to scale down to the conversation's width.
    expect(frame.getAttribute("srcdoc")).toContain('<svg viewBox="0 0 80 40" width="80" height="40">');
    expect((await screen.findByTestId("rendered-fence")).getAttribute("data-language")).toBe("svg");
  });

  it.each(["~~~", "````", "```"])("preserves HTML media during streaming in %s fences", async marker => {
    const code = '<div><img src="https://example.test/chart.png"></div>';
    const text = `${marker}html\n${code}\n`;
    expect(normalizeMediaMarkup(text)).toBe(text);
    expect(normalizeMediaMarkup(text + marker)).toBe(text + marker);
    const { rerender } = render(<ChatMarkdown text={text} />);
    // Still being written: its place is held, no half-drawn markup and no code.
    expect(await screen.findByTestId("rendered-fence-pending")).toBeTruthy();
    expect(screen.queryByTestId("inline-html-frame")).toBeNull();
    expect(screen.queryByText(/chart\.png/)).toBeNull();
    rerender(<ChatMarkdown text={text + marker} />);
    expect((await screen.findByTestId("inline-html-frame")).getAttribute("srcdoc")).toContain(code);
    expect(screen.queryByTestId("rendered-fence-pending")).toBeNull();
  });

  it("holds only the block that is still being written", async () => {
    const done = "```svg\n<svg viewBox=\"0 0 4 4\"><title>Done</title></svg>\n```";
    render(<ChatMarkdown text={`${done}\n\nNext:\n\n\`\`\`html\n<div>half`} />);
    expect(await screen.findByTestId("rendered-fence-pending")).toBeTruthy();
    expect((await screen.findAllByTestId("rendered-fence")).map(fence => fence.getAttribute("data-language"))).toEqual(["svg"]);
  });

  it("draws a block the answer never closed once it stands still", async () => {
    vi.useFakeTimers();
    render(<ChatMarkdown text={"```html\n<div>Never closed</div>"} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.queryByTestId("inline-html-frame")).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    vi.useRealTimers();
    expect((await screen.findByTestId("inline-html-frame")).getAttribute("srcdoc")).toContain("Never closed");
  });

  it("draws a mermaid block as a diagram, with its text behind Source", async () => {
    renderMermaid.mockResolvedValue('<svg viewBox="0 0 10 10" id="diagram"><g/></svg>');
    render(<ChatMarkdown text={"```mermaid\nflowchart LR\n  A --> B\n```"} />);
    const frame = await screen.findByTestId("inline-html-frame");
    expect(renderMermaid.mock.calls[0][0]).toBe("flowchart LR\n  A --> B");
    expect(frame.getAttribute("srcdoc")).toContain('id="diagram"');
    // Drawn in the app's own colours, so it sits on the conversation's surface.
    expect(frame.getAttribute("data-look")).toBe("themed");
    const fence = screen.getByTestId("rendered-fence");
    expect(fence.getAttribute("data-language")).toBe("mermaid");
    fireEvent.click(within(fence).getByRole("button", { name: "Source" }));
    expect(within(fence).getByText(/A --> B/)).toBeTruthy();
  });

  it("leaves a mermaid block that is no diagram as the code it is", async () => {
    renderMermaid.mockRejectedValue(new Error("Parse error"));
    render(<ChatMarkdown text={"```mermaid\nnot a diagram\n```"} />);
    expect(await screen.findByText("not a diagram")).toBeTruthy();
    expect(screen.queryByTestId("rendered-fence")).toBeNull();
  });

  it("gives fenced code its language and a copy button", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<ChatMarkdown text={["Here:", "", "```python", "print('hi')", "```"].join("\n")} />);

    expect(screen.getByText("python")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy code" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("print('hi')"));
    expect(await screen.findByRole("button", { name: "Code copied" })).toBeTruthy();
  });

  it("keeps JSON results and explicit text as code", () => {
    const { container } = render(<ChatMarkdown text={'```json\n{"ok":true,"artifacts":[]}\n```\n\n```text\n<svg><rect/></svg>\n```'} />);
    expect(container.querySelectorAll("pre")).toHaveLength(2);
    expect(screen.queryByTestId("rendered-fence")).toBeNull();
  });
});

describe("shared chat media", () => {
  it("renders every image and video in a mixed response", () => {
    const { container } = render(<ChatMarkdown text={'![First](/api/media/a.png)\n\n![Second](/api/media/b.webp)\n\n[Clip](/api/media/video.mp4)\n\n[Audio](/api/media/audio.mp3)'} />);
    expect(screen.getAllByRole("img")).toHaveLength(2);
    const video = container.querySelector("video")!;
    expect(video.getAttribute("src")).toBe("/api/media/video.mp4");
    expect(video.hasAttribute("controls")).toBe(true);
    expect(video.hasAttribute("autoplay")).toBe(false);
    expect(video.getAttribute("preload")).toBe("metadata");
    expect(container.querySelector("audio")?.hasAttribute("controls")).toBe(true);
  });

  it.each(["mp4", "webm", "mov", "ogv"])("renders archived %s receipts with video controls", extension => {
    const url = `/api/outputs/run/files/tasks/chat/artifacts/files/clip.${extension}/download?disposition=inline`;
    render(<ChatMarkdown text={`[Clip](<${url}>)`} />);
    expect(screen.getByLabelText("Clip").tagName).toBe("VIDEO");
    expect(screen.getByLabelText("Clip").getAttribute("src")).toBe(url);
  });

  it("honors an extensionless video URL without altering its signed query", () => {
    const url = "/api/media/object?signature=a%2Bb#jarvis-media=video%2Fmp4";
    render(<ChatMarkdown text={`[Video](<${url}>)`} />);
    expect(screen.getByLabelText("Video").getAttribute("src")).toBe(url);
  });

  it("renders a video even when a provider used Markdown image syntax", () => {
    const { container } = render(<ChatMarkdown text="![Movie](/api/media/movie.webm)" />);
    expect(container.querySelector("video")).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
  });

  it("keeps a download link without duplicating an image preview", () => {
    const base = "/api/outputs/run/files/tasks/chat/artifacts/files/photo.png/download";
    render(<ChatMarkdown text={`![Photo](${base}?disposition=inline)\n\n[Download](${base})`} />);
    expect(screen.getAllByRole("img")).toHaveLength(1);
    expect(screen.getByRole("link", {name:"Download"})).toBeTruthy();
  });

  it("opens images in an accessible viewer", () => {
    render(<ChatMarkdown text="![Photo](/api/media/photo.png)" />);
    fireEvent.click(screen.getByRole("button", {name:"Enlarge Photo"}));
    expect(within(screen.getByRole("dialog")).getByRole("img").getAttribute("src")).toBe("/api/media/photo.png");
  });

  it("lists a picture as its download link where the transcript lists files, and still plays a video", () => {
    const base = "/api/outputs/run/files/tasks/chat/artifacts/files/photo.png/download";
    const { container } = render(
      <PictureDisplayContext.Provider value="files">
        <ChatMarkdown text={`![Photo](${base})\n\n[Clip](/api/media/video.mp4)`} />
      </PictureDisplayContext.Provider>,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("link", { name: /Photo/ }).getAttribute("href")).toBe(base);
    expect(container.querySelector("video")).not.toBeNull();
  });

  it("shows an explicit error and retains access to a failed video", () => {
    render(<ChatMarkdown text="[Clip](/api/media/clip.mp4)" />);
    fireEvent.error(screen.getByLabelText("Clip"));
    expect(screen.getByRole("status").textContent).toContain("cannot be loaded or played");
    expect(screen.getByRole("link", {name:/Open file/}).getAttribute("href")).toBe("/api/media/clip.mp4");
  });

  it("retries a changed source without retaining the previous error", () => {
    const {rerender} = render(<ChatMarkdown text="![Photo](/api/media/old.png)" />);
    fireEvent.error(screen.getByRole("img"));
    rerender(<ChatMarkdown text="![Photo](/api/media/new.png)" />);
    expect(screen.getByRole("img").getAttribute("src")).toBe("/api/media/new.png");
  });

  it("preserves playback when streamed text and another image arrive", () => {
    const text = "[Clip](/api/media/clip.mp4)";
    const {rerender} = render(<ChatMarkdown text={text} />);
    (screen.getByLabelText("Clip") as HTMLVideoElement).currentTime = 1.25;
    rerender(<ChatMarkdown text={text + "\n\nMore text.\n\n![Photo](/api/media/photo.png)"} />);
    expect((screen.getByLabelText("Clip") as HTMLVideoElement).currentTime).toBe(1.25);
  });

  it("retries without changing a signed media URL", () => {
    const url = "/api/media/clip.mp4?signature=abc";
    render(<ChatMarkdown text={`[Clip](${url})`} />);
    fireEvent.error(screen.getByLabelText("Clip"));
    fireEvent.click(screen.getByRole("button", {name:"Retry"}));
    expect(screen.getByLabelText("Clip").getAttribute("src")).toBe(url);
  });

  it("recognizes safe HTML media tags without running their handlers", () => {
    const {container} = render(<ChatMarkdown text={'<video controls><source src="/api/media/clip.mp4" type="video/mp4"></video>\n\n<img src="/api/media/photo.png" onerror="alert(1)" alt="Photo">'} />);
    expect(container.querySelector("video")).toBeTruthy();
    expect(screen.getByRole("img").hasAttribute("onerror")).toBe(false);
    expect(container.querySelector("script")).toBeNull();
  });

  it("loads nothing from a remote address: a picture, a video and a sound are links that open in the browser", () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ opened: true }) }));
    vi.stubGlobal("fetch", fetchMock);
    const picture = "https://example.test/a.png?d=c2VjcmV0";
    const { container } = render(<ChatMarkdown text={[
      `![Chart](${picture})`,
      "![Movie](https://example.test/movie.webm)",
      "[Clip](https://example.test/video.mp4)",
      "[Audio](https://example.test/audio.mp3)",
      '<video controls><source src="https://example.test/tag.mp4" type="video/mp4"></video>',
      '<img src="https://example.test/tag.png" alt="Tag">',
    ].join("\n\n")} />);
    // No element that would fetch: the answer was drawn and no host was asked.
    expect(container.querySelector("img, video, audio, source, iframe")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    const media = screen.getAllByTestId("chat-media");
    expect(media).toHaveLength(6);
    for (const item of media) expect(item.getAttribute("data-remote")).toBe("true");
    // The link says where it leads before the click, and opens it outside the window.
    const link = screen.getByRole("link", { name: /Chart/ });
    expect(link.getAttribute("title")).toBe(picture);
    expect(link.hasAttribute("download")).toBe(false);
    fireEvent.click(link);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/settings/open-external", expect.objectContaining({
      body: JSON.stringify({ url: picture }),
    }));
    vi.unstubAllGlobals();
  });

  it.each([
    "//example.test/a.png",
    "http://example.test/a.png",
    "HTTPS://EXAMPLE.TEST/a.png",
  ])("treats %s as remote however it is written", url => {
    const { container } = render(<ChatMarkdown text={`![Chart](<${url}>)`} />);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByTestId("chat-media").getAttribute("data-remote")).toBe("true");
  });

  it("tells what the app serves from what another host serves", () => {
    for (const own of ["/api/media/a.png", "/api/outputs/run/files/a.png/download", `${window.location.origin}/api/media/a.png`, "data:image/png;base64,AAAA"]) {
      expect(isRemoteMedia(own), own).toBe(false);
    }
    // A leading slash is not enough: these begin like a path of the app and lead to another host.
    for (const other of ["https://example.test/a.png", "//example.test/a.png", "/\\example.test/a.png", "\\\\example.test\\a.png", "http://localhost.example.test/a.png", "http://[bad"]) {
      expect(isRemoteMedia(other), other).toBe(true);
    }
  });

  it("still draws a picture inside the text itself and one the app serves", () => {
    const pixel = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";
    render(<ChatMarkdown text={`![Inline](${pixel})\n\n![Stored](/api/media/photo.png)`} />);
    expect(screen.getAllByRole("img").map(image => image.getAttribute("src"))).toEqual([pixel, "/api/media/photo.png"]);
  });

  it("lists a remote video as a link where the transcript lists files too", () => {
    const { container } = render(
      <PictureDisplayContext.Provider value="files">
        <ChatMarkdown text={"[Clip](https://example.test/video.mp4)\n\n![Photo](https://example.test/photo.png)"} />
      </PictureDisplayContext.Provider>,
    );
    expect(container.querySelector("img, video")).toBeNull();
    expect(screen.getByRole("link", { name: /Clip/ }).getAttribute("href")).toBe("https://example.test/video.mp4");
    expect(screen.getByRole("link", { name: /Photo/ }).getAttribute("href")).toBe("https://example.test/photo.png");
  });

  it("does not turn HTML code examples into media tags", () => {
    const text = '```text\n<video src="https://example.test/clip.mp4"></video>\n```';
    expect(normalizeMediaMarkup(text)).toBe(text);
  });

  it.each(["javascript:alert(1)", "file:///private/image.png", "C:\\private\\image.png", "data:text/html;base64,PHNjcmlwdD4=", "https://user:password@example.test/image.png"])("rejects unsafe or unarchived media URL %s", url => {
    expect(safeMediaUrl(url)).toBeNull();
    expect(mediaKind(url)).toBeNull();
  });

  it("opens a local file link on this computer instead of navigating", () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ opened: true }) }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatMarkdown text="[Clip](C:/Users/me/Downloads/Clip.mp4)" />);
    const link = screen.getByRole("link", { name: "Clip" });
    expect(link.getAttribute("href")).toBe("#jarvis-local=" + encodeURIComponent("C:/Users/me/Downloads/Clip.mp4"));
    fireEvent.click(link);
    expect(fetchMock).toHaveBeenCalledWith("/api/settings/open-path", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ path: "C:/Users/me/Downloads/Clip.mp4" }),
    }));
    vi.unstubAllGlobals();
  });

  it.each([
    ["[Clip](file:///C:/Users/Administrator/Downloads/Clip.mp4)", "C:/Users/Administrator/Downloads/Clip.mp4"],
    ["[notes.md](notes.md)", "notes.md"],
    ["[shot.png](shot.png)", "shot.png"],
  ])("opens %s on this computer", (markdown, path) => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ opened: true }) }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatMarkdown text={markdown} />);
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    screen.getByRole("link").dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/settings/open-path", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ path }),
    }));
    vi.unstubAllGlobals();
  });

  it("still opens a web link outside the window", () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ opened: true }) }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatMarkdown text="[Notes](https://example.test/notes)" />);
    fireEvent.click(screen.getByRole("link", { name: "Notes" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/settings/open-external", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ url: "https://example.test/notes" }),
    }));
    vi.unstubAllGlobals();
  });
});

describe("a page an answer shows", () => {
  const stored = "/api/outputs/chat-media-abc/files/tasks/chat/artifacts/files/media.html/download?disposition=inline";
  const page = "<!doctype html><html><head><title>Inner</title></head><body><h1>Latency</h1><script>go()</script></body></html>";

  it("draws the stored page in the sandboxed frame, not as a picture and not as a page of the app", async () => {
    const fetched = vi.fn(async () => new Response(page));
    vi.stubGlobal("fetch", fetched);
    const { container } = render(<ChatMarkdown text={`Here it is:\n\n![Latency report](<${stored}>)`} />);
    const frame = await screen.findByTestId("inline-html-frame");
    expect(fetched).toHaveBeenCalledWith(stored);
    expect(frame.getAttribute("srcdoc")).toContain("<h1>Latency</h1>");
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("data-scripts")).toBe("off");
    expect(frame.hasAttribute("src")).toBe(false);
    expect(container.querySelector("img")).toBeNull();
    // The answer's own words for it are the caption; its scripts wait for a click.
    const fence = screen.getByTestId("rendered-fence");
    expect(within(fence).getByText("Latency report")).toBeTruthy();
    expect(within(fence).getByTestId("inline-html-run-scripts")).toBeTruthy();
    expect(within(fence).getByTestId("page-download").getAttribute("href")).toBe(stored);
    // A figure cannot stand inside a paragraph.
    expect(fence.closest("p")).toBeNull();
  });

  it("says so when the stored page cannot be read", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("gone", { status: 404 })));
    render(<ChatMarkdown text={`![Report](<${stored}>)`} />);
    expect(await screen.findByRole("status")).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("cannot be loaded"));
    expect(screen.queryByTestId("inline-html-frame")).toBeNull();
  });

  it("lists the page as a file where the transcript lists files", () => {
    const fetched = vi.fn();
    vi.stubGlobal("fetch", fetched);
    render(<PictureDisplayContext.Provider value="files"><ChatMarkdown text={`![Report](<${stored}>)`} /></PictureDisplayContext.Provider>);
    expect(screen.getByRole("link", { name: /Report/ }).getAttribute("href")).toBe(stored);
    expect(fetched).not.toHaveBeenCalled();
  });

  it("draws only what the chat stored itself", () => {
    expect(mediaKind(stored)).toBe("page");
    expect(mediaKind("https://example.test/index.html")).toBeNull();
    expect(mediaKind("/api/outputs/run-1/files/report.html/download")).toBeNull();
    expect(mediaKind("/api/outputs/chat-media-abc/files/tasks/chat/artifacts/files/media.png/download")).toBe("image");
  });
});

describe("pages named in an answer", () => {
  it("draws a page link as the page's name and opens it in the node window", async () => {
    const { useNodePeek } = await import("@/store/nodePeek");
    const page = "run-1::tasks/report/artifacts/files/plan.html";
    render(<ChatMarkdown text={`I made [Business plan v1](artifact:${page}) and [a site](https://example.test/x).`} />);
    const link = screen.getByTestId("page-link");
    expect(link.textContent).toBe("Business plan v1");
    // The other link stays a web link.
    const web = screen.getByTestId("web-link");
    expect(web.textContent).toBe("a site");
    expect(web.getAttribute("href")).toBe("https://example.test/x");
    fireEvent.click(link);
    expect(useNodePeek.getState().peek).toMatchObject({ ref: page, title: "Business plan v1" });
    useNodePeek.setState({ peek: null, touched: {} });
  });
});

describe("web links in an answer", () => {
  it("draws a named link as the site's logo and its words", () => {
    render(<ChatMarkdown text="See the [Dodaios repo](https://github.com/Dodaios/Dodaios)." />);
    const link = screen.getByTestId("web-link");
    expect(link.getAttribute("href")).toBe("https://github.com/Dodaios/Dodaios");
    expect(link.textContent).toBe("Dodaios repo");
    expect(within(link).getByTestId("web-link-icon").getAttribute("src")).toBe("/api/link-icon?host=github.com");
  });

  it("shortens a bare address to a few words", () => {
    render(<ChatMarkdown text="Thread: https://www.reddit.com/r/LocalLLaMA/comments/1oxk2z/local_first_open_source_alternative/" />);
    const link = screen.getByTestId("web-link");
    expect(link.textContent).toBe("Local first open source alternative");
    expect(link.getAttribute("data-host")).toBe("reddit.com");
    expect(screen.queryByText(/reddit\.com\/r\//)).toBeNull();
  });

  it("names a post on X in the reader's language", () => {
    render(<ChatMarkdown text="https://x.com/ai_hakase_/status/1988" />);
    expect(screen.getByTestId("web-link").textContent).toMatch(/@ai_hakase_/);
  });

  it("shows the site and the full address when the pointer rests on a link, and opens it from there", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ opened: true }) }));
    vi.stubGlobal("fetch", fetchMock);
    const url = "https://www.reddit.com/r/LocalLLaMA/comments/1oxk2z/local_first/";
    render(<ChatMarkdown text={`[Local-first thread](${url})`} />);
    fireEvent.mouseEnter(screen.getByTestId("web-link").parentElement!);
    const card = await screen.findByTestId("web-link-card");
    expect(card.textContent).toContain("Reddit");
    expect(within(card).getByTestId("web-link-address").textContent).toBe("www.reddit.com/r/LocalLLaMA/comments/1oxk2z/local_first");
    fireEvent.click(card);
    expect(fetchMock).toHaveBeenCalledWith("/api/settings/open-external", expect.objectContaining({
      body: JSON.stringify({ url }),
    }));
    vi.unstubAllGlobals();
  });

  it("draws a globe when a named site's logo does not load", async () => {
    const { resetLinkIconsForTests } = await import("./WebLink");
    resetLinkIconsForTests();
    render(<ChatMarkdown text="[Repo](https://github.com/Dodaios/Dodaios)" />);
    fireEvent.error(screen.getByTestId("web-link-icon"));
    expect(screen.getByTestId("web-link-globe")).toBeTruthy();
    expect(screen.queryByTestId("web-link-icon")).toBeNull();
    resetLinkIconsForTests();
  });

  it.each([
    "https://nologo.example/",
    "https://docs.python.org/3/library/re.html",
    // What an answer wrote into a name: no logo is asked for, so the name goes nowhere.
    "https://c2vjcmv0lxrva2vu.collect.example.net/x",
    "https://github.com.example.net/x",
    "https://a.b.wikipedia.org/wiki/X",
  ])("draws a globe and asks for no logo for %s", async url => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ opened: true }) }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatMarkdown text={`[Somewhere](${url})`} />);
    const link = screen.getByTestId("web-link");
    expect(within(link).getByTestId("web-link-globe")).toBeTruthy();
    // The card on the pointer names the address and asks for no logo either.
    fireEvent.mouseEnter(link.parentElement!);
    const card = await screen.findByTestId("web-link-card");
    expect(within(card).getByTestId("web-link-globe")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.queryByTestId("web-link-icon")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("draws a sub-domain of a named site with that site's logo", () => {
    render(<ChatMarkdown text="[Turing](https://en.wikipedia.org/wiki/Alan_Turing)" />);
    expect(screen.getByTestId("web-link-icon").getAttribute("src")).toBe("/api/link-icon?host=wikipedia.org");
  });

  it("keeps bold words inside a link", () => {
    render(<ChatMarkdown text="[**Release notes**](https://example.com/v5)" />);
    expect(screen.getByTestId("web-link").textContent).toBe("Release notes");
  });
});

describe("a web link's logo and first word", () => {
  it("stay on one line together", () => {
    render(<ChatMarkdown text="[Local-first open source alternative](https://www.reddit.com/r/LocalLLaMA/)" />);
    const link = screen.getByTestId("web-link");
    const kept = link.querySelector(".whitespace-nowrap");
    expect(kept?.textContent).toBe("Local-first");
    expect(within(kept as HTMLElement).getByTestId("web-link-icon")).toBeTruthy();
    expect(link.textContent).toBe("Local-first open source alternative");
  });
});
