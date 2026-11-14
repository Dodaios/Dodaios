import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ComposerChipField, type ComposerChipFieldHandle } from "./ComposerChipField";
import type { ToolChoice } from "./toolChoices";

const gmail: ToolChoice = {
  id: "plugin:gmail",
  label: "Gmail",
  brand: "gmail",
  category: "plugins",
  group: "Gmail",
  description: "Mail",
  available: true,
  tool_names: ["gmail"],
  skill: "",
};

describe("ComposerChipField", () => {
  it("puts a plugin chip in the sentence at the caret", () => {
    const handle = createRef<ComposerChipFieldHandle>();
    render(
      <ComposerChipField
        ref={handle}
        placeholder="Message"
        onSubmit={() => {}}
        onDraftChange={() => {}}
      />,
    );
    handle.current?.hydrate("I am  now", []);
    handle.current?.hydrate("I am @gmail now", [gmail]);
    const field = screen.getByTestId("composer-chip-field");
    expect(field.querySelector('[data-brand="gmail"]')?.textContent).toContain("Gmail");
    expect(handle.current?.getDraft().text).toContain("@gmail");
    expect(handle.current?.getDraft().choices.map((row) => row.id)).toEqual(["plugin:gmail"]);
  });

  it("inserts the chip at the typing caret, not the start of the field", () => {
    const handle = createRef<ComposerChipFieldHandle>();
    render(
      <ComposerChipField
        ref={handle}
        placeholder="Message"
        onSubmit={() => {}}
        onDraftChange={() => {}}
      />,
    );
    const field = screen.getByTestId("composer-chip-field");
    handle.current?.setText("Hello, this is Ruben");
    field.focus();
    const range = document.createRange();
    range.selectNodeContents(field);
    range.collapse(false);
    const sel = document.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));

    handle.current?.insertChip(gmail);

    const draft = handle.current!.getDraft();
    expect(field.firstChild?.textContent).toContain("Hello, this is Ruben");
    expect(field.querySelector('[data-brand="gmail"]')).not.toBeNull();
    expect(draft.text.startsWith("Hello, this is Ruben")).toBe(true);
    expect(draft.text).toContain("@gmail");
    expect(draft.caret).toBeGreaterThan(draft.text.indexOf("@gmail"));
  });

  it("keeps a chip when the text around it is replaced", () => {
    // A dictation rewrites the box with every reading of the words so far.
    const handle = createRef<ComposerChipFieldHandle>();
    const drafts = vi.fn();
    render(<ComposerChipField ref={handle} placeholder="Message" onSubmit={() => {}} onDraftChange={drafts} />);
    handle.current?.hydrate("Ask @gmail", [gmail]);

    handle.current?.setText("Ask @gmail for the invoice");

    const field = screen.getByTestId("composer-chip-field");
    expect(field.querySelector('[data-brand="gmail"]')).not.toBeNull();
    expect(handle.current?.getDraft().text).toBe("Ask @gmail for the invoice");
    expect(handle.current?.getDraft().choices.map((row) => row.id)).toEqual(["plugin:gmail"]);
    expect(drafts.mock.lastCall?.[0].choices.map((row: ToolChoice) => row.id)).toEqual(["plugin:gmail"]);

    handle.current?.setText("Ask for the invoice");
    expect(handle.current?.getDraft().choices).toEqual([]);
  });

  it("keeps an already selected connector to one chip", () => {
    const handle = createRef<ComposerChipFieldHandle>();
    render(<ComposerChipField ref={handle} placeholder="Message" onSubmit={() => {}} onDraftChange={() => {}} />);
    handle.current?.insertChip(gmail);
    handle.current?.insertChip(gmail);
    expect(handle.current?.getDraft().choices.map((row) => row.id)).toEqual(["plugin:gmail"]);
  });

  it("sends selection changes only to the current draft owner after switching sessions", () => {
    const handle = createRef<ComposerChipFieldHandle>();
    const blank = vi.fn();
    const assigned = vi.fn();
    const { rerender } = render(
      <ComposerChipField ref={handle} placeholder="Message" onSubmit={() => {}} onDraftChange={blank} />,
    );
    handle.current?.hydrate("Followup draft");
    blank.mockClear();
    rerender(
      <ComposerChipField ref={handle} placeholder="Message" onSubmit={() => {}} onDraftChange={assigned} />,
    );
    document.dispatchEvent(new Event("selectionchange"));
    expect(blank).not.toHaveBeenCalled();
    expect(assigned).toHaveBeenCalledWith(expect.objectContaining({ text: "Followup draft" }));
  });
});

/**
 * The words a seat acts on are painted with the CSS Custom Highlight API.
 * jsdom has none, so a stand-in registry records what the field hands it.
 */
describe("ComposerChipField token colour", () => {
  class FakeHighlight {
    ranges: Range[];
    constructor(...ranges: Range[]) {
      this.ranges = ranges;
    }
  }
  const registry = new Map<string, FakeHighlight>();
  const painted = () => (registry.get("composer-token")?.ranges ?? []).map((range) => range.toString());
  const slashOnly = (text: string) => (text.startsWith("/goal") ? [{ start: 0, end: 5 }] : []);

  function withHighlightApi() {
    registry.clear();
    vi.stubGlobal("Highlight", FakeHighlight);
    vi.stubGlobal("CSS", { highlights: registry });
  }

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("paints the stretches it is given and clears them when the text changes", () => {
    withHighlightApi();
    const handle = createRef<ComposerChipFieldHandle>();
    render(
      <ComposerChipField ref={handle} placeholder="Message" onSubmit={() => {}} onDraftChange={() => {}} tokenSpans={slashOnly} />,
    );
    handle.current?.setText("/goal ship it");
    expect(painted()).toEqual(["/goal"]);
    // The text itself is untouched: no wrapper element, one plain text node.
    const field = screen.getByTestId("composer-chip-field");
    expect(field.children).toHaveLength(0);
    expect(handle.current?.getDraft().text).toBe("/goal ship it");

    handle.current?.setText("ship it");
    expect(registry.has("composer-token")).toBe(false);
  });

  it("counts a chip as its @tag, so a word after a chip is painted in the right place", () => {
    withHighlightApi();
    const handle = createRef<ComposerChipFieldHandle>();
    const afterChip = (text: string) => {
      const at = text.indexOf("$deploy");
      return at < 0 ? [] : [{ start: at, end: at + 7 }];
    };
    render(
      <ComposerChipField ref={handle} placeholder="Message" onSubmit={() => {}} onDraftChange={() => {}} tokenSpans={afterChip} />,
    );
    handle.current?.hydrate("ask @gmail then $deploy now", [gmail]);
    expect(handle.current?.getDraft().text).toBe("ask @gmail then $deploy now");
    expect(painted()).toEqual(["$deploy"]);
  });

  it("repaints when the seat's list arrives after the text, and lets go on unmount", () => {
    withHighlightApi();
    const handle = createRef<ComposerChipFieldHandle>();
    const props = { ref: handle, placeholder: "Message", onSubmit: () => {}, onDraftChange: () => {} };
    const view = render(<ComposerChipField {...props} tokenSpans={() => []} />);
    handle.current?.setText("/goal ship it");
    expect(painted()).toEqual([]);
    view.rerender(<ComposerChipField {...props} tokenSpans={slashOnly} />);
    expect(painted()).toEqual(["/goal"]);
    view.unmount();
    expect(registry.has("composer-token")).toBe(false);
  });

  it("works unpainted where the web view has no highlight API", () => {
    const handle = createRef<ComposerChipFieldHandle>();
    render(
      <ComposerChipField ref={handle} placeholder="Message" onSubmit={() => {}} onDraftChange={() => {}} tokenSpans={slashOnly} />,
    );
    handle.current?.setText("/goal ship it");
    expect(handle.current?.getDraft().text).toBe("/goal ship it");
  });
});
