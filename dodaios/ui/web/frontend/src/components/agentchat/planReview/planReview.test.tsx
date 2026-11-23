/**
 * A plan under review: the window edits the plan's Markdown without restyling
 * what was not touched, comments stay with the words they are about, and what
 * the person did is exactly what the card's answer carries.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { getSchema, type Editor } from "@tiptap/core";
import { Node as ProseNode } from "@tiptap/pm/model";

import { docExtensions } from "@/components/nodes/editors/docs/extensions";
import { DocMarkdown } from "@/components/nodes/editors/docs/markdown/document";
import PlanReviewDialog from "./PlanReviewDialog";
import { PlanDraftMarks, PlanReviewButton } from "./PlanReviewButton";
import { findQuote, inReadingOrder, planText, quoteBetween, rangesOf } from "./planComments";
import { EMPTY_DRAFT, PLAN_DRAFTS_KEY, loadPlanDrafts, planAnswer, planDraftOf, reviewOf, usePlanDrafts } from "./planDraft";

vi.mock("@/i18n", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/i18n")>();
  return { ...actual, useT: () => (key: string) => key, useUiLanguage: () => "en" };
});

// jsdom lays nothing out; ProseMirror asks for rectangles when it scrolls the caret into view.
const rect = () => ({ x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, toJSON: () => ({}) });
Range.prototype.getBoundingClientRect = rect as unknown as () => DOMRect;
Range.prototype.getClientRects = (() => ({ length: 0, item: () => null, [Symbol.iterator]: function* () {} })) as unknown as () => DOMRectList;
document.elementFromPoint = (() => null) as typeof document.elementFromPoint;
Element.prototype.scrollIntoView = () => {};

const PLAN = [
  "# Plan: add a database",
  "",
  "## Steps",
  "",
  "1. Add the table in `db/schema.sql`",
  "2. Wire the route",
  "",
  "* Keep the old route   alive",
  "* Wire the route",
].join("\n");

function docOf(markdown: string): ProseNode {
  const schema = getSchema(docExtensions({ summary: false }));
  return ProseNode.fromJSON(schema, new DocMarkdown(markdown).doc);
}

beforeEach(() => {
  localStorage.clear();
  usePlanDrafts.setState({ drafts: {} });
});

afterEach(() => {
  cleanup();
});

describe("comments anchored to the plan's words", () => {
  it("finds a passage again, and the right one of two equal passages", () => {
    const map = planText(docOf(PLAN));
    expect(map.text).toContain("Add the table in db/schema.sql");
    const first = map.text.indexOf("Wire the route");
    const second = map.text.indexOf("Wire the route", first + 1);
    expect(second).toBeGreaterThan(first);
    expect(findQuote(map, { quote: "Wire the route", at: first })?.from).toBe(first);
    expect(findQuote(map, { quote: "Wire the route", at: second + 3 })?.from).toBe(second);
    expect(findQuote(map, { quote: "not in the plan", at: 0 })).toBeNull();
  });

  it("marks a passage that runs across code and plain text, one range per stretch", () => {
    const doc = docOf(PLAN);
    const map = planText(doc);
    const found = findQuote(map, { quote: "table in db/schema.sql", at: 0 })!;
    const ranges = rangesOf(map, found.from, found.to);
    expect(ranges.length).toBe(2);
    expect(ranges.map((range) => doc.textBetween(range.from, range.to)).join("")).toBe("table in db/schema.sql");
  });

  it("keeps the selected words as the quote, trimmed, with where they start", () => {
    const doc = docOf(PLAN);
    const map = planText(doc);
    const start = map.text.indexOf("Wire the route");
    const [range] = rangesOf(map, start - 1, start + "Wire the route".length);
    const { quote, at } = quoteBetween(map, range.from, range.to + 100);
    expect(quote.startsWith("Wire the route")).toBe(true);
    expect(at).toBeGreaterThanOrEqual(start - 1);
  });

  it("lists comments in the order their passages stand in the plan", () => {
    const map = planText(docOf(PLAN));
    const comments = [
      { id: "b", quote: "Keep the old route", at: 0, text: "" },
      { id: "gone", quote: "deleted words", at: 0, text: "" },
      { id: "a", quote: "Add the table", at: 0, text: "" },
    ];
    expect(inReadingOrder(map, comments).map((comment) => comment.id)).toEqual(["a", "b", "gone"]);
  });
});

describe("what a plan card's answer carries", () => {
  it("is nothing for an untouched plan", () => {
    expect(reviewOf(EMPTY_DRAFT, true)).toBeUndefined();
    expect(planAnswer("card", "allow")).toEqual({});
    expect(planAnswer("card", "deny")).toEqual({});
  });

  it("sends a typed note alone as the plain reason when planning goes on, and as a note when building", () => {
    usePlanDrafts.getState().patch("card", { note: "  smaller steps " });
    expect(planAnswer("card", "deny")).toEqual({ feedback: "smaller steps" });
    expect(planAnswer("card", "allow")).toEqual({ review: { note: "smaller steps" } });
  });

  it("sends edits and written comments, and drops a comment left empty", () => {
    usePlanDrafts.getState().patch("card", {
      plan: "# New plan",
      note: "ok",
      comments: [
        { id: "1", quote: "Wire the route", at: 4, text: " which one? " },
        { id: "2", quote: "Steps", at: 1, text: "   " },
      ],
    });
    const review = { plan: "# New plan", comments: [{ quote: "Wire the route", text: "which one?" }], note: "ok" };
    expect(planAnswer("card", "deny")).toEqual({ review });
    expect(planAnswer("card", "allow")).toEqual({ review });
  });
});

describe("a draft that outlives the window", () => {
  it("is kept in the browser and read back after a reload", () => {
    usePlanDrafts.getState().patch("card", { plan: "# New plan", comments: [{ id: "1", quote: "Steps", at: 3, text: "why?" }] });
    const kept = loadPlanDrafts();
    expect(kept.card).toMatchObject({ plan: "# New plan", note: "", comments: [{ id: "1", quote: "Steps", at: 3, text: "why?" }] });
    // Answered: nothing of it stays behind.
    usePlanDrafts.getState().clear("card");
    expect(localStorage.getItem(PLAN_DRAFTS_KEY)).toBeNull();
  });

  it("forgets a draft the person emptied again, an old one, and anything unreadable", () => {
    usePlanDrafts.getState().patch("card", { note: "x" });
    usePlanDrafts.getState().patch("card", { note: "" });
    expect(usePlanDrafts.getState().drafts.card).toBeUndefined();
    expect(localStorage.getItem(PLAN_DRAFTS_KEY)).toBeNull();
    const month = 31 * 24 * 60 * 60 * 1000;
    localStorage.setItem(PLAN_DRAFTS_KEY, JSON.stringify({
      old: { plan: "# Old", comments: [], note: "", savedMs: Date.now() - month },
      fresh: { plan: null, comments: [{ id: "1", quote: "a", text: "b" }, { nonsense: true }], note: 7, savedMs: Date.now() },
    }));
    expect(loadPlanDrafts()).toEqual({ fresh: { plan: null, comments: [{ id: "1", quote: "a", at: 0, text: "b" }], note: "", savedMs: expect.any(Number) } });
    localStorage.setItem(PLAN_DRAFTS_KEY, "not json");
    expect(loadPlanDrafts()).toEqual({});
  });

  it("keeps only the newest few", () => {
    for (let index = 0; index < 12; index += 1) usePlanDrafts.getState().patch(`card-${index}`, { note: `note ${index}` });
    const kept = Object.keys(loadPlanDrafts());
    expect(kept.length).toBe(8);
    expect(kept).toContain("card-11");
  });
});

function mountWindow(onAnswer?: (answer: "build" | "keep") => void) {
  render(<PlanReviewDialog cardId="card" plan={PLAN} open onOpenChange={() => {}} onAnswer={onAnswer} />);
  const dom = screen.getByTestId("plan-review-text") as HTMLElement & { editor: Editor };
  return dom.editor;
}

function select(editor: Editor, text: string) {
  const map = planText(editor.state.doc);
  const start = map.text.indexOf(text);
  if (start < 0) throw new Error(`not found: ${text}`);
  const ranges = rangesOf(map, start, start + text.length);
  act(() => {
    editor.commands.setTextSelection({ from: ranges[0].from, to: ranges[ranges.length - 1].to });
  });
}

describe("the plan review window", () => {
  it("shows the plan as a document, with no summary line", () => {
    const editor = mountWindow(() => {});
    const text = screen.getByTestId("plan-review-text");
    expect(text.querySelector("h1")?.textContent).toBe("Plan: add a database");
    expect(text.querySelectorAll("ol > li").length).toBe(2);
    expect(text.querySelector("[data-doc-summary]")).toBeNull();
    expect(editor.isEditable).toBe(true);
    // Nothing is a draft until the person does something.
    expect(planDraftOf("card")).toEqual(EMPTY_DRAFT);
  });

  it("keeps untouched blocks exactly as the agent wrote them when one line changes", () => {
    const editor = mountWindow(() => {});
    select(editor, "Wire the route");
    act(() => {
      editor.commands.insertContent("Wire the new route");
    });
    const edited = planDraftOf("card").plan!;
    expect(edited).toContain("Wire the new route");
    // The bullet list below, with its own marker and odd spacing, is untouched.
    expect(edited).toContain("* Keep the old route   alive");
    expect(edited.startsWith("# Plan: add a database\n\n## Steps")).toBe(true);
    expect(screen.getByTestId("plan-review-marks").textContent).toBe("plan_review.edited");
    // Undoing brings back the agent's own text: nothing is edited any more.
    act(() => {
      editor.commands.undo();
    });
    expect(planDraftOf("card").plan).toBeNull();
    expect(screen.queryByTestId("plan-review-marks")).toBeNull();
  });

  it("puts the agent's plan back with one click", () => {
    const editor = mountWindow(() => {});
    select(editor, "Steps");
    act(() => {
      editor.commands.insertContent("Phases");
    });
    expect(planDraftOf("card").plan).toContain("## Phases");
    fireEvent.click(screen.getByTestId("plan-review-reset"));
    expect(planDraftOf("card").plan).toBeNull();
    expect(screen.getByTestId("plan-review-text").querySelector("h2")?.textContent).toBe("Steps");
  });

  it("comments on the selected passage and marks it in the text", async () => {
    const editor = mountWindow(() => {});
    expect((screen.getByTestId("plan-review-comment") as HTMLButtonElement).disabled).toBe(true);
    select(editor, "Add the table");
    fireEvent.click(screen.getByTestId("plan-review-comment"));
    const field = await screen.findByTestId("plan-comment-text");
    await waitFor(() => expect(document.activeElement).toBe(field));
    fireEvent.change(field, { target: { value: "Which table?" } });
    expect(planDraftOf("card").comments).toMatchObject([{ quote: "Add the table", text: "Which table?" }]);
    const marks = screen.getByTestId("plan-review-text").querySelectorAll(".plan-comment-mark");
    expect(Array.from(marks).map((mark) => mark.textContent).join("")).toBe("Add the table");
    expect(screen.getByTestId("plan-review-marks").textContent).toBe("plan_review.comments_one");
    // A comment left without a word is dropped again.
    select(editor, "Wire the route");
    fireEvent.click(screen.getByTestId("plan-review-comment"));
    await waitFor(() => expect(screen.getAllByTestId("plan-comment-text").length).toBe(2));
    const empty = screen.getAllByTestId("plan-comment-text").find((el) => (el as HTMLTextAreaElement).value === "")!;
    fireEvent.blur(empty);
    expect(planDraftOf("card").comments.length).toBe(1);
  });

  it("opens again on what the person left: their text and their comments", () => {
    usePlanDrafts.getState().patch("card", {
      plan: PLAN.replace("Wire the route\n\n", "Wire the new route\n\n"),
      comments: [{ id: "1", quote: "Add the table", at: 0, text: "Which table?" }],
      note: "smaller",
    });
    mountWindow(() => {});
    const text = screen.getByTestId("plan-review-text");
    expect(text.textContent).toContain("Wire the new route");
    expect(text.querySelector(".plan-comment-mark")?.textContent).toBe("Add the table");
    expect((screen.getByTestId("plan-comment-text") as HTMLTextAreaElement).value).toBe("Which table?");
    expect((screen.getByTestId("plan-review-note") as HTMLTextAreaElement).value).toBe("smaller");
  });

  it("answers from the window", () => {
    const answers: string[] = [];
    mountWindow((answer) => answers.push(answer));
    fireEvent.click(screen.getByTestId("plan-review-keep"));
    fireEvent.click(screen.getByTestId("plan-review-build"));
    expect(answers).toEqual(["keep", "build"]);
  });

  it("only shows the plan where the card cannot be answered", () => {
    const editor = mountWindow();
    expect(editor.isEditable).toBe(false);
    expect(screen.queryByTestId("plan-review-build")).toBeNull();
    expect(screen.queryByTestId("plan-review-rail")).toBeNull();
    expect(screen.queryByTestId("plan-review-comment")).toBeNull();
  });
});

describe("a window newer than its backend", () => {
  it("keeps the plan read only and says why, so no edit is made that would be lost", async () => {
    render(<PlanReviewButton cardId="card" plan={PLAN} supported={false} onAnswer={() => {}} />);
    fireEvent.click(screen.getByTestId("plan-review-open"));
    const text = (await screen.findByTestId("plan-review-text", undefined, { timeout: 15000 })) as HTMLElement & { editor: Editor };
    expect(text.editor.isEditable).toBe(false);
    expect(screen.queryByTestId("plan-review-build")).toBeNull();
    expect(screen.getByTestId("plan-review-read-only").textContent).toBe("plan_review.needs_restart");
  }, 20000);
});

describe("the way into the window from a plan card", () => {
  it("opens the window and says what the person did to the plan", async () => {
    render(<>
      <PlanReviewButton cardId="card" plan={PLAN} supported onAnswer={() => {}} />
      <PlanDraftMarks cardId="card" />
    </>);
    expect(screen.queryByTestId("plan-draft-marks")).toBeNull();
    expect(screen.queryByTestId("plan-review")).toBeNull();
    fireEvent.click(screen.getByTestId("plan-review-open"));
    const text = (await screen.findByTestId("plan-review-text", undefined, { timeout: 15000 })) as HTMLElement & { editor: Editor };
    select(text.editor, "Steps");
    act(() => {
      text.editor.commands.insertContent("Phases");
    });
    expect(screen.getByTestId("plan-draft-marks").textContent).toBe("plan_review.edited");
  }, 20000);
});
