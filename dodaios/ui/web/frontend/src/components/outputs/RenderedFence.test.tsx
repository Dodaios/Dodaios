/**
 * An `html` or `svg` fence in a Markdown deliverable is DRAWN, with its
 * markup one click away — and the HTML runs in the artifact page's sandbox
 * model, never in the app's origin.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { MarkdownProse } from "@/components/outputs/MarkdownProse";
import {
  INLINE_HTML_CSP,
  INLINE_HTML_SIZE_MESSAGE,
  wrapInlineHtml,
  svgDataUrl,
} from "@/components/outputs/RenderedFence";

afterEach(() => cleanup());

it("adds the standalone SVG namespace without replacing a declared namespace", () => {
  expect(decodeURIComponent(svgDataUrl('<svg viewBox="0 0 10 10"><rect/></svg>'))).toContain('<svg xmlns="http://www.w3.org/2000/svg"');
  const declared = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>';
  expect(decodeURIComponent(svgDataUrl(declared)).split(",")[1]).toBe(declared);
});

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>';

describe("wrapInlineHtml", () => {
  it("wraps a fragment in a themed page with the artifact CSP and the size reporter", () => {
    const doc = wrapInlineHtml("<div>hi</div>", "dark", ":r1:");
    expect(doc.startsWith("<!doctype html>")).toBe(true);
    expect(doc).toContain('data-theme="dark"');
    expect(doc).toContain(`content="${INLINE_HTML_CSP}"`);
    expect(doc).toContain("<div>hi</div>");
    expect(doc).toContain(INLINE_HTML_SIZE_MESSAGE);
    expect(doc).toContain('token:":r1:"');
  });

  it("stamps a whole page instead of wrapping it", () => {
    const page = "<html><head><title>t</title></head><body><p>x</p></body></html>";
    const doc = wrapInlineHtml(page, "light", "a");
    expect(doc.match(/<html/g)).toHaveLength(1);
    expect(doc).toContain('<html data-theme="light">');
    expect(doc).toContain(`<head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy"`);
    expect(doc).toContain("</script></body>");
  });

  it("injects no script into the inert preview", () => {
    const doc = wrapInlineHtml("<div>hi</div>", "dark", "a", { scripts: false });
    expect(doc).not.toContain("<script");
    expect(doc).toContain(`content="${INLINE_HTML_CSP}"`);
  });

  it("keeps a page's own theme stamp and adds a head when it has none", () => {
    const doc = wrapInlineHtml('<html data-theme="dark"><body>x</body></html>', "light", "a");
    expect(doc).toContain('<html data-theme="dark"><head><meta charset="utf-8">');
    expect(doc).not.toContain('data-theme="light"');
  });
});

describe("MarkdownProse fences", () => {
  it.each(["SVG", "xml", "image/svg+xml", ""])("draws a complete SVG with label %s", language => {
    render(<MarkdownProse slug="r" path="r.md" files={[]} text={`\`\`\`${language}\n${SVG}\n\`\`\``} />);
    expect(screen.getByTestId("inline-svg")).toBeDefined();
  });
  it("draws an svg fence as a picture and an html fence in a sandboxed frame", () => {
    render(
      <MarkdownProse
        slug="run-1"
        path="report.md"
        files={[]}
        text={"# Chart\n\n```svg\n" + SVG + "\n```\n\n```html\n<div id=\"card\">hi</div>\n```\n"}
      />,
    );
    const fences = screen.getAllByTestId("rendered-fence");
    expect(fences.map((f) => f.getAttribute("data-language"))).toEqual(["svg", "html"]);

    const picture = within(fences[0]).getByTestId("inline-svg") as HTMLImageElement;
    expect(picture.getAttribute("src")).toBe(
      `data:image/svg+xml;charset=utf-8,${encodeURIComponent(SVG)}`,
    );

    const frame = within(fences[1]).getByTestId("inline-html-frame") as HTMLIFrameElement;
    // Inert by default (#346): an empty sandbox runs no script at all.
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("data-scripts")).toBe("off");
    expect(frame.getAttribute("srcdoc")).toContain('<div id="card">hi</div>');
    expect(frame.getAttribute("srcdoc")).toContain("Content-Security-Policy");
  });

  it("runs no script until the reader clicks Run scripts, and never joins the app origin", () => {
    const evil = '<html><head></head><body><script>location.href="http://blocked.invalid/leak"</script></body></html>';
    render(<MarkdownProse slug="r" path="r.md" files={[]} text={"```html\n" + evil + "\n```\n"} />);
    const fence = screen.getByTestId("rendered-fence");

    const inert = within(fence).getByTestId("inline-html-frame") as HTMLIFrameElement;
    expect(inert.getAttribute("sandbox")).toBe("");
    expect(inert.getAttribute("srcdoc")).not.toContain(INLINE_HTML_SIZE_MESSAGE);

    fireEvent.click(within(fence).getByTestId("inline-html-run-scripts"));
    const live = within(fence).getByTestId("inline-html-frame") as HTMLIFrameElement;
    expect(live.getAttribute("sandbox")).toBe("allow-scripts");
    expect(live.getAttribute("sandbox")).not.toContain("allow-same-origin");
    expect(live.getAttribute("data-scripts")).toBe("on");
    expect(live.getAttribute("srcdoc")).toContain(INLINE_HTML_SIZE_MESSAGE);
    expect(within(fence).queryByTestId("inline-html-run-scripts")).toBeNull();
  });

  it("offers no Run scripts switch on an svg fence", () => {
    render(<MarkdownProse slug="r" path="r.md" files={[]} text={"```svg\n" + SVG + "\n```\n"} />);
    expect(screen.queryByTestId("inline-html-run-scripts")).toBeNull();
  });

  it("shows the markup behind the Source switch and comes back to Rendered", () => {
    render(
      <MarkdownProse slug="run-1" path="r.md" files={[]} text={"```html\n<b>bold</b>\n```\n"} />,
    );
    const fence = screen.getByTestId("rendered-fence");
    expect(fence.getAttribute("data-mode")).toBe("rendered");

    fireEvent.click(within(fence).getByRole("button", { name: "Source" }));
    expect(fence.getAttribute("data-mode")).toBe("source");
    expect(within(fence).queryByTestId("inline-html-frame")).toBeNull();
    expect(within(fence).getByText("<b>bold</b>")).toBeDefined();

    fireEvent.click(within(fence).getByRole("button", { name: "Rendered" }));
    expect(within(fence).getByTestId("inline-html-frame")).toBeDefined();
  });

  it("leaves every other fence to the code block", () => {
    render(<MarkdownProse slug="r" path="r.md" files={[]} text={"```python\nprint(1)\n```\n"} />);
    expect(screen.queryByTestId("rendered-fence")).toBeNull();
    expect(screen.getByText("print(1)")).toBeDefined();
  });
});
