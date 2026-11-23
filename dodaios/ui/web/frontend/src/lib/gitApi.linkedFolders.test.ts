import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchLinkedFolders } from "./gitApi";

function answer(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchLinkedFolders", () => {
  it("hands over which repository is which folder", async () => {
    answer({ linked: { p1: "Octo/App" }, folders: { "octo/app": "/work/app" } });
    expect(await fetchLinkedFolders()).toEqual({ "octo/app": "/work/app" });
  });

  it("says nothing is known on a backend that predates the folders", async () => {
    // Such a backend would clone into its own checkout: the picker must be able
    // to tell it from one that has no connected repositories.
    answer({ linked: { p1: "Octo/App" } });
    expect(await fetchLinkedFolders()).toBeNull();
    answer({ linked: {}, folders: {} });
    expect(await fetchLinkedFolders()).toEqual({});
  });
});
