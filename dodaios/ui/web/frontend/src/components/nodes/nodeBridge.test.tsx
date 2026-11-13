/**
 * The app's side of the comment bridge: only its own frame is heard, a
 * comment is plain bounded text, and the page learns how the sending went.
 */
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import {
  NODE_COMMENT_MESSAGE,
  NODE_COMMENT_STATE_MESSAGE,
  NODE_MODE_MESSAGE,
  NODE_READY_MESSAGE,
  parseNodeComment,
  useNodeBridge,
  type NodeComment,
} from "./nodeBridge";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const LABELS = { placeholder: "Add a comment…", send: "Send", sent: "Sent", failed: "Not sent." };

function Harness({
  commenting,
  onComment,
}: {
  commenting: boolean;
  onComment: (comment: NodeComment) => Promise<void>;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  useNodeBridge(frame, { commenting, labels: LABELS, onComment });
  return <iframe ref={frame} title="page" data-testid="frame" />;
}

function fromFrame(data: unknown, source?: Window | null) {
  const frame = screen.getByTestId("frame") as HTMLIFrameElement;
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, source: source ?? frame.contentWindow }));
  });
}

const flush = () => act(async () => void (await Promise.resolve()));

describe("parseNodeComment", () => {
  it("takes a comment as bounded, trimmed text", () => {
    expect(
      parseNodeComment({ type: NODE_COMMENT_MESSAGE, n: 2, text: "  shorter ", quote: " Intro ", where: "/slides/0" }),
    ).toEqual({ n: 2, text: "shorter", quote: "Intro", where: "/slides/0" });
    const long = parseNodeComment({ type: NODE_COMMENT_MESSAGE, n: 1, text: "x".repeat(5000), quote: "q".repeat(900) });
    expect(long?.text).toHaveLength(2000);
    expect(long?.quote).toHaveLength(240);
    expect(long?.where).toBe("");
  });

  it("refuses everything that is not one", () => {
    expect(parseNodeComment(null)).toBeNull();
    expect(parseNodeComment("dodaios-node-comment")).toBeNull();
    expect(parseNodeComment({ type: "dodaios-open-link", n: 1, text: "x" })).toBeNull();
    expect(parseNodeComment({ type: NODE_COMMENT_MESSAGE, n: 1, text: "   " })).toBeNull();
    expect(parseNodeComment({ type: NODE_COMMENT_MESSAGE, n: 0, text: "x" })).toBeNull();
    expect(parseNodeComment({ type: NODE_COMMENT_MESSAGE, n: "1", text: "x" })).toBeNull();
    expect(parseNodeComment({ type: NODE_COMMENT_MESSAGE, n: 1, text: { toString: () => "x" } })).toBeNull();
  });
});

describe("useNodeBridge", () => {
  it("tells the page its mode when the page loads and when the mode changes", () => {
    const onComment = vi.fn(async () => undefined);
    const view = render(<Harness commenting={false} onComment={onComment} />);
    const frame = screen.getByTestId("frame") as HTMLIFrameElement;
    const posted = vi.spyOn(frame.contentWindow as Window, "postMessage");

    fromFrame({ type: NODE_READY_MESSAGE });
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_MODE_MESSAGE, mode: "view", labels: LABELS }, "*");

    view.rerender(<Harness commenting onComment={onComment} />);
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_MODE_MESSAGE, mode: "comment", labels: LABELS }, "*");

    // A page drawn again asks once more and comes back in the same mode.
    posted.mockClear();
    fromFrame({ type: NODE_READY_MESSAGE });
    expect(posted).toHaveBeenCalledWith({ type: NODE_MODE_MESSAGE, mode: "comment", labels: LABELS }, "*");
  });

  it("hands a comment on and tells the page that it went out", async () => {
    const onComment = vi.fn(async (_comment: NodeComment) => undefined);
    render(<Harness commenting onComment={onComment} />);
    const frame = screen.getByTestId("frame") as HTMLIFrameElement;
    const posted = vi.spyOn(frame.contentWindow as Window, "postMessage");

    fromFrame({ type: NODE_COMMENT_MESSAGE, n: 1, text: "Make this shorter", quote: "Intro", where: "§ Intro" });
    await flush();
    expect(onComment).toHaveBeenCalledWith({ n: 1, text: "Make this shorter", quote: "Intro", where: "§ Intro" });
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_COMMENT_STATE_MESSAGE, n: 1, state: "sent" }, "*");
  });

  it("tells the page when a comment could not be sent", async () => {
    const onComment = vi.fn(async () => {
      throw new Error("offline");
    });
    render(<Harness commenting onComment={onComment} />);
    const frame = screen.getByTestId("frame") as HTMLIFrameElement;
    const posted = vi.spyOn(frame.contentWindow as Window, "postMessage");

    fromFrame({ type: NODE_COMMENT_MESSAGE, n: 3, text: "x", quote: "", where: "" });
    await flush();
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_COMMENT_STATE_MESSAGE, n: 3, state: "failed" }, "*");
  });

  it("hears nothing that does not come from its own frame", async () => {
    const onComment = vi.fn(async () => undefined);
    render(<Harness commenting onComment={onComment} />);

    fromFrame({ type: NODE_COMMENT_MESSAGE, n: 1, text: "x", quote: "", where: "" }, window);
    await flush();
    expect(onComment).not.toHaveBeenCalled();
  });
});
