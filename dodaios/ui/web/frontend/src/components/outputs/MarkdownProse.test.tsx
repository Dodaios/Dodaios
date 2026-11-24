import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { artifactInlineUrl, type ArtifactSummary } from "@/hooks/useOutputs";
import { MarkdownProse } from "./MarkdownProse";

afterEach(cleanup);

const DOCUMENT = "tasks/report/artifacts/files/report.md";
const CHART = "tasks/report/artifacts/files/chart.png";
const picture: ArtifactSummary = { path: CHART, size: 4096, mtime: 1, is_text: false, preview: null };

it("draws a picture of the run and loads no remote one", () => {
  const remote = "https://example.test/r.png?d=c2VjcmV0";
  render(
    <MarkdownProse
      slug="run-1"
      path={DOCUMENT}
      files={[picture]}
      text={`# Report\n\n![chart](chart.png)\n\n![tracker](${remote})\n\n![other](<//example.test/o.png>)`}
    />,
  );
  const page = screen.getByTestId("artifact-markdown");
  // The picture beside the document comes from the run archive, as before.
  expect(Array.from(page.querySelectorAll("img")).map((image) => image.getAttribute("src"))).toEqual([artifactInlineUrl("run-1", CHART)]);
  // A remote address is a link, as in a chat message: opening the document asks no host.
  expect(within(page).getByRole("link", { name: /tracker/ }).getAttribute("href")).toBe(remote);
  expect(within(page).getByRole("link", { name: /other/ }).getAttribute("href")).toBe("//example.test/o.png");
});
