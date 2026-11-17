import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";

import { PREVIEW_CSP, PreviewFrame, preparePreviewHtml, previewCsp, useNodePreview } from "./PreviewFrame";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const PAGE = '<!doctype html><html lang="en"><head><title>x</title></head><body><main>Hi</main></body></html>';

describe("previewCsp", () => {
  it("opens one way in: a clip's library files on the app's own origin", () => {
    const csp = previewCsp("http://127.0.0.1:8765");
    expect(csp).toContain("media-src data: blob: http://127.0.0.1:8765/clip-media/;");
    expect(csp).toContain("img-src data: blob: http://127.0.0.1:8765/clip-media/;");
    expect(csp).toContain("connect-src 'none'");
    // An origin that is not a plain web origin leaves the policy shut.
    expect(previewCsp("null")).toBe(PREVIEW_CSP);
    expect(previewCsp("http://x; script-src *")).toBe(PREVIEW_CSP);
  });
});

describe("preparePreviewHtml", () => {
  it("puts the network-shut policy first in <head>, stamps the theme and adds the editor's script", () => {
    const html = preparePreviewHtml(PAGE, "dark", "window.x = 1; '</script>'");
    expect(html).toContain(`<head><meta http-equiv="Content-Security-Policy" content="${previewCsp()}">`);
    expect(html).toContain('<html lang="en" data-theme="dark">');
    expect(html).toContain("<script>window.x = 1; '<\\/script>'</script></body>");
    expect(PREVIEW_CSP).toContain("connect-src 'none'");
    expect(preparePreviewHtml('<html data-theme="light"><head></head></html>', "dark")).toContain('<html data-theme="dark">');
  });
});

describe("PreviewFrame", () => {
  it("frames the page in a script-only sandbox and hears only its own frame", () => {
    const onMessage = vi.fn();
    render(<PreviewFrame html={PAGE} title="Preview" onMessage={onMessage} />);
    const frame = screen.getByTitle("Preview") as HTMLIFrameElement;
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("srcdoc")).toContain("<main>Hi</main>");
    act(() => void window.dispatchEvent(new MessageEvent("message", { data: "stranger", source: window })));
    expect(onMessage).not.toHaveBeenCalled();
    act(() => void window.dispatchEvent(new MessageEvent("message", { data: { path: "/a" }, source: frame.contentWindow })));
    expect(onMessage).toHaveBeenCalledWith({ path: "/a" });
  });
});

describe("useNodePreview", () => {
  it("asks once the spec stops changing and keeps the last good page on a refusal", async () => {
    const bodies: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
        const body = JSON.parse(String(init?.body)) as { spec: { n: number } };
        bodies.push(body.spec);
        if (body.spec.n < 0) return { ok: false, status: 422, json: async () => ({ detail: "No." }) };
        return { ok: true, status: 200, text: async () => `<p>${body.spec.n}</p>` };
      }),
    );
    const { result, rerender } = renderHook(({ spec }) => useNodePreview("n1", spec, { delayMs: 15 }), {
      initialProps: { spec: { n: 1 } },
    });
    rerender({ spec: { n: 2 } });
    rerender({ spec: { n: 3 } });
    await waitFor(() => expect(result.current.html).toBe("<p>3</p>"));
    expect(bodies).toEqual([{ n: 3 }]);
    rerender({ spec: { n: -1 } });
    await waitFor(() => expect(result.current.error).toBe("No."));
    expect(result.current.html).toBe("<p>3</p>");
    expect(result.current.loading).toBe(false);
  });
});
