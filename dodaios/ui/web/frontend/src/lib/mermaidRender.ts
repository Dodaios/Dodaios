/**
 * A diagram written as Mermaid text, drawn to SVG.
 *
 * Coding agents describe a flow, a sequence or a structure as a fenced
 * `mermaid` block far more reliably than they place boxes by hand, so the
 * chat draws that block. The library is large and most answers carry no
 * diagram: it loads with the first one.
 *
 * The SVG is not put into the app's page. The caller shows it in the visual
 * frame (`RenderedFence`), a sandboxed document of its own, so a label in the
 * diagram can never act in the app. Labels are SVG text, not HTML: their
 * size is measured here and must hold in that other document, whose only
 * styles are the diagram's own.
 */
import type { VisualSkin } from "@/components/outputs/RenderedFence";

const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';
/** Longer than any diagram a person reads; a runaway block stays code. */
export const MAX_MERMAID_CHARS = 20_000;

type Mermaid = (typeof import("mermaid"))["default"];

let library: Promise<Mermaid> | null = null;
let serial = 0;

/** The diagram as SVG markup in the given colours. Rejects when the text is no diagram. */
export async function renderMermaid(code: string, dark: boolean, skin: VisualSkin, surface: string): Promise<string> {
  if (code.length > MAX_MERMAID_CHARS) throw new Error("diagram too long");
  const mermaid = await (library ??= import("mermaid").then((module) => module.default));
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "base",
    fontFamily: FONT,
    htmlLabels: false,
    // A little tighter than the library's own spacing: a figure in a conversation is narrow.
    flowchart: { htmlLabels: false, useMaxWidth: true, nodeSpacing: 36, rankSpacing: 40 },
    // The library lets the line show through a label on it; here the label covers it.
    themeCSS: ".edgeLabel rect,.labelBkg{opacity:1}",
    themeVariables: {
      darkMode: dark,
      background: "transparent",
      fontFamily: FONT,
      fontSize: "14px",
      textColor: skin.fg,
      lineColor: skin.muted,
      primaryColor: skin.surface,
      primaryTextColor: skin.fg,
      primaryBorderColor: skin.line,
      secondaryColor: skin.surface,
      secondaryTextColor: skin.fg,
      secondaryBorderColor: skin.line,
      tertiaryColor: skin.surface,
      tertiaryTextColor: skin.fg,
      tertiaryBorderColor: skin.line,
      mainBkg: skin.surface,
      nodeBorder: skin.line,
      clusterBkg: "transparent",
      clusterBorder: skin.line,
      titleColor: skin.fg,
      // A label on a line covers the line behind it.
      edgeLabelBackground: surface,
      noteBkgColor: skin.surface,
      noteTextColor: skin.fg,
      noteBorderColor: skin.line,
      actorBkg: skin.surface,
      actorBorder: skin.line,
      actorTextColor: skin.fg,
      signalColor: skin.muted,
      signalTextColor: skin.fg,
      labelBoxBkgColor: skin.surface,
      labelBoxBorderColor: skin.line,
      labelTextColor: skin.fg,
      activationBkgColor: skin.surface,
      activationBorderColor: skin.line,
    },
  });
  // A text that is no diagram is refused here, before the library draws its own error picture.
  await mermaid.parse(code);
  const id = `visual-mermaid-${++serial}`;
  try {
    const { svg } = await mermaid.render(id, code);
    return svg;
  } finally {
    // A failed drawing leaves its scratch element in the page.
    document.getElementById(id)?.remove();
    document.getElementById(`d${id}`)?.remove();
  }
}
