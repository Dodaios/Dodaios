/**
 * A memory page's Markdown, set as a document at the reading measure.
 *
 * Wikilinks arrive pre-resolved from `prepareBody`: a link to a page that
 * exists opens it; a link to a page that does not exist yet is drawn dashed
 * and offers to create it.
 */
import { useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { useT } from "@/i18n";
import { LINK_SCHEME, MISSING_SCHEME } from "@/lib/memoryModel";

export function MarkdownBody({
  markdown,
  onOpen,
  onCreate,
}: {
  markdown: string;
  onOpen: (path: string) => void;
  onCreate?: (title: string) => void;
}) {
  const t = useT();
  const components = useMemo<Components>(
    () => ({
      a: ({ href, children }) => {
        if (href?.startsWith(LINK_SCHEME)) {
          const path = decodeURIComponent(href.slice(LINK_SCHEME.length));
          return (
            <a
              href={href}
              data-memory-link={path}
              onClick={(event) => {
                event.preventDefault();
                onOpen(path);
              }}
              className="font-medium text-foreground-strong underline decoration-border-strong decoration-1 underline-offset-[3px] transition-colors hover:decoration-accent"
            >
              {children}
            </a>
          );
        }
        if (href?.startsWith(MISSING_SCHEME)) {
          const title = decodeURIComponent(href.slice(MISSING_SCHEME.length));
          return (
            <a
              href={href}
              title={t("memory_view.link_missing")}
              onClick={(event) => {
                event.preventDefault();
                onCreate?.(title);
              }}
              className="text-muted-foreground underline decoration-dashed decoration-1 underline-offset-[3px] hover:text-foreground"
            >
              {children}
            </a>
          );
        }
        return (
          <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="text-accent underline-offset-[3px] hover:underline"
          >
            {children}
          </a>
        );
      },
      h1: ({ children }) => (
        <h2 className="mb-3 mt-10 text-2xl font-semibold tracking-tight text-foreground-strong first:mt-0">{children}</h2>
      ),
      h2: ({ children }) => (
        <h2 className="mb-3 mt-9 text-xl font-semibold tracking-tight text-foreground-strong first:mt-0">{children}</h2>
      ),
      h3: ({ children }) => (
        <h3 className="mb-2 mt-7 text-lg font-semibold text-foreground-strong first:mt-0">{children}</h3>
      ),
      h4: ({ children }) => (
        <h4 className="mb-2 mt-6 text-base font-semibold text-foreground-strong first:mt-0">{children}</h4>
      ),
      p: ({ children }) => <p className="my-3.5 leading-7 text-foreground">{children}</p>,
      ul: ({ children }) => (
        <ul className="my-3.5 list-disc space-y-1.5 pl-5 leading-7 text-foreground marker:text-foreground-faint">
          {children}
        </ul>
      ),
      ol: ({ children }) => (
        <ol className="my-3.5 list-decimal space-y-1.5 pl-6 leading-7 text-foreground marker:text-sm marker:tabular-nums marker:text-foreground-faint">
          {children}
        </ol>
      ),
      li: ({ children }) => <li className="pl-1">{children}</li>,
      blockquote: ({ children }) => (
        <blockquote className="my-5 border-l-2 border-border-strong pl-4 text-foreground-secondary">{children}</blockquote>
      ),
      hr: () => <hr className="my-8 border-border" />,
      strong: ({ children }) => <strong className="font-semibold text-foreground-strong">{children}</strong>,
      table: ({ children }) => (
        <div className="my-5 overflow-x-auto rounded-lg border border-border">
          <table className="w-full border-collapse text-sm">{children}</table>
        </div>
      ),
      th: ({ children }) => (
        <th className="border-b border-border bg-secondary px-3 py-2 text-left font-medium text-foreground">{children}</th>
      ),
      td: ({ children }) => (
        <td className="border-b border-border px-3 py-2 align-top text-foreground-secondary">{children}</td>
      ),
      pre: ({ children }) => (
        <pre className="my-5 overflow-x-auto rounded-lg border border-border bg-secondary p-4 font-mono text-sm leading-6 text-foreground [&>code]:bg-transparent [&>code]:p-0">
          {children}
        </pre>
      ),
      code: ({ children, node: _node, ...rest }) => (
        <code {...rest} className="rounded-sm bg-secondary px-1 py-0.5 font-mono text-[0.9em] text-foreground">
          {children}
        </code>
      ),
    }),
    [onCreate, onOpen, t],
  );

  return (
    <div className="text-reading" data-testid="memory-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
