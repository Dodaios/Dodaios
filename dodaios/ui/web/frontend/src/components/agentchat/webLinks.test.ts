import { describe, expect, it } from "vitest";
import { clip, displayAddress, humanize, looksLikeAddress, siteName, webLinkInfo } from "./webLinks";

const bare = (url: string) => webLinkInfo(url, url);

describe("webLinkInfo", () => {
  it("keeps the words the answer gave a link", () => {
    const info = webLinkInfo("https://github.com/Dodaios/Dodaios", "Dodaios repo");
    expect(info).toMatchObject({ host: "github.com", site: "GitHub", label: null });
  });

  it("keeps a label that is more than text", () => {
    expect(webLinkInfo("https://github.com/Dodaios/Dodaios", null)?.label).toBeNull();
  });

  it("is null for an address that is not a web page", () => {
    expect(webLinkInfo("mailto:someone@example.com", "mail")).toBeNull();
    expect(webLinkInfo("#jarvis-local=%2Ftmp%2Fa.txt", "a.txt")).toBeNull();
    expect(webLinkInfo("/api/outputs/x", "x")).toBeNull();
  });

  it("names a Reddit thread by its title", () => {
    const info = bare("https://www.reddit.com/r/LocalLLaMA/comments/1oxk2z/localfirst_open_source_alternative_to_grokbot/");
    expect(info).toMatchObject({ host: "reddit.com", site: "Reddit", label: "Localfirst open source alternative to grokbot" });
    expect(bare("https://www.reddit.com/r/LocalLLaMA/")?.label).toBe("r/LocalLLaMA");
    expect(bare("https://reddit.com/user/someone")?.label).toBe("u/someone");
  });

  it("names a post on X by its author", () => {
    expect(bare("https://x.com/ai_hakase_/status/1988")?.kind).toEqual({ type: "x_post", user: "ai_hakase_" });
    expect(bare("https://twitter.com/dodaios")?.label).toBe("@dodaios");
    expect(bare("https://x.com/home")?.label).toBe("X");
  });

  it("names GitHub repositories, pull requests and files", () => {
    expect(bare("https://github.com/Dodaios/Dodaios")?.label).toBe("Dodaios/Dodaios");
    expect(bare("https://github.com/Dodaios/Dodaios/pull/1589")?.label).toBe("Dodaios/Dodaios #1589");
    expect(bare("https://github.com/Dodaios/Dodaios/issues/12")?.label).toBe("Dodaios/Dodaios #12");
    expect(bare("https://github.com/Dodaios/Dodaios/blob/main/docs/ci-pipeline.md")?.label).toBe("ci-pipeline.md");
    expect(bare("https://github.com/Dodaios/Dodaios/releases/tag/v5.2.0")?.label).toBe("Dodaios/Dodaios v5.2.0");
    expect(bare("https://github.com/Dodaios")?.label).toBe("Dodaios");
  });

  it("names Hacker News, YouTube, Wikipedia and LinkedIn pages", () => {
    expect(bare("https://news.ycombinator.com/item?id=4242")?.kind).toEqual({ type: "discussion" });
    expect(bare("https://news.ycombinator.com/")).toMatchObject({ site: "Hacker News", label: "Hacker News" });
    expect(bare("https://www.youtube.com/watch?v=abc")?.kind).toEqual({ type: "video" });
    expect(bare("https://youtu.be/abc")?.kind).toEqual({ type: "video" });
    expect(bare("https://www.youtube.com/@dodaios")?.label).toBe("@dodaios");
    expect(bare("https://en.wikipedia.org/wiki/Caf%C3%A9_racer")).toMatchObject({ site: "Wikipedia", label: "Café racer" });
    expect(bare("https://www.linkedin.com/in/jane-doe")?.label).toBe("Jane doe");
  });

  it("names any other page by the last part of its path that reads as words", () => {
    expect(bare("https://www.spiegel.de/netzwelt/apps/neue-ki-app-im-test-a-1f2e3d4c")?.label).toBe("Neue ki app im test");
    expect(bare("https://example.com/blog/2026/11/launch-week.html")?.label).toBe("Launch week");
    expect(bare("https://example.com/p/8f3a9c2d1e")?.label).toBe("example.com");
    expect(bare("https://example.com/")?.label).toBe("example.com");
  });

  it("shortens a domain path written as the link text", () => {
    expect(webLinkInfo("https://github.com/Dodaios/Dodaios", "github.com/Dodaios/Dodaios")?.label).toBe("Dodaios/Dodaios");
    expect(webLinkInfo("https://www.reddit.com/r/LocalLLaMA", "www.reddit.com/r/LocalLLaMA")?.label).toBe("r/LocalLLaMA");
  });
});

describe("helpers", () => {
  it("tells an address from a name", () => {
    expect(looksLikeAddress("https://a.b/c")).toBe(true);
    expect(looksLikeAddress("www.a.com")).toBe(true);
    expect(looksLikeAddress("github.com/a/b")).toBe(true);
    expect(looksLikeAddress("Dodaios repo")).toBe(false);
    expect(looksLikeAddress("README.md")).toBe(false);
  });

  it("knows websites by name, also on a sub-domain", () => {
    expect(siteName("reddit.com")).toBe("Reddit");
    expect(siteName("en.wikipedia.org")).toBe("Wikipedia");
    expect(siteName("heise.de")).toBe("heise.de");
  });

  it("turns slugs into words and leaves ids alone", () => {
    expect(humanize("local_first-tool")).toBe("Local first tool");
    expect(humanize("1oxk2z")).toBeNull();
    expect(humanize("a3f9c2d1e8")).toBeNull();
    expect(humanize("2026")).toBeNull();
  });

  it("clips a long name on a word", () => {
    const long = clip("one two three four five six seven eight nine ten eleven twelve thirteen", 30);
    expect(long.endsWith("…")).toBe(true);
    expect(long.length).toBeLessThanOrEqual(30);
    expect(long).toBe("one two three four five six…");
  });

  it("shows the address without its scheme", () => {
    expect(displayAddress("https://www.reddit.com/r/LocalLLaMA/")).toBe("www.reddit.com/r/LocalLLaMA");
  });
});
