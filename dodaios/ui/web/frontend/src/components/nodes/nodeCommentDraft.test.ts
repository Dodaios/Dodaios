/**
 * The waiting comments: they collect, go out together, and a failed send
 * keeps them for another try.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ sendNodeComments: vi.fn(async (_card: unknown, _comments: unknown) => undefined) }));
vi.mock("./askDodaios", () => api);

import { useNodeCommentDraft } from "./nodeCommentDraft";
import type { NodeCard } from "./nodeModel";

const CARD = { id: "n-1", key: "node:n-1", title: "Brief" } as unknown as NodeCard;
const draft = () => useNodeCommentDraft.getState();
const comment = (n: number, text = `comment ${n}`) => ({ n, text, quote: "", where: "" });

beforeEach(() => {
  draft().open(null);
  draft().open("n-1");
});

afterEach(() => vi.clearAllMocks());

describe("useNodeCommentDraft", () => {
  it("collects comments, drops one taken back, and sends the rest in pin order", async () => {
    draft().add(comment(2));
    draft().add(comment(1));
    draft().add(comment(3));
    draft().remove(3);
    expect(await draft().sendAll(CARD)).toBe(true);
    expect(api.sendNodeComments).toHaveBeenCalledWith(CARD, [comment(1), comment(2)]);
    expect(draft().pending).toEqual([]);
    expect(draft().working).toBe(2);
    expect(draft().outcome).toMatchObject({ ns: [1, 2], state: "sent" });
    draft().settle();
    expect(draft().working).toBe(0);
  });

  it("keeps the comments when they could not be sent", async () => {
    api.sendNodeComments.mockRejectedValueOnce(new Error("offline"));
    draft().add(comment(1));
    expect(await draft().sendAll(CARD)).toBe(false);
    expect(draft().pending).toEqual([comment(1)]);
    expect(draft().sending).toBe(false);
    expect(draft().outcome).toMatchObject({ ns: [1], state: "failed" });
  });

  it("sends nothing when nothing waits, and starts empty on another node", async () => {
    expect(await draft().sendAll(CARD)).toBe(false);
    expect(api.sendNodeComments).not.toHaveBeenCalled();
    draft().add(comment(1));
    draft().open("n-1");
    expect(draft().pending).toHaveLength(1);
    draft().open("n-2");
    expect(draft().pending).toEqual([]);
  });
});
