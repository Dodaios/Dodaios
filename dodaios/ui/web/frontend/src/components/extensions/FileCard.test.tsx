import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { MarkdownBody } from "./FileCard";

afterEach(cleanup);

it("loads no remote picture a pack's file names", () => {
  const remote = "https://example.test/logo.png?v=1";
  render(<MarkdownBody text={`---\nname: demo\n---\n# Usage\n\n![logo](${remote})\n\n![own](/api/media/own.png)`} />);
  expect(screen.getByRole("heading", { name: "Usage" })).toBeTruthy();
  // What the app serves is drawn; the remote address is a link, as in a chat message.
  expect(Array.from(document.querySelectorAll("img")).map((image) => image.getAttribute("src"))).toEqual(["/api/media/own.png"]);
  expect(screen.getByRole("link", { name: /logo/ }).getAttribute("href")).toBe(remote);
});
