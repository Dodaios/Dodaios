import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { SourceCard, type SourceDocument } from "./SourceCard";

afterEach(cleanup);

const noop = () => undefined;

function documentOf(body: string): SourceDocument {
  return {
    data: { content: body, path: "USER.md", mtime_ms: null, size_bytes: body.length },
    isLoading: false,
    error: null,
    isRefetching: false,
    refetch: noop,
    editing: false,
    draft: "",
    setDraft: noop,
    startEditing: noop,
    cancelEditing: noop,
    save: noop,
    isSaving: false,
    pulsing: false,
    body,
  };
}

it("loads no remote picture the profile names", () => {
  const remote = "https://example.test/p.png?d=c2VjcmV0";
  render(<SourceCard doc={documentOf(`# About me\n\n![portrait](${remote})\n\n![own](/api/media/own.png)`)} />);
  const page = screen.getByTestId("profile-source-markdown");
  expect(within(page).getByRole("heading", { name: "About me" })).toBeTruthy();
  // What the app serves is drawn; the remote address is a link, as in a chat message.
  expect(Array.from(page.querySelectorAll("img")).map((image) => image.getAttribute("src"))).toEqual(["/api/media/own.png"]);
  expect(within(page).getByRole("link", { name: /portrait/ }).getAttribute("href")).toBe(remote);
});
