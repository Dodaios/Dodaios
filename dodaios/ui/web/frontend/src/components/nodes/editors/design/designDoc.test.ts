/**
 * A design's markup as an editable tree, and the preview frame's messages.
 *
 * Contracts worth pinning:
 * - markup survives a parse and write unchanged (SVG spelling included),
 * - the layers are the visible elements; a drawing and a text with inline
 *   marks are one layer each,
 * - every structural change addresses elements by the same path the
 *   preview frame uses, and returns the path to select next,
 * - a new block lands after the selection, or inside a design's one wrapper,
 * - text typed in place can change words and inline marks, never structure,
 * - a message from the frame is only taken when every field checks out.
 */
import { describe, expect, it } from "vitest";

import {
  duplicateElement,
  editMarkup,
  elementAt,
  insertBlock,
  insertionPoint,
  isPlainText,
  isTextElement,
  layersOf,
  moveElement,
  moveElementTo,
  parseDesign,
  plainTextOf,
  readDesignSpec,
  removeElement,
  serialize,
  setInlineMarkup,
  setPlainText,
  setStyle,
  styleOf,
} from "./designDoc";
import { PICKER_SOURCE, pickerScript, readPickerMessage } from "./picker";
import { BLOCKS, imageMarkup } from "./designBlocks";

const POSTER =
  '<section class="poster"><p>14 June</p><h1>Summer<br>Concert</h1>' +
  '<svg viewBox="0 0 400 40"><path d="M0 20q25-36 50 0"></path></svg>' +
  "<p>Town Hall. <strong>Free</strong> entry.</p></section>";

describe("parse and write", () => {
  it("writes the markup back as it was", () => {
    expect(serialize(parseDesign(POSTER))).toBe(POSTER);
  });

  it("finds elements by path and leaves a wrong path empty", () => {
    const root = parseDesign(POSTER);
    expect(elementAt(root, [0, 1])?.localName).toBe("h1");
    expect(elementAt(root, [0, 9])).toBeNull();
  });
});

describe("layers", () => {
  it("lists the visible blocks, a drawing and a marked-up text as one layer each", () => {
    const layers = layersOf(parseDesign(`<style>.a{}</style>${POSTER}`));
    expect(layers).toHaveLength(1);
    const poster = layers[0]!;
    expect(poster).toMatchObject({ path: [1], tag: "section", kind: "box", label: ".poster" });
    expect(poster.children.map((layer) => [layer.kind, layer.label])).toEqual([
      ["text", "14 June"],
      ["heading", "SummerConcert"],
      ["graphic", ""],
      ["text", "Town Hall. Free entry."],
    ]);
    expect(poster.children.every((layer) => layer.children.length === 0)).toBe(true);
  });

  it("tells a text from a box", () => {
    const root = parseDesign('<p>Plain<br>lines</p><p>With <em>marks</em></p><div><p>x</p></div><div style="height:4px"></div>');
    const [plain, marked, box, spacer] = Array.from(root.children);
    expect([isTextElement(plain!), isPlainText(plain!)]).toEqual([true, true]);
    expect([isTextElement(marked!), isPlainText(marked!)]).toEqual([true, false]);
    expect(isTextElement(box!)).toBe(false);
    expect(isTextElement(spacer!)).toBe(false);
  });
});

describe("structure", () => {
  it("moves a block among its siblings, skipping what is not shown", () => {
    const { html, result } = editMarkup("<h1>a</h1><style>x{}</style><p>b</p>", (root) => moveElement(root, [0], 1));
    expect(html).toBe("<style>x{}</style><p>b</p><h1>a</h1>");
    expect(result).toEqual([2]);
    expect(editMarkup("<p>a</p>", (root) => moveElement(root, [0], -1)).result).toBeNull();
  });

  it("moves a block before, after or into another, never into itself", () => {
    const moved = editMarkup("<div><p>a</p></div><p>b</p>", (root) => moveElementTo(root, [1], [0], "inside"));
    expect(moved).toEqual({ html: "<div><p>a</p><p>b</p></div>", result: [0, 1] });
    const self = editMarkup("<div><p>a</p></div>", (root) => moveElementTo(root, [0], [0, 0], "before"));
    expect(self.result).toBeNull();
    expect(self.html).toBe("<div><p>a</p></div>");
  });

  it("duplicates a block without its ids", () => {
    const { html, result } = editMarkup('<div id="hero"><p id="x">a</p></div>', (root) => duplicateElement(root, [0]));
    expect(html).toBe('<div id="hero"><p id="x">a</p></div><div><p>a</p></div>');
    expect(result).toEqual([1]);
  });

  it("removes a block and offers a neighbour, else the parent", () => {
    expect(editMarkup("<p>a</p><p>b</p>", (root) => removeElement(root, [0]))).toEqual({ html: "<p>b</p>", result: [0] });
    expect(editMarkup("<div><p>a</p></div>", (root) => removeElement(root, [0, 0]))).toEqual({ html: "<div></div>", result: [0] });
  });

  it("adds a block after the selection, or inside the design's one wrapper", () => {
    const after = editMarkup("<h1>a</h1><p>b</p>", (root) => insertBlock(root, [0], "<hr>"));
    expect(after).toEqual({ html: "<h1>a</h1><hr><p>b</p>", result: [1] });
    const wrapped = editMarkup(POSTER, (root) => insertBlock(root, null, "<h2>New</h2>"));
    expect(wrapped.result).toEqual([0, 4]);
    expect(wrapped.html.endsWith("<h2>New</h2></section>")).toBe(true);
    const root = parseDesign("<h1>a</h1><p>b</p>");
    expect(insertionPoint(root, null).parent).toBe(root);
  });

  it("makes every block template into one element", () => {
    const words = { heading: "H", text: "T", button: "B", item: "I", quote: "Q", label: "L", value: "1" };
    for (const block of BLOCKS) {
      if (block.id === "image") continue;
      const root = parseDesign(block.markup(words));
      expect(root.children).toHaveLength(1);
    }
    expect(BLOCKS.find((b) => b.id === "heading")!.markup({ ...words, heading: "<b>&" })).toBe("<h2>&lt;b&gt;&amp;</h2>");
    expect(imageMarkup('data:image/png;base64,AA"', "a")).toContain('src="data:image/png;base64,AA&quot;"');
  });
});

describe("text and style", () => {
  it("edits a text with line breaks as lines", () => {
    const root = parseDesign("<h1>Summer<br>Concert</h1>");
    const heading = root.firstElementChild!;
    expect(plainTextOf(heading)).toBe("Summer\nConcert");
    setPlainText(heading, "Winter\n\nGala <b>");
    expect(serialize(root)).toBe("<h1>Winter<br><br>Gala &lt;b&gt;</h1>");
    expect(plainTextOf(heading)).toBe("Winter\n\nGala <b>");
  });

  it("keeps inline marks typed in place and unwraps any block", () => {
    const root = parseDesign("<p>old</p>");
    setInlineMarkup(root.firstElementChild!, 'New <b>bold</b><div>line</div><img src="x"><script>x()</script>');
    expect(serialize(root)).toBe("<p>New <b>bold</b><br>linex()</p>");
  });

  it("sets and clears one inline style property", () => {
    const root = parseDesign("<p>x</p>");
    const p = root.firstElementChild!;
    setStyle(p, "color", "var(--accent)");
    setStyle(p, "font-size", "48px");
    expect(styleOf(p, "color")).toBe("var(--accent)");
    setStyle(p, "color", "");
    setStyle(p, "font-size", "");
    expect(serialize(root)).toBe("<p>x</p>");
  });
});

describe("the spec", () => {
  it("reads a saved spec and keeps accent and theme only when set", () => {
    expect(readDesignSpec({ html: "<p>x</p>", fit: "canvas", width: 1080, height: 1080, background: "", accent: "#E4572E", theme: "dark" })).toEqual({
      html: "<p>x</p>",
      css: "",
      fit: "canvas",
      width: 1080,
      height: 1080,
      background: "",
      accent: "#E4572E",
      theme: "dark",
    });
    expect(readDesignSpec({ html: "<p>x</p>", theme: "sepia" })).toEqual({ html: "<p>x</p>", css: "", fit: "page", background: "" });
  });
});

describe("the preview frame's messages", () => {
  it("takes only well-formed messages from the picker", () => {
    expect(readPickerMessage({ source: PICKER_SOURCE, type: "select", path: [0, 2] })).toEqual({ source: PICKER_SOURCE, type: "select", path: [0, 2] });
    expect(readPickerMessage({ source: PICKER_SOURCE, type: "select", path: null })?.type).toBe("select");
    expect(readPickerMessage({ source: PICKER_SOURCE, type: "select", path: [-1] })).toBeNull();
    expect(readPickerMessage({ source: PICKER_SOURCE, type: "text", path: [0], html: 5 })).toBeNull();
    expect(readPickerMessage({ source: "dodaios-node-ready", type: "ready" })).toBeNull();
    expect(readPickerMessage({ source: PICKER_SOURCE, type: "key", key: "z", meta: true })).toMatchObject({ key: "z", meta: true, ctrl: false });
    expect(readPickerMessage("ready")).toBeNull();
  });

  it("builds a script that parses and talks only in its own tag", () => {
    const script = pickerScript("#2F7CF6");
    expect(() => new Function(script)).not.toThrow();
    expect(script).toContain(JSON.stringify(PICKER_SOURCE));
    expect(script).not.toContain("</script");
  });
});

describe("what the inspector lets into a design", () => {
  it("keeps web, mail and phone links and anything still being typed, never a script link", async () => {
    const { safeLink } = await import("./DesignInspector");
    for (const ok of ["https://example.com", "http://a.b", "mailto:x@y.z", "tel:+49", "#top", "h", "www.example.com", "/path"]) {
      expect(safeLink(ok)).toBe(ok);
    }
    for (const bad of ["javascript:alert(1)", " JavaScript:alert(1)", "data:text/html,<b>", "vbscript:x"]) {
      expect(safeLink(bad)).toBe("");
    }
  });

  it("shows only an embedded picture in the app", async () => {
    const { embeddedPicture } = await import("./DesignInspector");
    expect(embeddedPicture("data:image/png;base64,AAAA")).toBe("data:image/png;base64,AAAA");
    expect(embeddedPicture("https://tracker.example/pixel.png")).toBe("");
    expect(embeddedPicture("data:image/svg+xml;base64,PHN2Zz4=")).toBe("");
    expect(embeddedPicture(null)).toBe("");
  });
});
