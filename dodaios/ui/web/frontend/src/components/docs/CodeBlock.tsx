import { Fragment, useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import type { ShikiTransformer } from "shiki";

import { robustCopy } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";

/**
 * Shiki-based code block with copy button and language tag.
 *
 * Shiki is ESM-only and large, so each language is lazy-loaded only when a
 * guide actually contains that kind of code. Highlighters are cached per
 * canonical language; opening ordinary prose docs never downloads Shiki.
 *
 * If the language isn't recognized, fall back to ``txt`` without highlighting.
 */
type ShikiHighlighterApi = {
  codeToHtml: (
    code: string,
    opts: {
      lang: string;
      themes: { light: string; dark: string };
      defaultColor: string;
      transformers?: ShikiTransformer[];
    },
  ) => string;
};

/**
 * Both themes are baked into ONE highlight pass.
 *
 * Shiki's dual-theme mode writes the light colour into `color:` and the dark
 * one into a `--shiki-dark` custom property on the same span; the rule in
 * index.css picks whichever the app is currently in. That means switching the
 * theme costs nothing — no re-highlight, no second Shiki download, no flash of
 * unstyled code — which matters because these blocks appear inside long guides
 * where re-rendering would jump the scroll position.
 */
const CODE_THEMES = { light: "github-light", dark: "github-dark-default" } as const;

const highlighterPromises = new Map<string, Promise<ShikiHighlighterApi>>();

const SUPPORTED_LANGS = [
  "bash", "shell", "sh", "powershell", "ps1",
  "python", "py", "typescript", "ts", "tsx", "javascript", "js", "jsx",
  "json", "yaml", "yml", "toml", "ini", "xml", "html", "css",
  "rust", "go", "java", "c", "cpp", "csharp", "kotlin", "swift",
  "sql", "diff", "markdown", "md",
];

const LANGUAGE_ALIASES: Record<string, string> = {
  shell: "bash",
  sh: "bash",
  ps1: "powershell",
  py: "python",
  ts: "typescript",
  js: "javascript",
  yml: "yaml",
  md: "markdown",
};

function canonicalLanguage(language: string): string {
  return LANGUAGE_ALIASES[language] ?? language;
}

async function loadHighlighter(language: string): Promise<ShikiHighlighterApi> {
  const cached = highlighterPromises.get(language);
  if (cached) return cached;
  const promise = import("shiki").then(async (shiki) => {
    return await shiki.createHighlighter({
      themes: [CODE_THEMES.light, CODE_THEMES.dark],
      langs: [language],
    });
  });
  highlighterPromises.set(language, promise);
  return promise;
}

interface CodeBlockProps {
  language: string;
  code: string;
  /**
   * Draw the block's own frame — border, language tag, copy button. Off when
   * the caller frames the code itself (a rendered fence's Source view), so two
   * header bars never stack.
   */
  chrome?: boolean;
  /** Less air around the frame: a chat answer, not a long guide. */
  dense?: boolean;
  /** A line (1-based) to mark and bring into view: the one a file reference pointed at. */
  markLine?: number;
}

/** The class the marked line wears; styled in index.css, since Shiki writes it at runtime. */
const MARKED_LINE = "code-line-marked";

export function CodeBlock({ language, code, chrome = true, dense = false, markLine }: CodeBlockProps) {
  const t = useT();
  const [html, setHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const mountedRef = useRef(true);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const lang = SUPPORTED_LANGS.includes(language)
      ? canonicalLanguage(language)
      : "txt";
    if (lang === "txt") {
      setHtml(null);
      return;
    }
    void loadHighlighter(lang)
      .then((highlighter) => {
        if (cancelled || !mountedRef.current) return;
        try {
          const out = highlighter.codeToHtml(code, {
            lang,
            themes: CODE_THEMES,
            defaultColor: "light",
            transformers: markLine ? [{
              line(node, line) {
                if (line === markLine) this.addClassToHast(node, MARKED_LINE);
              },
            }] : [],
          });
          setHtml(out);
        } catch {
          setHtml(null);
        }
      })
      .catch(() => {
        highlighterPromises.delete(lang);
        if (!cancelled && mountedRef.current) setHtml(null);
      });
    return () => {
      cancelled = true;
    };
  }, [language, code, markLine]);

  // The marked line comes into view once it is drawn, and again when the
  // highlighted version replaces the plain one.
  useEffect(() => {
    if (!markLine) return;
    rootRef.current?.querySelector(`.${MARKED_LINE}`)?.scrollIntoView?.({ block: "center" });
  }, [markLine, code, html]);

  const handleCopy = () => {
    void robustCopy(code).then((copied) => {
      if (!copied) return;
      setCopied(true);
      window.setTimeout(() => {
        if (mountedRef.current) setCopied(false);
      }, 1500);
    });
  };

  return (
    <div
      ref={rootRef}
      className={cn(
        "not-prose group relative overflow-hidden",
        chrome && "rounded-lg border border-border bg-card",
        chrome && (dense ? "my-3" : "my-6"),
      )}
    >
      {chrome && (
        <div className="flex h-9 items-center justify-between border-b border-border pl-4 pr-1.5">
          <span className="font-mono text-xs text-muted-foreground">
            {language || "text"}
          </span>
          <button
            type="button"
            onClick={handleCopy}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-sm px-2 text-xs font-medium text-muted-foreground transition-colors",
              "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            )}
            title={t("docs_content.copy_code")}
            aria-label={
              copied ? t("docs_content.code_copied") : t("docs_content.copy_code")
            }
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />
            ) : (
              <Copy className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            <span aria-hidden="true">
              {copied ? t("docs_content.code_copied") : t("docs_content.copy")}
            </span>
            <span className="sr-only" aria-live="polite">
              {copied ? t("docs_content.code_copied") : ""}
            </span>
          </button>
        </div>
      )}
      {/* Body — either Shiki HTML or plain text */}
      {html ? (
        <div
          className="code-block-body overflow-x-auto px-4 py-3.5 font-mono text-sm leading-6 [&_pre]:m-0 [&_pre]:!bg-transparent [&_pre]:font-mono"
          // sanitized by Shiki — our code is only rendered locally
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <pre className="m-0 overflow-x-auto px-4 py-3.5 font-mono text-sm leading-6 text-foreground">
          <code>
            {markLine
              // Line by line only when one is marked; otherwise one text node.
              ? code.split("\n").map((text, index) => <Fragment key={index}>
                {index > 0 && "\n"}
                <span className={cn("line", index + 1 === markLine && MARKED_LINE)}>{text}</span>
              </Fragment>)
              : code}
          </code>
        </pre>
      )}
    </div>
  );
}
