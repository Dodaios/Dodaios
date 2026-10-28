import { describe, expect, it } from "vitest";
import { parseApprovalCard } from "./approvalInfo";
import { approvalTitle } from "./approvalCopy";

const t = (key: string) => key;
const card = (extra: Record<string, unknown> = {}) => parseApprovalCard({
  source: { kind: "files", app: "", verb: "" }, where: "", where_full: "", why: "", caution: "", detail: "", brief: "", rule: null, ...extra,
})!;

describe("a file approval's question", () => {
  it("asks to create a file that does not exist yet", () => {
    expect(card({ creates: true }).creates).toBe(true);
    expect(approvalTitle(card({ creates: true }), t)).toBe("action_card.title.files_create");
  });

  it("asks to change a file that is already there", () => {
    expect(card().creates).toBeUndefined();
    expect(approvalTitle(card(), t)).toBe("action_card.title.files");
  });
});
