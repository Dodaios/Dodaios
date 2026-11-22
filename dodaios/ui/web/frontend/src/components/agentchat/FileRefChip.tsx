import { useContext } from "react";
import { File, Folder } from "lucide-react";

import { QuickTooltip } from "@/components/ui/tooltip";
import { ChatFileIcon, type FileRef } from "./chatPaths";
import { fileRefLabel } from "./fileRefs";

/** Past this many characters a label may wrap, so a very long name cannot push the column sideways. */
const NOWRAP_MAX = 48;

/**
 * A file or folder a thread's answer names, drawn as a reference instead of
 * code: its file-type glyph, then its name and line in the signal colour
 * (`config.py · L3134`). The path as the answer wrote it shows on hover, and a
 * click opens the file beside the conversation, at that line.
 *
 * The look (glyph in front, name and line, accent text, underline on hover,
 * full path in a tooltip) is adapted from pingdotgg/t3code @ 2c4310eb
 * (apps/web/src/components/chat/MarkdownFileLink.tsx, ContextChip.tsx),
 * MIT License, Copyright (c) 2026 T3 Tools Inc. — third_party/t3code/LICENSE.
 * Changes: the explorer's own file-type glyphs, a folder glyph for folders,
 * and an inline box instead of an inline-flex chip, so punctuation after it
 * never wraps onto its own line.
 */
export function FileRefChip({ fileRef, written, suffix, onOpen }: {
  fileRef: FileRef;
  /** The reference as the answer wrote it (`core/config.py:3134`). */
  written: string;
  /** A parent folder that tells this file from a same-named one in the answer. */
  suffix?: string;
  onOpen: () => void;
}) {
  const Icon = useContext(ChatFileIcon);
  const folder = /[\\/]$/.test(fileRef.path);
  const label = fileRefLabel(fileRef, suffix);
  const glyph = "mr-[0.25em] inline-block h-[1em] w-[1em] shrink-0 align-[-0.15em]";
  return <QuickTooltip side="top" className="inline" content={<span className="font-mono text-xs [overflow-wrap:anywhere]">{written}</span>}>
    <a href={`#jarvis-local=${encodeURIComponent(fileRef.path)}`} data-testid="chat-path-link" data-file-ref={folder ? "folder" : "file"}
      className={`not-prose group cursor-pointer rounded-sm font-medium text-accent no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${label.length <= NOWRAP_MAX ? "whitespace-nowrap" : ""}`}
      onClick={(event) => { event.preventDefault(); onOpen(); }}>
      {folder
        ? <Folder aria-hidden className={`${glyph} text-muted-foreground`} />
        : Icon ? <Icon path={fileRef.path} className={glyph} /> : <File aria-hidden className={`${glyph} text-muted-foreground`} />}
      <span className="underline decoration-transparent decoration-1 underline-offset-[0.2em] transition-colors group-hover:decoration-current motion-reduce:transition-none">{label}</span>
    </a>
  </QuickTooltip>;
}
