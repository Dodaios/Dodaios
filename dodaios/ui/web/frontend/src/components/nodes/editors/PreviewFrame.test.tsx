import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";

import { PREVIEW_CSP, PreviewFrame, preparePreviewHtml, useNodePreview } from "./PreviewFrame";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const PAGE = '<!doctype html><html lang="en"><head><title>x</title></head><body><main>Hi</main></body></html>';

describe("preparePreviewHtml", () => {
  it("puts the network-shut policy first in <head>, stamps the theme and adds the editor's script", () => {
    const html = preparePreviewHtml(PAGE, "dark", "window.x = 1; '</script>'");
    expect(html).toContain(`<head><meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}">`);
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
