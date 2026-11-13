/**
 * The app's side of the comment bridge: only its own frame is heard, a
 * comment is plain bounded text that waits for "Send", and the page learns
 * where each of its comments stands.
 */
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import {
  NODE_COMMENT_MESSAGE,
  NODE_COMMENT_REMOVE_MESSAGE,
  NODE_COMMENT_STATE_MESSAGE,
  NODE_EDIT_MESSAGE,
  NODE_EDIT_STATE_MESSAGE,
  NODE_MODE_MESSAGE,
  NODE_READY_MESSAGE,
  NODE_SCROLL_MESSAGE,
  parseNodeComment,
  parseNodeEdit,
  useNodeBridge,
  type NodeComment,
  type NodeEdit,
  type NodePageMode,
  type TellCommentState,
} from "./nodeBridge";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const LABELS = {
  placeholder: "Add a comment…",
  add: "Add comment",
  pending: "Not sent yet",
  sent: "Sent",
  failed: "Not sent.",
  remove: "Remove comment",
};

let tellState: TellCommentState | null = null;

function Harness({
  commenting,
  mode,
  onComment = async () => undefined,
  onRemove,
  onEdit,
  pageKey,
}: {
  commenting?: boolean;
  mode?: NodePageMode;
  onComment?: (comment: NodeComment) => Promise<void>;
  onRemove?: (n: number) => void;
  onEdit?: (edit: NodeEdit) => Promise<void>;
  pageKey?: string;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  tellState = useNodeBridge(frame, {
    mode: mode ?? (commenting ? "comment" : "view"),
    labels: LABELS,
    onComment,
    onRemove,
    onEdit,
    pageKey,
  });
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

  it("takes a comment in and tells the page that it waits for Send", async () => {
    const onComment = vi.fn(async (_comment: NodeComment) => undefined);
    render(<Harness commenting onComment={onComment} />);
    const frame = screen.getByTestId("frame") as HTMLIFrameElement;
    const posted = vi.spyOn(frame.contentWindow as Window, "postMessage");

    fromFrame({ type: NODE_COMMENT_MESSAGE, n: 1, text: "Make this shorter", quote: "Intro", where: "§ Intro" });
    await flush();
    expect(onComment).toHaveBeenCalledWith({ n: 1, text: "Make this shorter", quote: "Intro", where: "§ Intro" });
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_COMMENT_STATE_MESSAGE, n: 1, state: "pending" }, "*");

    // Later, once the batch went out, the app tells each pin.
    act(() => tellState?.([1, 2], "sent"));
    expect(posted).toHaveBeenCalledWith({ type: NODE_COMMENT_STATE_MESSAGE, n: 1, state: "sent" }, "*");
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_COMMENT_STATE_MESSAGE, n: 2, state: "sent" }, "*");
  });

  it("hears a comment taken back", () => {
    const onRemove = vi.fn();
    render(<Harness commenting onComment={vi.fn(async () => undefined)} onRemove={onRemove} />);
    fromFrame({ type: NODE_COMMENT_REMOVE_MESSAGE, n: 2 });
    fromFrame({ type: NODE_COMMENT_REMOVE_MESSAGE, n: "2" });
    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledWith(2);
  });

  it("tells the page when a comment could not be taken", async () => {
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

describe("parseNodeEdit", () => {
  it("takes a typed value with its place and kind", () => {
    expect(parseNodeEdit({ type: NODE_EDIT_MESSAGE, id: 4, path: "/rows/0/price", value: "40,62", as: "number" })).toEqual({
      id: 4,
      path: "/rows/0/price",
      value: "40,62",
      as: "number",
      refresh: false,
    });
    expect(parseNodeEdit({ type: NODE_EDIT_MESSAGE, id: 1, path: "@title", value: "Plan", refresh: true })).toEqual({
      id: 1,
      path: "@title",
      value: "Plan",
      as: "text",
      refresh: true,
    });
    expect(parseNodeEdit({ type: NODE_EDIT_MESSAGE, id: 2, path: "/a/0/done", value: true, as: "toggle" })?.value).toBe(true);
  });

  it("refuses what is not one", () => {
    expect(parseNodeEdit({ type: NODE_EDIT_MESSAGE, id: 1, path: "rows/0", value: "x" })).toBeNull();
    expect(parseNodeEdit({ type: NODE_EDIT_MESSAGE, id: 0, path: "/a", value: "x" })).toBeNull();
    expect(parseNodeEdit({ type: NODE_EDIT_MESSAGE, id: 1, path: "/a", value: 3 })).toBeNull();
    expect(parseNodeEdit({ type: NODE_EDIT_MESSAGE, id: 1, path: "/a", value: "x", as: "toggle" })).toBeNull();
    expect(parseNodeEdit({ type: NODE_EDIT_MESSAGE, id: 1, path: "/a", value: "x".repeat(200001) })).toBeNull();
    expect(parseNodeEdit({ type: NODE_COMMENT_MESSAGE, id: 1, path: "/a", value: "x" })).toBeNull();
  });
});

describe("useNodeBridge: editing", () => {
  it("saves an edit only while the reader is editing, and tells the page how it went", async () => {
    const onEdit = vi.fn(async (_edit: NodeEdit) => undefined);
    const view = render(<Harness mode="view" onEdit={onEdit} />);
    const frame = screen.getByTestId("frame") as HTMLIFrameElement;
    const posted = vi.spyOn(frame.contentWindow as Window, "postMessage");
    const edit = { type: NODE_EDIT_MESSAGE, id: 1, path: "/summary", value: "Shorter", as: "text" };

    // A page cannot write into its node on its own.
    fromFrame(edit);
    await flush();
    expect(onEdit).not.toHaveBeenCalled();
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_EDIT_STATE_MESSAGE, id: 1, state: "failed" }, "*");

    view.rerender(<Harness mode="edit" onEdit={onEdit} />);
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_MODE_MESSAGE, mode: "edit", labels: LABELS }, "*");
    fromFrame({ ...edit, id: 2 });
    await flush();
    expect(onEdit).toHaveBeenCalledWith({ id: 2, path: "/summary", value: "Shorter", as: "text", refresh: false });
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_EDIT_STATE_MESSAGE, id: 2, state: "saved" }, "*");

    onEdit.mockRejectedValueOnce(new Error("refused"));
    fromFrame({ ...edit, id: 3 });
    await flush();
    await flush();
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_EDIT_STATE_MESSAGE, id: 3, state: "failed" }, "*");
  });

  it("brings a page drawn again back to where it was scrolled, until another page opens", () => {
    const view = render(<Harness mode="edit" pageKey="a" />);
    const frame = screen.getByTestId("frame") as HTMLIFrameElement;
    const posted = vi.spyOn(frame.contentWindow as Window, "postMessage");

    fromFrame({ type: NODE_SCROLL_MESSAGE, x: 0, y: 840 });
    fromFrame({ type: NODE_READY_MESSAGE });
    expect(posted).toHaveBeenLastCalledWith(
      { type: NODE_MODE_MESSAGE, mode: "edit", labels: LABELS, scroll: { x: 0, y: 840 } },
      "*",
    );

    // A page that keeps its place in the hash (a deck's slide) gets it back too.
    fromFrame({ type: NODE_SCROLL_MESSAGE, x: 0, y: 0, hash: "#7" });
    fromFrame({ type: NODE_READY_MESSAGE });
    expect(posted).toHaveBeenLastCalledWith(
      { type: NODE_MODE_MESSAGE, mode: "edit", labels: LABELS, scroll: { x: 0, y: 0, hash: "#7" } },
      "*",
    );
    fromFrame({ type: NODE_SCROLL_MESSAGE, x: 0, y: 0, hash: "javascript:alert(1)" });
    fromFrame({ type: NODE_READY_MESSAGE });
    expect(posted).toHaveBeenLastCalledWith(
      { type: NODE_MODE_MESSAGE, mode: "edit", labels: LABELS, scroll: { x: 0, y: 0 } },
      "*",
    );

    view.rerender(<Harness mode="edit" pageKey="b" />);
    fromFrame({ type: NODE_READY_MESSAGE });
    expect(posted).toHaveBeenLastCalledWith({ type: NODE_MODE_MESSAGE, mode: "edit", labels: LABELS }, "*");
  });
});
