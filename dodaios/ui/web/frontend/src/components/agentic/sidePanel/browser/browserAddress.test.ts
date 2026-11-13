import { describe, expect, it } from "vitest";
import { normalizeBrowserAddress, readBrowserInput, wordFromBrokenAddress } from "./browserAddress";

describe("normalizeBrowserAddress", () => {
  it("sends bare ports and local hosts over http", () => {
    expect(normalizeBrowserAddress("5173")).toBe("http://localhost:5173/");
    expect(normalizeBrowserAddress(":3000/app")).toBe("http://localhost:3000/app");
    expect(normalizeBrowserAddress("localhost:8080")).toBe("http://localhost:8080/");
    expect(normalizeBrowserAddress("127.0.0.1:4321/x?y=1")).toBe("http://127.0.0.1:4321/x?y=1");
  });

  it("adds https to other hosts and keeps explicit web schemes", () => {
    expect(normalizeBrowserAddress("  example.com/docs ")).toBe("https://example.com/docs");
    expect(normalizeBrowserAddress("http://intranet.test")).toBe("http://intranet.test/");
  });

  it("refuses non-web schemes, blanks and text with spaces", () => {
    expect(normalizeBrowserAddress("javascript:alert(1)")).toBeNull();
    expect(normalizeBrowserAddress("file:///etc/passwd")).toBeNull();
    expect(normalizeBrowserAddress("")).toBeNull();
    expect(normalizeBrowserAddress("two words")).toBeNull();
  });
});

describe("readBrowserInput", () => {
  it("searches for a single word and for text with spaces, as a browser bar does", () => {
    expect(readBrowserInput("github")).toEqual({
      kind: "search", query: "github", url: "https://www.google.com/search?q=github",
    });
    expect(readBrowserInput("  flüge münchen dubai ")).toEqual({
      kind: "search", query: "flüge münchen dubai",
      url: "https://www.google.com/search?q=fl%C3%BCge%20m%C3%BCnchen%20dubai",
    });
    expect(readBrowserInput("javascript: alert(1)")?.kind).toBe("search");
  });

  it("keeps addresses, local hosts and bare ports as addresses", () => {
    expect(readBrowserInput("github.com")).toEqual({ kind: "address", url: "https://github.com/" });
    expect(readBrowserInput("localhost")).toEqual({ kind: "address", url: "http://localhost/" });
    expect(readBrowserInput("5173")).toEqual({ kind: "address", url: "http://localhost:5173/" });
    expect(readBrowserInput("nas:5000")).toEqual({ kind: "address", url: "https://nas:5000/" });
    expect(readBrowserInput("http://intranet/")).toEqual({ kind: "address", url: "http://intranet/" });
    expect(readBrowserInput("javascript:alert(1)")).toBeNull();
    expect(readBrowserInput("   ")).toBeNull();
  });
});

describe("wordFromBrokenAddress", () => {
  it("finds the search word the old bar turned into a host", () => {
    expect(wordFromBrokenAddress("https://github/")).toBe("github");
  });

  it("leaves real addresses alone", () => {
    for (const url of ["https://github.com/", "http://localhost:5173/", "https://nas:5000/",
      "http://intranet/", "https://wiki/page", "https://localhost/", "not a url"]) {
      expect(wordFromBrokenAddress(url)).toBeNull();
    }
  });
});
