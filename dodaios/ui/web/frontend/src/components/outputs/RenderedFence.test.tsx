/**
 * An `html` or `svg` fence in a Markdown deliverable is DRAWN, with its
 * markup one click away — and it draws in the artifact page's sandbox
 * model, never in the app's origin, with none of its own scripts running
 * until the reader asks.
 */
import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { MarkdownProse } from "@/components/outputs/MarkdownProse";
import {
  INLINE_HTML_CSP,
  INLINE_HTML_SIZE_MESSAGE,
  VISUAL_TOKENS,
  hasScripts,
  isThemeAware,
  pinColourScheme,
  scalableSvg,
  visualDocument,
  visualTitle,
} from "@/components/outputs/RenderedFence";

afterEach(() => cleanup());

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>';
const OPTIONS = { theme: "dark", token: "tok", nonce: "n0nce" } as const;

/** The policy a document carries, as the browser will read it. */
function policyOf(doc: string): string {
  return /<meta http-equiv="Content-Security-Policy" content="([^"]*)">/.exec(doc)?.[1] ?? "";
}

describe("visualDocument", () => {
  it("puts the policy and the size reporter in front of everything the author wrote", () => {
    const doc = visualDocument("<div>hi</div>", OPTIONS);
    expect(doc.startsWith('<!doctype html><html lang="en" data-theme="light"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy"')).toBe(true);
    expect(doc.indexOf("Content-Security-Policy")).toBeLessThan(doc.indexOf("<div>hi</div>"));
    expect(doc.indexOf(INLINE_HTML_SIZE_MESSAGE)).toBeLessThan(doc.indexOf("<div>hi</div>"));
    expect(doc).toContain('token:"tok"');
  });

  it("lets only the size reporter run while the visual's own scripts are off", () => {
    const evil = '<img src=x onerror="steal()"><script>steal()</script>';
    const doc = visualDocument(evil, OPTIONS);
    const policy = policyOf(doc);
    expect(policy).toContain("script-src 'nonce-n0nce'");
    expect(policy).not.toContain("unsafe-inline'; style"); // no inline script allowance
    expect(policy).toContain("default-src 'none'");
    expect(policy).toContain("connect-src 'none'");
    // The author's script stands in the document, without the nonce.
    expect(doc).toContain("<script>steal()</script>");
    expect(doc.match(/<script nonce="n0nce">/g)).toHaveLength(1);
  });

  it("keeps the policy in front of a page that hides a script before its head", () => {
    const page = "<html><script>early()</script><head><title>t</title></head><body><p>x</p></body></html>";
    const doc = visualDocument(page, OPTIONS);
    expect(doc.indexOf("Content-Security-Policy")).toBeLessThan(doc.indexOf("early()"));
    expect(doc.match(/<html/g)).toHaveLength(1);
    expect(doc).toContain('<html data-theme="light">');
  });

  it("allows the page's scripts once the reader asked, with the artifact policy", () => {
    const doc = visualDocument("<div>hi</div>", { ...OPTIONS, scripts: true });
    expect(policyOf(doc)).toBe(INLINE_HTML_CSP);
  });

  it("draws a visual that fixes its own colours on a white page, in both palettes", () => {
    const doc = visualDocument('<p style="color:#333">x</p>', OPTIONS);
    expect(doc).toContain("color-scheme:light !important");
    expect(doc).toContain("--fg:#171717");
  });

  it("gives a page that asks for the reader's palette the app's answer, not the computer's", () => {
    const page = "<html><head><style>:root{color-scheme:light dark;--ink:#111}"
      + "@media (prefers-color-scheme: dark){:root{--ink:#eee}}"
      + "@media ( prefers-color-scheme:light ) and (min-width:400px){p{margin:0}}</style></head><body><p>x</p></body></html>";
    const dark = visualDocument(page, OPTIONS);
    expect(dark).toContain("@media (min-width:0px){:root{--ink:#eee}}");
    expect(dark).toContain("@media (max-width:0px) and (min-width:400px){p{margin:0}}");
    expect(dark).toContain("color-scheme:dark !important");
    const light = visualDocument(page, { ...OPTIONS, theme: "light" });
    expect(light).toContain("@media (max-width:0px){:root{--ink:#eee}}");
    expect(light).toContain("@media (min-width:0px) and (min-width:400px){p{margin:0}}");
    expect(light).not.toContain("prefers-color-scheme");
  });

  it("draws a visual that names the chat's colours in the app's palette", () => {
    const doc = visualDocument('<p style="color:var(--muted)">x</p>', OPTIONS);
    expect(doc).toContain('data-theme="dark"');
    expect(doc).toContain("color-scheme:dark !important");
    expect(doc).toContain("--fg:#fafafa");
    for (const token of VISUAL_TOKENS) expect(doc).toContain(`--${token}:`);
  });

  it("keeps a page's own theme stamp and drops its late doctype", () => {
    const doc = visualDocument('<!DOCTYPE html>\n<html data-theme="dark"><body>x</body></html>', { ...OPTIONS, theme: "light" });
    expect(doc.match(/<!doctype/gi)).toHaveLength(1);
    expect(doc).toContain('<html data-theme="dark">');
  });

  it("sets a bare svg in a page and lets it scale", () => {
    const doc = visualDocument(SVG, { ...OPTIONS, language: "svg" });
    expect(doc).toContain('<svg viewBox="0 0 10 10" xmlns=');
    expect(doc).toContain("body>svg{display:block;margin:0 auto}");
  });
});

describe("what a visual says about itself", () => {
  it("knows a visual that follows the palette", () => {
    expect(isThemeAware('<rect stroke="var(--line)"/>')).toBe(true);
    expect(isThemeAware("@media (prefers-color-scheme: dark) {}")).toBe(true);
    expect(isThemeAware('<rect stroke="#333" fill="var(--brand)"/>')).toBe(false);
  });

  it("answers a palette query for the look it is drawn in", () => {
    expect(pinColourScheme("@media (prefers-color-scheme: dark) {}", "dark")).toBe("@media (min-width:0px) {}");
    expect(pinColourScheme("@media (prefers-color-scheme: dark) {}", "light")).toBe("@media (max-width:0px) {}");
    expect(pinColourScheme("matchMedia('(prefers-color-scheme: light)')", "light")).toBe("matchMedia('(min-width:0px)')");
  });

  it("reads the caption from the title", () => {
    expect(visualTitle("<svg><title>Sign-in  flow</title></svg>")).toBe("Sign-in flow");
    expect(visualTitle("<div>x</div>")).toBe("");
  });

  it("knows a page that would run something", () => {
    expect(hasScripts("<script>x()</script>")).toBe(true);
    expect(hasScripts('<button onclick="x()">go</button>')).toBe(true);
    expect(hasScripts("<p>one script too many</p>")).toBe(false);
  });

  it("gives a sized svg a view box and leaves one that has it alone", () => {
    expect(scalableSvg('<svg width="800px" height="400">')).toBe('<svg viewBox="0 0 800 400" width="800px" height="400">');
    const boxed = '<svg viewBox="0 0 5 5" width="800" height="400">';
    expect(scalableSvg(boxed)).toBe(boxed);
    expect(scalableSvg('<svg width="100%">')).toBe('<svg width="100%">');
  });
});

describe("MarkdownProse fences", () => {
  it.each(["SVG", "xml", "image/svg+xml", ""])("draws a complete SVG with label %s", language => {
    render(<MarkdownProse slug="r" path="r.md" files={[]} text={`\`\`\`${language}\n${SVG}\n\`\`\``} />);
    expect(screen.getByTestId("rendered-fence").getAttribute("data-language")).toBe("svg");
    expect(screen.getByTestId("inline-html-frame").getAttribute("srcdoc")).toContain("<rect");
  });

  it("draws an svg fence and an html fence, each in a sandboxed frame", () => {
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
    for (const fence of fences) {
      const frame = within(fence).getByTestId("inline-html-frame") as HTMLIFrameElement;
      // An opaque origin, always: the frame never joins the app's.
      expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
      expect(frame.getAttribute("data-scripts")).toBe("off");
      expect(policyOf(frame.getAttribute("srcdoc") ?? "")).toMatch(/script-src 'nonce-[0-9a-f]{32}'/);
    }
    expect(within(fences[1]).getByTestId("inline-html-frame").getAttribute("srcdoc")).toContain('<div id="card">hi</div>');
  });

  it("runs none of the page's scripts until the reader clicks Run scripts, and never joins the app origin", () => {
    const evil = '<html><head></head><body><script>location.href="http://blocked.invalid/leak"</script></body></html>';
    render(<MarkdownProse slug="r" path="r.md" files={[]} text={"```html\n" + evil + "\n```\n"} />);
    const fence = screen.getByTestId("rendered-fence");

    const inert = within(fence).getByTestId("inline-html-frame") as HTMLIFrameElement;
    const before = inert.getAttribute("srcdoc") ?? "";
    expect(policyOf(before)).not.toContain("'unsafe-inline'; style-src"); // script-src holds a nonce only
    expect(policyOf(before)).toMatch(/script-src 'nonce-[0-9a-f]{32}';/);
    // The page's script carries no nonce, so the policy refuses it.
    expect(before).toContain('<script>location.href="http://blocked.invalid/leak"</script>');
    expect(inert.getAttribute("sandbox")).not.toContain("allow-same-origin");

    fireEvent.click(within(fence).getByTestId("inline-html-run-scripts"));
    const live = within(fence).getByTestId("inline-html-frame") as HTMLIFrameElement;
    expect(live.getAttribute("sandbox")).toBe("allow-scripts");
    expect(live.getAttribute("data-scripts")).toBe("on");
    expect(policyOf(live.getAttribute("srcdoc") ?? "")).toBe(INLINE_HTML_CSP);
    expect(within(fence).queryByTestId("inline-html-run-scripts")).toBeNull();
  });

  it("offers Run scripts only where there is something to run", () => {
    render(<MarkdownProse slug="r" path="r.md" files={[]} text={"```svg\n" + SVG + "\n```\n\n```html\n<b>bold</b>\n```\n"} />);
    expect(screen.queryByTestId("inline-html-run-scripts")).toBeNull();
  });

  it("takes the height its own frame reports, and no other window's word for it", () => {
    render(<MarkdownProse slug="r" path="r.md" files={[]} text={"```html\n<b>bold</b>\n```\n"} />);
    const frame = screen.getByTestId("inline-html-frame") as HTMLIFrameElement;
    const token = /token:"([^"]+)"/.exec(frame.getAttribute("srcdoc") ?? "")?.[1];
    expect(token).toBeTruthy();
    const report = (source: MessageEventSource | null, height: number) => act(() => {
      window.dispatchEvent(new MessageEvent("message", { source, data: { type: INLINE_HTML_SIZE_MESSAGE, token, height } }));
    });
    report(window, 300);
    expect(frame.style.height).toBe("160px");
    report(frame.contentWindow, 300);
    expect(frame.style.height).toBe("300px");
    report(frame.contentWindow, 90_000);
    expect(frame.style.height).toBe("640px");
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

  it("opens the visual large on request", () => {
    render(<MarkdownProse slug="r" path="r.md" files={[]} text={"```svg\n<svg viewBox=\"0 0 4 4\"><title>Sign-in flow</title></svg>\n```\n"} />);
    expect(screen.getByText("Sign-in flow")).toBeDefined(); // the caption
    fireEvent.click(screen.getByTestId("visual-expand"));
    const large = within(screen.getByTestId("visual-full-view")).getByTestId("inline-html-frame") as HTMLIFrameElement;
    expect(large.style.height).toBe("100%");
  });

  it("leaves every other fence to the code block", () => {
    render(<MarkdownProse slug="r" path="r.md" files={[]} text={"```python\nprint(1)\n```\n"} />);
    expect(screen.queryByTestId("rendered-fence")).toBeNull();
    expect(screen.getByText("print(1)")).toBeDefined();
  });
});
