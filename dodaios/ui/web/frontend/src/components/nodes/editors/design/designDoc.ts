/**
 * A Visuals (``design``) spec's markup as a tree the editor can change.
 *
 * A design has no block grammar: its layout IS its markup
 * (`dodaios/nodes/kinds/design.py`). So the editor's "blocks" are the
 * markup's own elements, addressed by a PATH of element-child indexes from
 * the design's root (`<main class="design">` on the page). The same path
 * names the same element in the editor's parsed copy and in the preview
 * frame, because both are the browser's parse of the same markup.
 *
 * Every change parses the current markup, changes the parsed tree and writes
 * it out again (`serialize`), so the spec keeps holding plain markup the
 * server cleans as it always has. Nothing here trusts the markup: it is only
 * ever parsed into an inert document (`DOMParser`), never into the app's own.
 */

export type ElementPath = readonly number[];

/** One element of the design as the layers list shows it. */
export interface DesignLayer {
  path: number[];
  tag: string;
  kind: LayerKind;
  /** A short human label: the element's text, or its class, or its tag. */
  label: string;
  children: DesignLayer[];
}

export type LayerKind =
  | "heading"
  | "text"
  | "link"
  | "button"
  | "image"
  | "graphic"
  | "list"
  | "divider"
  | "table"
  | "box";

const HEADINGS = new Set(["h1", "h2", "h3", "h4", "h5", "h6"]);
const TEXTS = new Set(["p", "span", "small", "strong", "b", "em", "i", "u", "s", "mark", "q", "cite", "blockquote", "figcaption", "label", "dt", "dd", "li", "time", "code", "pre", "sub", "sup", "abbr", "address", "caption", "legend", "summary", "td", "th"]);
const LISTS = new Set(["ul", "ol", "dl"]);
/** Elements that only shape text inside a line: they keep a text a text. */
export const INLINE_TAGS = new Set(["b", "strong", "i", "em", "u", "s", "small", "mark", "span", "a", "sub", "sup", "code", "br", "abbr", "q", "cite", "time", "wbr", "del", "ins", "kbd", "var", "bdi", "bdo"]);
/** SVG shapes: coloured with fill and stroke rather than color and background. */
export const SVG_NS = "http://www.w3.org/2000/svg";

/** Layers deeper than this are listed but not unfolded by default. */
export const OPEN_DEPTH = 1;

/* --------------------------------------------------------------- parsing */

/** The markup parsed into an inert document; its `<body>` is the design's root. */
export function parseDesign(html: string): HTMLElement {
  const doc = new DOMParser().parseFromString(`<!doctype html><html><body>${html}</body></html>`, "text/html");
  return doc.body;
}

/** The root's markup again, as the spec stores it. */
export function serialize(root: HTMLElement): string {
  return root.innerHTML.trim();
}

export function elementAt(root: Element, path: ElementPath): Element | null {
  let node: Element | null = root;
  for (const index of path) {
    node = node?.children.item(index) ?? null;
    if (!node) return null;
  }
  return node;
}

export function pathOf(root: Element, element: Element): number[] | null {
  const path: number[] = [];
  let node: Element | null = element;
  while (node && node !== root) {
    const parent: Element | null = node.parentElement;
    if (!parent) return null;
    path.unshift(Array.prototype.indexOf.call(parent.children, node));
    node = parent;
  }
  return node === root ? path : null;
}

export function samePath(a: ElementPath | null, b: ElementPath | null): boolean {
  return !!a && !!b && a.length === b.length && a.every((value, index) => value === b[index]);
}

/** Whether `inner` is `outer` or lies inside it. */
export function isWithin(inner: ElementPath, outer: ElementPath): boolean {
  return outer.length <= inner.length && outer.every((value, index) => inner[index] === value);
}

/* ----------------------------------------------------------- describing */

function tagOf(element: Element): string {
  return element.localName.toLowerCase();
}

export function isSvgElement(element: Element): boolean {
  return element.namespaceURI === SVG_NS;
}

export function layerKind(element: Element): LayerKind {
  const tag = tagOf(element);
  if (isSvgElement(element)) return "graphic";
  if (HEADINGS.has(tag)) return "heading";
  if (tag === "img") return "image";
  if (tag === "hr") return "divider";
  if (tag === "button" || (tag === "a" && /\bbtn\b/.test(element.getAttribute("class") ?? ""))) return "button";
  if (tag === "a") return "link";
  if (LISTS.has(tag)) return "list";
  if (tag === "table") return "table";
  if (TEXTS.has(tag) || isTextElement(element)) return "text";
  return "box";
}

/**
 * Whether an element is a TEXT: its content is words, maybe with inline
 * marks, and no block inside. Such an element can be typed into directly.
 */
export function isTextElement(element: Element): boolean {
  if (isSvgElement(element) && tagOf(element) !== "text" && tagOf(element) !== "tspan") return false;
  const tag = tagOf(element);
  if (tag === "img" || tag === "hr" || tag === "br" || tag === "style") return false;
  for (const child of Array.from(element.children)) {
    const inner = tagOf(child);
    if (!INLINE_TAGS.has(inner)) return false;
    if (inner !== "br" && inner !== "wbr" && !isTextElement(child)) return false;
  }
  if ((element.textContent ?? "").trim() !== "") return true;
  // An empty element is a text only where words belong (an empty heading
  // waiting for its words); an empty box is a spacer or a shape.
  return HEADINGS.has(tag) || TEXTS.has(tag) || tag === "a" || tag === "button";
}

/** Whether a text element holds only words and line breaks (no inline marks). */
export function isPlainText(element: Element): boolean {
  return isTextElement(element) && Array.from(element.children).every((child) => tagOf(child) === "br");
}

function squash(text: string, limit: number): string {
  const one = text.replace(/\s+/g, " ").trim();
  return one.length > limit ? `${one.slice(0, limit - 1)}…` : one;
}

export function layerLabel(element: Element): string {
  const tag = tagOf(element);
  if (tag === "img") return squash(element.getAttribute("alt") ?? "", 40);
  const words = squash(element.textContent ?? "", 48);
  if (words && (isTextElement(element) || layerKind(element) !== "box")) return words;
  const klass = (element.getAttribute("class") ?? "").trim().split(/\s+/)[0] ?? "";
  return klass ? `.${klass}` : words;
}

/** Elements that draw nothing and are left out of the layers list. */
function isHidden(element: Element): boolean {
  const tag = tagOf(element);
  return tag === "style" || tag === "br" || tag === "wbr" || tag === "defs" || tag === "title" || tag === "desc";
}

/**
 * The layers list. An SVG is one layer (its shapes are not unfolded: a
 * drawing is edited as a whole), and so is a text with inline marks.
 */
export function layersOf(root: Element, base: number[] = []): DesignLayer[] {
  const layers: DesignLayer[] = [];
  Array.from(root.children).forEach((child, index) => {
    if (isHidden(child)) return;
    const path = [...base, index];
    const leaf = isSvgElement(child) || isTextElement(child) || tagOf(child) === "img";
    layers.push({
      path,
      tag: tagOf(child),
      kind: layerKind(child),
      label: layerLabel(child),
      children: leaf ? [] : layersOf(child, path),
    });
  });
  return layers;
}

/** The layers in reading order, for keyboard travel through the list. */
export function flattenLayers(layers: DesignLayer[], open: (path: number[]) => boolean): DesignLayer[] {
  const out: DesignLayer[] = [];
  const walk = (items: DesignLayer[]) => {
    for (const layer of items) {
      out.push(layer);
      if (layer.children.length && open(layer.path)) walk(layer.children);
    }
  };
  walk(layers);
  return out;
}

/* ---------------------------------------------------------- inline style */

/** One inline style property of an element ("" when not set). */
export function styleOf(element: Element, property: string): string {
  return (element as HTMLElement).style?.getPropertyValue(property).trim() ?? "";
}

/** Set (or with "" remove) one inline style property. */
export function setStyle(element: Element, property: string, value: string): void {
  const style = (element as HTMLElement).style;
  if (!style) return;
  if (value.trim()) style.setProperty(property, value.trim());
  else style.removeProperty(property);
  if (!element.getAttribute("style")?.trim()) element.removeAttribute("style");
}

/* -------------------------------------------------------- changing text */

/** A text element's words with its line breaks as newlines. */
export function plainTextOf(element: Element): string {
  let out = "";
  element.childNodes.forEach((node) => {
    if (node.nodeType === 3) out += node.textContent ?? "";
    else if (node.nodeType === 1 && tagOf(node as Element) === "br") out += "\n";
    else out += node.textContent ?? "";
  });
  return out;
}

/** Replace an element's content with `text`, newlines becoming line breaks. */
export function setPlainText(element: Element, text: string): void {
  const doc = element.ownerDocument;
  element.replaceChildren();
  text.split("\n").forEach((line, index) => {
    if (index > 0) element.appendChild(doc.createElement("br"));
    if (line) element.appendChild(doc.createTextNode(line));
  });
}

/**
 * Replace an element's content with markup typed in the preview. Only
 * inline marks are kept (what the frame's `contenteditable` produces from
 * bold, italic and line breaks); any block or other element is unwrapped to
 * its words, so typing can never change the design's structure.
 */
export function setInlineMarkup(element: Element, markup: string): void {
  const scratch = parseDesign(markup);
  const keep = (node: Node, into: Node) => {
    node.childNodes.forEach((child) => {
      if (child.nodeType === 3) {
        into.appendChild(element.ownerDocument.createTextNode(child.textContent ?? ""));
      } else if (child.nodeType === 1) {
        const tag = tagOf(child as Element);
        if (INLINE_TAGS.has(tag)) {
          const copy = element.ownerDocument.createElement(tag);
          for (const name of ["class", "href", "style"]) {
            const value = (child as Element).getAttribute(name);
            if (value !== null) copy.setAttribute(name, value);
          }
          into.appendChild(copy);
          keep(child, copy);
        } else {
          // A <div> the browser made for a new line becomes a line break.
          if (tag === "div" && into.childNodes.length) into.appendChild(element.ownerDocument.createElement("br"));
          keep(child, into);
        }
      }
    });
  };
  element.replaceChildren();
  keep(scratch, element);
}

/* ------------------------------------------------------ changing structure */

/** Move an element among its siblings by `step`. Returns its new path. */
export function moveElement(root: Element, path: ElementPath, step: number): number[] | null {
  const element = elementAt(root, path);
  const parent = element?.parentElement;
  if (!element || !parent || !path.length) return null;
  const siblings = Array.from(parent.children);
  const from = siblings.indexOf(element);
  // Skip over what the layers list does not show, so one press is one visible step.
  let to = from + step;
  while (to >= 0 && to < siblings.length && isHidden(siblings[to] as Element)) to += Math.sign(step);
  if (to < 0 || to >= siblings.length || to === from) return null;
  const anchor = siblings[to] as Element;
  if (step < 0) parent.insertBefore(element, anchor);
  else parent.insertBefore(element, anchor.nextElementSibling);
  return pathOf(root, element);
}

/**
 * Move an element to another place: before or after `target`, or as the
 * last child inside it. An element cannot go inside itself.
 */
export function moveElementTo(
  root: Element,
  path: ElementPath,
  target: ElementPath,
  where: "before" | "after" | "inside",
): number[] | null {
  if (isWithin(target, path)) return null;
  const element = elementAt(root, path);
  const anchor = elementAt(root, target);
  if (!element || !anchor || !path.length) return null;
  if (where === "inside") anchor.appendChild(element);
  else if (!anchor.parentElement) return null;
  else if (where === "before") anchor.parentElement.insertBefore(element, anchor);
  else anchor.parentElement.insertBefore(element, anchor.nextElementSibling);
  return pathOf(root, element);
}

export function duplicateElement(root: Element, path: ElementPath): number[] | null {
  const element = elementAt(root, path);
  if (!element || !path.length) return null;
  const copy = element.cloneNode(true) as Element;
  // An id is unique on a page; the copy keeps the styles but not the id.
  copy.removeAttribute("id");
  copy.querySelectorAll("[id]").forEach((inner) => {
    if (!isSvgElement(inner)) inner.removeAttribute("id");
  });
  element.after(copy);
  return pathOf(root, copy);
}

/** Remove an element. Returns the path best selected afterwards (a neighbour or the parent). */
export function removeElement(root: Element, path: ElementPath): number[] | null {
  const element = elementAt(root, path);
  if (!element || !path.length) return null;
  const parent = element.parentElement;
  const next = element.nextElementSibling ?? element.previousElementSibling;
  element.remove();
  if (next && !isHidden(next)) return pathOf(root, next);
  return parent && parent !== root ? pathOf(root, parent) : null;
}

/**
 * Where a new block goes: after the selected element; with nothing selected,
 * at the end of the design. A design that is one wrapper (a `<section>` that
 * holds everything, the usual shape) takes new blocks inside its wrapper, so
 * they share its padding and grid.
 */
export function insertionPoint(root: Element, selected: ElementPath | null): { parent: Element; before: Element | null } {
  const element = selected ? elementAt(root, selected) : null;
  if (element && element.parentElement && selected && selected.length) {
    return { parent: element.parentElement, before: element.nextElementSibling };
  }
  const shown = Array.from(root.children).filter((child) => !isHidden(child));
  const only = shown.length === 1 ? shown[0] : null;
  if (only && !isSvgElement(only) && layerKind(only) === "box") return { parent: only, before: null };
  return { parent: root, before: null };
}

/** Insert `markup` (one block) at the insertion point. Returns the new block's path. */
export function insertBlock(root: Element, selected: ElementPath | null, markup: string): number[] | null {
  const scratch = parseDesign(markup);
  const block = scratch.firstElementChild;
  if (!block) return null;
  const { parent, before } = insertionPoint(root, selected);
  const adopted = root.ownerDocument.importNode(block, true);
  parent.insertBefore(adopted, before);
  return pathOf(root, adopted);
}

/**
 * Change the markup through `change(root)` and return the new markup with
 * what `change` returned (a path to select). The one entry point the editor
 * uses inside its `apply`, so each change is parse, edit, write.
 */
export function editMarkup<T>(html: string, change: (root: HTMLElement) => T): { html: string; result: T } {
  const root = parseDesign(html);
  const result = change(root);
  return { html: serialize(root), result };
}

/* ------------------------------------------------------------- the spec */

/** The design spec as `design.normalize` keeps it (`dodaios/nodes/kinds/design.py`). */
export interface DesignSpec {
  html: string;
  css: string;
  fit: "page" | "canvas";
  width?: number;
  height?: number;
  /** A hex, rgb()/hsl(), a spec colour name, or "" for the page's ground. */
  background: string;
  /** Replaces the theme's accent on this design; absent for the theme's own. */
  accent?: string;
  /** Keeps the design in one theme; absent to follow the app. */
  theme?: "light" | "dark";
}

/** The saved spec in the editor's shape (the server's is already normalized). */
export function readDesignSpec(raw: unknown): DesignSpec {
  const source = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const html = typeof raw === "string" ? raw : typeof source.html === "string" ? source.html : "";
  const spec: DesignSpec = {
    html,
    css: typeof source.css === "string" ? source.css : "",
    fit: source.fit === "canvas" ? "canvas" : "page",
    background: typeof source.background === "string" ? source.background : "",
  };
  if (spec.fit === "canvas") {
    spec.width = typeof source.width === "number" ? source.width : 1080;
    spec.height = typeof source.height === "number" ? source.height : 1350;
  }
  if (typeof source.accent === "string" && source.accent) spec.accent = source.accent;
  if (source.theme === "light" || source.theme === "dark") spec.theme = source.theme;
  return spec;
}
