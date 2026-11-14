/**
 * The document editor's schema: what a document can hold, and the keys and
 * typing shortcuts that make it.
 *
 * The schema is exactly what the docs page can draw from Markdown (see
 * `markdown/parse.ts`), nothing more: a mark the page cannot show (underline,
 * colour, font size) is not offered, because it would vanish on save. The
 * document's summary is the first node, so typing, the caret and undo flow
 * from the summary line into the body as in one document.
 */
import { Extension, Node, mergeAttributes, wrappingInputRule, type NodeViewRenderer } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Table, TableCell, TableHeader, TableRow } from "@tiptap/extension-table";
import { TaskItem, TaskList } from "@tiptap/extension-list";
import { Placeholder } from "@tiptap/extensions";
import { TextSelection } from "@tiptap/pm/state";

import { CALLOUT_TONES, isCalloutTone } from "./markdown/parse";

/** Addresses a link may have: the page keeps web, mail and in-page links only. */
export const SAFE_LINK = /^(?:https?:\/\/|mailto:|#)/i;
/** Pictures the page can show: raster data URIs (the page has no network). */
export const SAFE_IMAGE = /^data:image\/(?:png|jpe?g|gif|webp|avif);base64,[A-Za-z0-9+/=\s]+$/i;

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    docBlocks: {
      /** Wrap the selection in a callout of a tone, or change the tone of the callout around it. */
      setCallout: (tone: string) => ReturnType;
      /** Lift the selection out of its callout. */
      unsetCallout: () => ReturnType;
      /** Insert a chart block (its JSON in the report chart grammar). */
      insertChart: (source: string) => ReturnType;
      /** Insert a key-figures block. */
      insertMetrics: (source: string) => ReturnType;
      /** Insert a picture (a data URI) at the selection. */
      insertImage: (attrs: { src: string; alt?: string | null }) => ReturnType;
    };
  }
}

const Document = Node.create({
  name: "doc",
  topNode: true,
  content: "summary block+",
});

/**
 * The document's summary: plain text under the title (the page shows it as
 * the lead). Enter goes on into the body instead of making a second summary.
 */
const Summary = Node.create({
  name: "summary",
  content: "text*",
  marks: "",
  defining: true,
  parseHTML: () => [{ tag: "p[data-doc-summary]" }],
  renderHTML: ({ HTMLAttributes }) => ["p", mergeAttributes(HTMLAttributes, { "data-doc-summary": "", class: "doc-summary" }), 0],
  addKeyboardShortcuts() {
    const intoBody = () => {
      const { state, view } = this.editor;
      const { $from } = state.selection;
      if ($from.parent.type.name !== "summary") return false;
      const after = $from.after(1);
      const next = state.doc.nodeAt(after);
      let tr = state.tr;
      if (!next || !next.isTextblock || next.content.size > 0) {
        tr = tr.insert(after, state.schema.nodes.paragraph.create());
      }
      tr = tr.setSelection(TextSelection.create(tr.doc, after + 1)).scrollIntoView();
      view.dispatch(tr);
      return true;
    };
    return {
      Enter: intoBody,
      "Shift-Enter": intoBody,
      // At the very start of the body, Backspace goes back to the summary instead of merging into it.
      Backspace: () => {
        const { state } = this.editor;
        const { $from, empty } = state.selection;
        if (!empty || $from.parentOffset > 0 || $from.depth !== 1 || $from.index(0) !== 1) return false;
        if ($from.parent.content.size > 0 || state.doc.childCount <= 2) {
          return this.editor.commands.setTextSelection(state.doc.child(0).nodeSize - 1);
        }
        return false;
      },
    };
  },
});

/**
 * A callout: the page's `> [!NOTE]` … `> [!CAUTION]` quote, drawn as a
 * coloured box. Its tone is an attribute; typing `[!tip] ` at the start of a
 * line makes one.
 */
export const Callout = Node.create<{ view: NodeViewRenderer | null }>({
  name: "callout",
  group: "block",
  content: "block+",
  defining: true,
  addOptions: () => ({ view: null }),
  addAttributes: () => ({
    tone: {
      default: "note",
      parseHTML: (element) => {
        const tone = element.getAttribute("data-tone");
        return isCalloutTone(tone) ? tone : "note";
      },
      renderHTML: (attributes) => ({ "data-tone": attributes.tone }),
    },
  }),
  parseHTML: () => [{ tag: "aside[data-callout]" }],
  renderHTML: ({ HTMLAttributes }) => ["aside", mergeAttributes(HTMLAttributes, { "data-callout": "", class: "doc-callout" }), 0],
  addNodeView() {
    return this.options.view ?? null;
  },
  addCommands() {
    return {
      setCallout:
        (tone) =>
        ({ state, commands, tr, dispatch }) => {
          const value = isCalloutTone(tone) ? tone : "note";
          const { $from } = state.selection;
          for (let depth = $from.depth; depth > 0; depth -= 1) {
            if ($from.node(depth).type.name === this.name) {
              if (dispatch) tr.setNodeMarkup($from.before(depth), undefined, { tone: value });
              return true;
            }
          }
          return commands.wrapIn(this.name, { tone: value });
        },
      unsetCallout:
        () =>
        ({ commands }) =>
          commands.lift(this.name),
    };
  },
  addInputRules() {
    return [
      wrappingInputRule({
        find: new RegExp(`^\\[!(${CALLOUT_TONES.join("|")})\\]\\s$`, "i"),
        type: this.type,
        getAttributes: (match) => ({ tone: String(match[1]).toLowerCase() }),
      }),
    ];
  },
});

/** A block held as one attribute (`source`) and drawn by a node view. */
function sourceBlock(name: string, tag: string) {
  return Node.create<{ view: NodeViewRenderer | null }>({
    name,
    group: "block",
    atom: true,
    draggable: true,
    selectable: true,
    addOptions: () => ({ view: null }),
    addAttributes: () => ({
      source: {
        default: "",
        parseHTML: (element) => element.getAttribute("data-source") ?? element.textContent ?? "",
        renderHTML: (attributes) => ({ "data-source": attributes.source }),
      },
    }),
    parseHTML: () => [{ tag: `div[${tag}]` }],
    renderHTML: ({ HTMLAttributes }) => ["div", mergeAttributes(HTMLAttributes, { [tag]: "" })],
    addNodeView() {
      return this.options.view ?? null;
    },
  });
}

/** A fenced `chart` block: the chart's JSON in the report chart grammar. */
export const ChartBlock = sourceBlock("chartBlock", "data-doc-chart").extend({
  addCommands() {
    return {
      insertChart:
        (source) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs: { source } }),
    };
  },
});

/** A fenced `metrics` block: one `value | label | detail` per line. */
export const MetricsBlock = sourceBlock("metricsBlock", "data-doc-metrics").extend({
  addCommands() {
    return {
      insertMetrics:
        (source) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs: { source } }),
    };
  },
});

/**
 * Markdown only the page understands (a footnote or a definition list),
 * edited as its text so it reaches the page unchanged.
 */
export const RawBlock = Node.create<{ label: string }>({
  name: "rawBlock",
  group: "block",
  content: "text*",
  marks: "",
  code: true,
  defining: true,
  addOptions: () => ({ label: "Markdown" }),
  parseHTML: () => [{ tag: "pre[data-doc-raw]", preserveWhitespace: "full" }],
  renderHTML({ HTMLAttributes }) {
    return ["pre", mergeAttributes(HTMLAttributes, { "data-doc-raw": "", "data-label": this.options.label, class: "doc-raw" }), ["code", 0]];
  },
});

/**
 * A picture. Only an embedded picture (data URI) is shown, as on the page;
 * one from an address keeps its place and says what it shows.
 */
export const DocImage = Node.create<{ notLoaded: string }>({
  name: "image",
  group: "inline",
  inline: true,
  atom: true,
  draggable: true,
  addOptions: () => ({ notLoaded: "Picture not loaded" }),
  addAttributes: () => ({
    src: { default: "" },
    alt: { default: null },
    title: { default: null },
  }),
  parseHTML: () => [
    {
      tag: "img[src]",
      getAttrs: (element) => ({
        src: element.getAttribute("src") ?? "",
        alt: element.getAttribute("alt"),
        title: element.getAttribute("title"),
      }),
    },
  ],
  renderHTML({ node }) {
    const src = String(node.attrs.src ?? "");
    const alt = node.attrs.alt ? String(node.attrs.alt) : "";
    if (SAFE_IMAGE.test(src)) {
      return ["img", { src, alt, title: node.attrs.title ?? undefined, class: "doc-image", draggable: "true" }];
    }
    return ["span", { class: "doc-image-missing", role: "img", "aria-label": alt || this.options.notLoaded, title: src }, alt || this.options.notLoaded];
  },
  addCommands() {
    return {
      insertImage:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs: { src: attrs.src, alt: attrs.alt ?? null } }),
    };
  },
});

/** A column's alignment, which Markdown keeps per column (`:--`, `:-:`, `--:`). */
const alignAttribute = {
  align: {
    default: null,
    parseHTML: (element: HTMLElement) => {
      const value = element.style.textAlign;
      return value === "left" || value === "center" || value === "right" ? value : null;
    },
    renderHTML: (attributes: Record<string, unknown>) =>
      attributes.align ? { style: `text-align: ${String(attributes.align)}` } : {},
  },
};

// A Markdown cell holds one line of text: no lists or second paragraph.
const DocTableCell = TableCell.extend({
  content: "paragraph",
  addAttributes() {
    return { ...this.parent?.(), ...alignAttribute };
  },
});
const DocTableHeader = TableHeader.extend({
  content: "paragraph",
  addAttributes() {
    return { ...this.parent?.(), ...alignAttribute };
  },
});

/**
 * Keys beyond each extension's own: the heading levels the page uses
 * (Mod-Alt-1 is a section, `##`, since the title is the page's only top
 * heading), Mod-Alt-0 back to text, and Mod-K for a link.
 */
const DocKeys = Extension.create<{ onLink: (() => void) | null }>({
  name: "docKeys",
  priority: 200,
  addOptions: () => ({ onLink: null }),
  addKeyboardShortcuts() {
    const heading = (level: 2 | 3 | 4) => () => this.editor.commands.toggleHeading({ level });
    return {
      "Mod-Alt-1": heading(2),
      "Mod-Alt-2": heading(3),
      "Mod-Alt-3": heading(4),
      "Mod-Alt-0": () => this.editor.commands.setParagraph(),
      "Mod-k": () => {
        if (!this.options.onLink) return false;
        this.options.onLink();
        return true;
      },
    };
  },
});

export interface DocExtensionOptions {
  /** Node views (the editor passes React views; tests may leave them out). */
  views?: { callout?: NodeViewRenderer; chart?: NodeViewRenderer; metrics?: NodeViewRenderer };
  placeholders?: { summary: string; body: string; heading: string };
  labels?: { raw: string; pictureNotLoaded: string };
  onLink?: () => void;
}

export function docExtensions(options: DocExtensionOptions = {}) {
  const placeholders = options.placeholders;
  return [
    StarterKit.configure({
      document: false,
      // No Markdown keeps underlining, and the page would drop it.
      underline: false,
      heading: { levels: [1, 2, 3, 4, 5, 6] },
      link: {
        openOnClick: false,
        autolink: true,
        linkOnPaste: true,
        defaultProtocol: "https",
        isAllowedUri: (url) => SAFE_LINK.test(url),
      },
      trailingNode: { node: "paragraph" },
    }),
    Document,
    Summary,
    Callout.configure({ view: options.views?.callout ?? null }),
    ChartBlock.configure({ view: options.views?.chart ?? null }),
    MetricsBlock.configure({ view: options.views?.metrics ?? null }),
    RawBlock.configure({ label: options.labels?.raw ?? "Markdown" }),
    DocImage.configure({ notLoaded: options.labels?.pictureNotLoaded ?? "Picture not loaded" }),
    TaskList,
    TaskItem.configure({ nested: true }),
    Table.configure({ resizable: false, HTMLAttributes: { class: "doc-table" } }),
    TableRow,
    DocTableHeader,
    DocTableCell,
    DocKeys.configure({ onLink: options.onLink ?? null }),
    ...(placeholders
      ? [
          Placeholder.configure({
            showOnlyCurrent: false,
            // Only the body's own blocks get a hint, never a list item or a cell.
            includeChildren: false,
            // The placeholder is worked out while a change is applied, before
            // `editor.state` holds it: only the node itself is read here.
            placeholder: ({ node, hasAnchor }) => {
              if (node.type.name === "summary") return placeholders.summary;
              if (node.type.name === "heading") return hasAnchor ? placeholders.heading : "";
              return node.type.name === "paragraph" && hasAnchor ? placeholders.body : "";
            },
          }),
        ]
      : []),
  ];
}
