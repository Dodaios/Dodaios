/**
 * The document editor as a whole: it shows the document's blocks, the
 * toolbar's commands change the Markdown that is saved, the frame's undo is
 * the text editor's history, charts are edited through the shared chart
 * editor, and a revision by the assistant replaces the content.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { Editor } from "@tiptap/core";
import type { ReactNode } from "react";

import type { NodeCard } from "../../../nodeModel";
import { RevisionContext, createRevisionSource } from "../../editorContext";
import DocsEditor from "../index";
import { linkHref } from "../Toolbar";

vi.mock("@/i18n", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/i18n")>();
  return { ...actual, useT: () => (key: string) => key, useUiLanguage: () => "en" };
});

// jsdom lays nothing out; ProseMirror asks for rectangles when it scrolls the caret into view.
const rect = () => ({ x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, toJSON: () => ({}) });
Range.prototype.getBoundingClientRect = rect as unknown as () => DOMRect;
Range.prototype.getClientRects = (() => ({ length: 0, item: () => null, [Symbol.iterator]: function* () {} })) as unknown as () => DOMRectList;
document.elementFromPoint = (() => null) as typeof document.elementFromPoint;
if (typeof window.ResizeObserver === "undefined") {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

const NODE = {
  key: "k",
  id: "doc123",
  type: "docs",
  origin: "node",
  title: "Hosting plans",
  slug: "s",
  path: "p.html",
  created_at: 1,
  updated_at: 2,
  version: 1,
  status: "ready",
} as unknown as NodeCard;

const CHART = '{"type": "bar", "title": "Price per seat", "x": ["Alpha", "Beta", "Gamma"], "data": [19, 27, 24]}';
const MARKDOWN = [
  "## Result",
  "",
  "Alpha costs **19 €** per seat.",
  "",
  "```chart",
  CHART,
  "```",
  "",
  "> [!TIP]",
  "> **Recommendation** Start with Alpha.",
  "",
  "```metrics",
  "19 € | Alpha | per seat",
  "```",
].join("\n");

interface Saved {
  spec: { summary: string; markdown: string };
  base_version: number | null;
}

function server(markdown = MARKDOWN) {
  const state = { version: 1, updated_at: 100, spec: { summary: "Three plans compared.", markdown } };
  const puts: Saved[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/spec") && init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as Saved;
        puts.push(body);
        state.version += 1;
        state.updated_at += 10;
        state.spec = body.spec;
        return { ok: true, status: 200, json: async () => ({ ...state }) };
      }
      if (url.endsWith("/doc123")) return { ok: true, status: 200, json: async () => ({ ...state }) };
      return { ok: false, status: 404, json: async () => ({}) };
    }),
  );
  return {
    state,
    puts,
    last: () => puts[puts.length - 1]?.spec,
    revise(next: { summary: string; markdown: string }) {
      state.version += 1;
      state.updated_at += 100;
      state.spec = next;
    },
  };
}

function mount(remote: ReturnType<typeof server>, wrapper?: (props: { children: ReactNode }) => JSX.Element) {
  const view = render(
    <DocsEditor
      node={NODE}
      initial={{ spec: { ...remote.state.spec }, version: remote.state.version, updated_at: remote.state.updated_at }}
      onDone={() => {}}
    />,
    wrapper ? { wrapper } : undefined,
  );
  const dom = screen.getByTestId("docs-editor-content") as HTMLElement & { editor: Editor };
  return { ...view, editor: dom.editor };
}

/** Put the caret (or a selection) on the first occurrence of `text`. */
function select(editor: Editor, text: string, whole = true) {
  let found = -1;
  editor.state.doc.descendants((node, pos) => {
    if (found >= 0 || !node.isText) return found < 0;
    const at = node.text!.indexOf(text);
    if (at >= 0) found = pos + at;
    return false;
  });
  if (found < 0) throw new Error(`not found: ${text}`);
  act(() => {
    editor.commands.setTextSelection(whole ? { from: found, to: found + text.length } : found);
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DocsEditor", () => {
  it("shows the title, the summary and the document's blocks", async () => {
    const remote = server();
    mount(remote);
    expect(screen.getByRole("heading", { level: 1, name: "Hosting plans" })).toBeTruthy();
    const content = screen.getByTestId("docs-editor-content");
    expect(content.querySelector("p.doc-summary")?.textContent).toBe("Three plans compared.");
    expect(content.querySelector("h2")?.textContent).toBe("Result");
    expect(content.querySelector("strong")?.textContent).toBe("19 €");
    expect((await screen.findByTestId("docs-callout")).getAttribute("data-tone")).toBe("tip");
    expect(screen.getByTestId("docs-chart-block")).toBeTruthy();
    expect(screen.getAllByTestId("docs-metric")).toHaveLength(1);
  });

  it("saves nothing while nothing changed", async () => {
    const remote = server();
    mount(remote);
    await new Promise((resolve) => setTimeout(resolve, 900));
    expect(remote.puts).toHaveLength(0);
  });

  it("saves the toolbar's change as Markdown, keeping untouched blocks as written", async () => {
    const remote = server();
    const { editor } = mount(remote);
    select(editor, "per seat.");
    fireEvent.click(screen.getByTestId("docs-italic"));
    await waitFor(() => expect(remote.puts.length).toBeGreaterThan(0), { timeout: 3000 });
    const saved = remote.last()!;
    expect(saved.summary).toBe("Three plans compared.");
    expect(saved.markdown).toBe(MARKDOWN.replace("per seat.", "*per seat.*"));
    expect(remote.puts[0].base_version).toBe(1);
  });

  it("turns a paragraph into a heading, a list and a callout from the toolbar", async () => {
    const remote = server("First line\n\nSecond line\n\nThird line");
    const { editor } = mount(remote);
    select(editor, "First line", false);
    act(() => void editor.chain().setHeading({ level: 2 }).run());
    select(editor, "Second line", false);
    fireEvent.click(screen.getByTestId("docs-task-list"));
    select(editor, "Third line", false);
    act(() => void editor.chain().setCallout("warning").run());
    await waitFor(() => expect(remote.last()?.markdown).toBe("## First line\n\n- [ ] Second line\n\n> [!WARNING]\n> Third line"), {
      timeout: 3000,
    });
  });

  it("undoes and redoes through the frame's buttons, with the text editor's history", async () => {
    const remote = server("Plain text");
    const { editor } = mount(remote);
    expect((screen.getByTestId("node-editor-undo") as HTMLButtonElement).disabled).toBe(true);
    select(editor, "Plain");
    fireEvent.click(screen.getByTestId("docs-bold"));
    await waitFor(() => expect(remote.last()?.markdown).toBe("**Plain** text"), { timeout: 3000 });
    const undo = screen.getByTestId("node-editor-undo") as HTMLButtonElement;
    expect(undo.disabled).toBe(false);
    fireEvent.click(undo);
    await waitFor(() => expect(remote.last()?.markdown).toBe("Plain text"), { timeout: 3000 });
    fireEvent.click(screen.getByTestId("node-editor-redo"));
    await waitFor(() => expect(remote.last()?.markdown).toBe("**Plain** text"), { timeout: 3000 });
  });

  it("inserts a table and grows it by a row and a column", async () => {
    const remote = server("Intro");
    const { editor } = mount(remote);
    select(editor, "Intro", false);
    act(() => void editor.commands.setTextSelection(editor.state.doc.content.size - 1));
    act(() => void editor.chain().insertTable({ rows: 2, cols: 2, withHeaderRow: true }).run());
    act(() => void editor.chain().insertContent("Plan").run());
    fireEvent.click(screen.getByTestId("docs-table-menu"));
    fireEvent.click(await screen.findByTestId("docs-row-below"));
    fireEvent.click(screen.getByTestId("docs-table-menu"));
    fireEvent.click(await screen.findByTestId("docs-column-right"));
    fireEvent.click(screen.getByTestId("docs-align-right"));
    await waitFor(
      () => {
        const markdown = remote.last()?.markdown ?? "";
        expect(markdown).toContain("| Plan |   |   |");
        // The caret is in the first column, so that column is right-aligned.
        expect(markdown).toContain("| ---: | --- | --- |");
        expect(markdown.split("\n").filter((line) => line.startsWith("|"))).toHaveLength(4);
      },
      { timeout: 3000 },
    );
  });

  it("adds a link to the chosen words from the link form", async () => {
    const remote = server("Read the pricing page");
    const { editor } = mount(remote);
    select(editor, "pricing page");
    fireEvent.click(screen.getByTestId("docs-link"));
    const form = await screen.findByTestId("docs-link-form");
    fireEvent.change(within(form).getByRole("textbox"), { target: { value: "alpha.example/pricing" } });
    fireEvent.submit(form);
    await waitFor(() => expect(remote.last()?.markdown).toBe("Read the [pricing page](https://alpha.example/pricing)"), {
      timeout: 3000,
    });
  });

  it("edits a chart through the shared chart editor and writes its JSON back", async () => {
    const remote = server();
    mount(remote);
    fireEvent.click(await screen.findByTestId("docs-chart-edit"));
    const dialog = await screen.findByRole("dialog");
    const apply = within(dialog).getByRole("button", { name: "nodes.editor.chart.apply" });
    fireEvent.click(apply);
    await waitFor(() => expect(remote.puts.length).toBeGreaterThan(0), { timeout: 3000 });
    const markdown = remote.last()!.markdown;
    const fence = /```chart\n(.*)\n```/.exec(markdown);
    expect(fence).not.toBeNull();
    expect(JSON.parse(fence![1])).toMatchObject({ type: "bar", x: ["Alpha", "Beta", "Gamma"] });
    // The rest of the document is untouched.
    expect(markdown.startsWith("## Result\n\nAlpha costs **19 €** per seat.\n\n```chart\n")).toBe(true);
    expect(markdown.endsWith("> [!TIP]\n> **Recommendation** Start with Alpha.\n\n```metrics\n19 € | Alpha | per seat\n```")).toBe(true);
  });

  it("edits key figures in place", async () => {
    const remote = server();
    mount(remote);
    fireEvent.click(await screen.findByTestId("docs-metrics-add"));
    await waitFor(() => expect(screen.getAllByTestId("docs-metric")).toHaveLength(2));
    const metrics = screen.getAllByTestId("docs-metric");
    const [value, label] = within(metrics[1]).getAllByRole("textbox");
    fireEvent.change(value, { target: { value: "27 €" } });
    fireEvent.change(label, { target: { value: "Beta" } });
    await waitFor(() => expect(remote.last()?.markdown).toContain("```metrics\n19 € | Alpha | per seat\n27 € | Beta\n```"), {
      timeout: 3000,
    });
  });

  it("holds the save with a sentence when the body is emptied", async () => {
    const remote = server("Only line");
    const { editor } = mount(remote);
    act(() => {
      editor.commands.setTextSelection({ from: editor.state.doc.child(0).nodeSize + 1, to: editor.state.doc.content.size - 1 });
      editor.commands.deleteSelection();
    });
    await waitFor(() => expect(screen.getByTestId("node-editor-save-state").getAttribute("data-state")).toBe("held"), {
      timeout: 3000,
    });
    expect(screen.getByTestId("node-editor-save-state").textContent).toContain("nodes.editor.docs.errors.empty");
    expect(remote.puts).toHaveLength(0);
  });

  it("takes the assistant's revision while nothing is unsaved", async () => {
    const remote = server("Old text");
    const source = createRevisionSource();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <RevisionContext.Provider value={source}>{children}</RevisionContext.Provider>
    );
    mount(remote, wrapper);
    remote.revise({ summary: "New summary.", markdown: "## New\n\nRevised text" });
    act(() => source.emit(remote.state.updated_at));
    await waitFor(() => expect(screen.getByTestId("docs-editor-content").querySelector("h2")?.textContent).toBe("New"));
    const content = screen.getByTestId("docs-editor-content");
    expect(content.querySelector("p.doc-summary")?.textContent).toBe("New summary.");
    expect(content.textContent).not.toContain("Old text");
    // Taking it is not a save of the person's own.
    expect(remote.puts).toHaveLength(0);
  });
});

describe("linkHref", () => {
  it("completes a typed address and refuses what the page would drop", () => {
    expect(linkHref("https://a.example")).toBe("https://a.example");
    expect(linkHref("a.example/x")).toBe("https://a.example/x");
    expect(linkHref("me@a.example")).toBe("mailto:me@a.example");
    expect(linkHref("#overview")).toBe("#overview");
    expect(linkHref("javascript:alert(1)")).toBeNull();
    expect(linkHref("")).toBeNull();
  });
});
