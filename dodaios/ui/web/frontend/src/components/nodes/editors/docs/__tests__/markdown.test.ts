// @vitest-environment jsdom
/**
 * The document's Markdown survives the editor: read into the editor's schema
 * and written back, it means the same to the page, untouched blocks keep
 * their exact text, and edited blocks are written in the dialect the page's
 * renderer (Python-Markdown) reads the same way.
 */
import { afterEach, describe, expect, it } from "vitest";
import { Editor, type JSONContent } from "@tiptap/core";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { docExtensions } from "../extensions";
import { DocSession } from "../docModel";
import { markdownToDoc, parseMarkdown } from "../markdown/parse";
import { docToMarkdown, escapeText, serializeInline } from "../markdown/serialize";

const FIXTURES = join(__dirname, "..", "__fixtures__");
const fixtures = readdirSync(FIXTURES)
  .filter((name) => name.endsWith(".md") && !name.endsWith(".out.md"))
  .map((name) => ({ name, text: readFileSync(join(FIXTURES, name), "utf8").replace(/\s+$/, "") }));

const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

function load(markdown: string, summary = "") {
  const session = new DocSession({ summary, markdown });
  const editor = new Editor({ extensions: docExtensions(), content: session.content });
  editors.push(editor);
  session.remember(editor.state.doc);
  return { session, editor };
}

/** The doc's meaning: the parsed content, in the editor's schema. */
function meaning(markdown: string): JSONContent {
  const { editor } = load(markdown);
  const json = editor.getJSON();
  return { ...json, content: json.content?.slice(1) };
}

/** Write the editor's whole body fresh, as if every block had been edited. */
function rewrite(markdown: string): string {
  const { editor } = load(markdown);
  const json = editor.getJSON();
  return docToMarkdown({ type: "doc", content: json.content?.slice(1) });
}

describe("round trip", () => {
  it.each(fixtures)("$name keeps its exact text when nothing was edited", ({ text }) => {
    const { session, editor } = load(text, "A summary.");
    expect(session.specOf(editor.state.doc)).toEqual({ summary: "A summary.", markdown: text });
  });

  it.each(fixtures)("$name means the same after every block is written again", ({ text }) => {
    const written = rewrite(text);
    expect(meaning(written)).toEqual(meaning(text));
    // Writing it once more changes nothing: the writer has one form.
    expect(rewrite(written)).toBe(written);
  });

  it.each(fixtures.filter(({ name }) => readdirSync(FIXTURES).includes(name.replace(/\.md$/, ".out.md"))))(
    "$name is written as its expected page Markdown",
    ({ name, text }) => {
      const expected = readFileSync(join(FIXTURES, name.replace(/\.md$/, ".out.md")), "utf8").replace(/\s+$/, "");
      expect(rewrite(text)).toBe(expected);
    },
  );
});

describe("reading the page's own blocks", () => {
  it("reads a tone quote as a callout and its bold opening stays bold", () => {
    const doc = markdownToDoc("> [!TIP]\n> **Recommendation** Start with Alpha.");
    expect(doc.content?.[0]).toEqual({
      type: "callout",
      attrs: { tone: "tip" },
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "Recommendation", marks: [{ type: "bold" }] },
            { type: "text", text: " Start with Alpha." },
          ],
        },
      ],
    });
  });

  it("keeps a chart's JSON and a metrics block verbatim", () => {
    const chart = '{"type": "bar", "x": ["A", "B"], "data": [1, 2]}';
    const doc = markdownToDoc(`\`\`\`chart\n${chart}\n\`\`\`\n\n\`\`\`metrics\n19 € | Alpha\n\`\`\``);
    expect(doc.content).toEqual([
      { type: "chartBlock", attrs: { source: chart } },
      { type: "metricsBlock", attrs: { source: "19 € | Alpha" } },
    ]);
  });

  it("reads a list of [ ] / [x] items as a checklist", () => {
    const doc = markdownToDoc("- [ ] Open\n- [x] Done");
    expect(doc.content?.[0].type).toBe("taskList");
    expect(doc.content?.[0].content?.map((item) => item.attrs?.checked)).toEqual([false, true]);
    expect(rewrite("- [ ] Open\n- [x] Done")).toBe("- [ ] Open\n- [x] Done");
  });

  it("keeps footnote and definition-list paragraphs as raw Markdown", () => {
    const doc = markdownToDoc("Text[^1].\n\n[^1]: The source.\n\nTerm\n: Meaning");
    expect(doc.content?.map((node) => node.type)).toEqual(["paragraph", "rawBlock", "rawBlock"]);
    expect(rewrite("Text[^1].\n\n[^1]: The source.")).toBe("Text[^1].\n\n[^1]: The source.");
  });

  it("keeps table alignment per column", () => {
    const text = "| Plan | Price |\n| :---: | ---: |\n| Alpha | 19 |";
    expect(rewrite(text)).toBe(text);
  });

  it("keeps reference definitions a kept block still uses", () => {
    const text = "See [the plan][p].\n\nSecond paragraph.\n\n[p]: https://example.com/plan";
    const { session, editor } = load(text);
    // Edit the last paragraph: the gap with the definition goes, the definition must not.
    const last = editor.state.doc.lastChild!;
    const end = editor.state.doc.content.size - 1;
    editor.commands.insertContentAt(end, " More");
    expect(last).not.toBe(editor.state.doc.lastChild);
    const markdown = session.specOf(editor.state.doc).markdown;
    expect(markdown).toContain("See [the plan][p].");
    expect(markdown).toContain("Second paragraph. More");
    expect(markdown).toContain("[p]: https://example.com/plan");
  });
});

describe("writing for the page", () => {
  it("indents nested lists by four spaces", () => {
    expect(rewrite("- one\n  - two\n- three")).toBe("- one\n    - two\n- three");
  });

  it("separates a list from the paragraph it interrupted", () => {
    expect(rewrite("Text\n- item")).toBe("Text\n\n- item");
  });

  it("keeps a callout after a quote, and two lists, apart on the page", () => {
    expect(rewrite("> quote\n\n> [!TIP]\n> tip")).toBe("> quote\n\n&#8203;\n\n> [!TIP]\n> tip");
    expect(meaning("> quote\n\n&#8203;\n\n> [!TIP]\n> tip")).toEqual(meaning("> quote\n\n> [!TIP]\n> tip"));
    expect(rewrite("- a\n\n&#8203;\n\n- b")).toBe("- a\n\n&#8203;\n\n- b");
  });

  it("writes a hard break as two trailing spaces", () => {
    expect(rewrite("one  \ntwo")).toBe("one  \ntwo");
    expect(rewrite("one\\\ntwo")).toBe("one  \ntwo");
  });

  it("moves whitespace outside emphasis", () => {
    const content: JSONContent[] = [
      { type: "text", text: "bold ", marks: [{ type: "bold" }] },
      { type: "text", text: "plain" },
    ];
    expect(serializeInline(content)).toBe("**bold** plain");
  });

  it("nests marks without closing what continues", () => {
    const content: JSONContent[] = [
      { type: "text", text: "a", marks: [{ type: "bold" }] },
      { type: "text", text: "b", marks: [{ type: "bold" }, { type: "italic" }] },
      { type: "text", text: "c", marks: [{ type: "bold" }] },
    ];
    expect(serializeInline(content)).toBe("**a*b*c**");
  });

  it("writes links, code and strike", () => {
    expect(rewrite("[a *b*](https://x.example/a%20b) `c` ~~d~~")).toBe("[a *b*](https://x.example/a%20b) `c` ~~d~~");
  });

  it("escapes only what would turn into syntax", () => {
    expect(escapeText("2 * 3 = 6 and snake_case _x_")).toBe("2 \\* 3 = 6 and snake_case \\_x\\_");
    expect(escapeText("[^1] stays, [a](b) does not")).toBe("[^1] stays, \\[a](b) does not");
    expect(escapeText("~~not struck~~")).toBe("&#126;&#126;not struck&#126;&#126;");
    expect(escapeText("AT&T &amp;")).toBe("AT&T &amp;amp;");
    expect(rewrite("\\# not a heading")).toBe("\\# not a heading");
    expect(rewrite("1\\. not a list")).toBe("1\\. not a list");
  });

  it("reads back what it escaped as the same text", () => {
    const tricky = "a * b _c_ `d` [e](f) ~~g~~ <https://h> &copy; {: .x} # i";
    const doc = { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: tricky }] }] };
    const back = parseMarkdown(docToMarkdown(doc)).blocks[0].node;
    expect(back).toEqual({ type: "paragraph", content: [{ type: "text", text: tricky }] });
  });
});
