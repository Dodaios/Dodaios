/**
 * The editor draws slides exactly as the deck page does, and its fields
 * write into the deck.
 *
 * `__fixtures__/slides_markup.json` is the page's own markup of one slide of
 * every shape, written by `tests/unit/nodes/test_kind_slides.py` (which
 * fails when the page changes and the fixture is stale). Each slide drawn by
 * `SlideView` must be the same tree: same elements, classes, size steps and
 * texts.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";

import fixture from "./__fixtures__/slides_markup.json";
import { readDeck, type Slide } from "./deckModel";
import { esc, inlineHtml, linesHtml } from "./inline";
import { sectionNumber, SlideEditingProvider, SlideView, type SlideEditing } from "./SlideView";

/** A tree as a string that ignores attribute order and the style attribute's spacing. */
function canonical(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return esc(node.textContent ?? "");
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const el = node as Element;
  const attrs = Array.from(el.attributes)
    .map((a) => `${a.name}="${a.name === "style" ? a.value.replace(/\s+/g, "") : a.value}"`)
    .sort()
    .join(" ");
  const inner = Array.from(el.childNodes).map(canonical).join("");
  return `<${el.tagName.toLowerCase()}${attrs ? ` ${attrs}` : ""}>${inner}</${el.tagName.toLowerCase()}>`;
}

function tree(html: string): string {
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  return Array.from(doc.body.childNodes).map(canonical).join("");
}

afterEach(() => cleanup());

describe("SlideView draws the page's markup", () => {
  const deck = readDeck(fixture.spec);
  const entries = fixture.slides as { html: string; figure?: string }[];

  it("has a fixture slide for every slide of the deck", () => {
    expect(deck.slides.length).toBe(entries.length);
    expect(new Set(deck.slides.map((s) => s.layout)).size).toBe(11);
  });

  deck.slides.forEach((slide, index) => {
    it(`slide ${index + 1} (${slide.layout})`, () => {
      const html = renderToStaticMarkup(
        <SlideView
          slide={slide}
          index={index}
          deckTitle={fixture.title}
          section={sectionNumber(deck.slides, index)}
          figure={entries[index].figure ?? null}
        />,
      );
      expect(tree(html)).toBe(tree(entries[index].html));
    });
  });
});

describe("inline marks", () => {
  it("escapes first and keeps only safe marks", () => {
    expect(inlineHtml("**Bold** and *it* `x<y` [l](https://a.org?q=1&b=2)")).toBe(
      '<strong>Bold</strong> and <em>it</em> <code>x&lt;y</code> <a href="https://a.org?q=1&amp;b=2" rel="noopener noreferrer">l</a>',
    );
    // As the server reads it: the address stops at the first ")", and no tag survives.
    expect(inlineHtml("[bad](javascript:alert(1)) <img src=x>")).toBe("bad) &lt;img src=x&gt;");
    expect(inlineHtml("a\u0000b")).toBe("ab");
    expect(inlineHtml("snake_case *café*")).toBe("snake_case <em>café</em>");
    expect(linesHtml("one\r\n**two**")).toBe("one<br><strong>two</strong>");
  });
});

function editing(over: Partial<SlideEditing> = {}): SlideEditing {
  return {
    setText: vi.fn(),
    splitItem: vi.fn(),
    removeItem: vi.fn(),
    undo: vi.fn(),
    redo: vi.fn(),
    breakRun: vi.fn(),
    focusRequest: null,
    clearFocusRequest: vi.fn(),
    placeholder: (field) => `ph:${field}`,
    onFieldFocus: vi.fn(),
    ...over,
  };
}

function renderEditable(slide: Slide, context: SlideEditing) {
  const view = render(
    <SlideEditingProvider value={context}>
      <SlideView slide={slide} index={1} deckTitle="Deck" section={1} />
    </SlideEditingProvider>,
  );
  const field = (key: string) => view.container.querySelector<HTMLElement>(`[data-field="${key}"]`)!;
  return { ...view, field };
}

describe("SlideView fields", () => {
  const slide: Slide = { layout: "bullets", title: "Plan", text: "**Why**", bullets: ["One", ""] };

  it("makes every text a field, with prompts for empty ones", () => {
    const { field } = renderEditable(slide, editing());
    expect(field("title").textContent).toBe("Plan");
    expect(field("title").getAttribute("contenteditable")).toBe("plaintext-only");
    expect(field("text").innerHTML).toBe("<strong>Why</strong>");
    expect(field("bullets/1").getAttribute("data-placeholder")).toBe("ph:bullets");
  });

  it("shows a rich field's source while it is written and its marks after", () => {
    const context = editing();
    const { field } = renderEditable(slide, context);
    act(() => field("text").focus());
    expect(field("text").textContent).toBe("**Why**");
    expect(context.onFieldFocus).toHaveBeenCalledWith(["text"]);
    act(() => field("text").blur());
    expect(field("text").innerHTML).toBe("<strong>Why</strong>");
    expect(context.onFieldFocus).toHaveBeenLastCalledWith(null);
  });

  it("reports typing, one line, cut to the field's limit", () => {
    const context = editing();
    const { field } = renderEditable(slide, context);
    const title = field("title");
    title.textContent = "New\ntitle";
    fireEvent.input(title);
    expect(context.setText).toHaveBeenLastCalledWith(["title"], "New title");
    title.textContent = "x".repeat(200);
    fireEvent.input(title);
    expect(context.setText).toHaveBeenLastCalledWith(["title"], "x".repeat(110));
  });

  it("splits a point on Enter, removes an empty one on Backspace, and hands undo to the deck", () => {
    const context = editing();
    const { field } = renderEditable(slide, context);
    fireEvent.keyDown(field("bullets/0"), { key: "Enter" });
    expect(context.splitItem).toHaveBeenCalledWith(["bullets", 0]);
    const empty = field("bullets/1");
    act(() => empty.focus());
    const range = document.createRange();
    range.selectNodeContents(empty);
    range.collapse(true);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.keyDown(empty, { key: "Backspace" });
    expect(context.removeItem).toHaveBeenCalledWith(["bullets", 1]);
    fireEvent.keyDown(field("title"), { key: "z", metaKey: true });
    expect(context.undo).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(field("title"), { key: "z", metaKey: true, shiftKey: true });
    expect(context.redo).toHaveBeenCalledTimes(1);
  });

  it("keeps an emptied optional text drawn while editing, and leaves it out on the page", () => {
    const withKicker: Slide = { layout: "title", title: "T", kicker: "" };
    const { field } = renderEditable(withKicker, editing());
    expect(field("kicker")).toBeTruthy();
    const page = renderToStaticMarkup(<SlideView slide={withKicker} index={0} deckTitle="Deck" section={0} />);
    expect(page).not.toContain("sl-kicker");
  });

  it("focuses the field a new slide or point asks for", () => {
    const clear = vi.fn();
    const { field } = renderEditable(slide, editing({ focusRequest: { key: "title", select: "all" }, clearFocusRequest: clear }));
    expect(document.activeElement).toBe(field("title"));
    expect(window.getSelection()?.toString()).toBe("Plan");
    expect(clear).toHaveBeenCalled();
  });
});
