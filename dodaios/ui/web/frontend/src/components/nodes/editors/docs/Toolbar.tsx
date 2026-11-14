/**
 * The document editor's toolbar: the kind of block, the marks, lists and
 * quotes, links, what can be inserted, and the table's own commands while
 * the caret is in a table.
 *
 * Every control mirrors the selection (`useEditorState`), says its shortcut
 * in its tooltip and only offers what the page can draw from Markdown.
 */
import { useRef, useState, type FormEvent } from "react";
import { useEditorState, type Editor } from "@tiptap/react";
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  BarChart3,
  Bold,
  ChevronDown,
  Code,
  Gauge,
  Image as ImageIcon,
  Italic,
  Link,
  List,
  ListChecks,
  ListOrdered,
  ListTree,
  Minus,
  Plus,
  Quote,
  SquareCode,
  Strikethrough,
  Table,
  Unlink,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { useT } from "@/i18n";
import { ChartEditor } from "../charts/ChartEditor";
import { starterChart } from "../charts/chartModel";
import { MenuItem, Popover, Select, ToolbarButton, ToolbarGroup, ToolbarSeparator } from "../controls";
import { SAFE_LINK } from "./extensions";
import { CALLOUT_TONES, isCalloutTone } from "./markdown/parse";
import { chartSource } from "./views/ChartBlockView";
import { TONE_ICON } from "./views/CalloutView";

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
/** A shortcut as this platform writes it: "Mod-Shift-8" → "⇧⌘8" or "Ctrl+Shift+8". */
export function keys(combo: string): string {
  const parts = combo.split("-");
  if (!IS_MAC) return parts.map((part) => (part === "Mod" ? "Ctrl" : part)).join("+");
  const symbols: Record<string, string> = { Mod: "⌘", Shift: "⇧", Alt: "⌥" };
  const order = ["Alt", "Shift", "Mod"];
  const mods = parts.slice(0, -1).sort((a, b) => order.indexOf(a) - order.indexOf(b));
  return mods.map((part) => symbols[part] ?? part).join("") + parts[parts.length - 1].toUpperCase();
}

/** The block kinds the select offers: text, then the page's three heading steps. */
const BLOCK_KINDS = ["paragraph", "h2", "h3", "h4"] as const;

/** A typed address as a link the page keeps: "example.com" becomes "https://example.com". */
export function linkHref(typed: string): string | null {
  const value = typed.trim();
  if (!value) return null;
  if (SAFE_LINK.test(value)) return value;
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return `mailto:${value}`;
  if (/^[^\s/]+\.[^\s]{2,}/.test(value) && !/^[a-z][a-z0-9+.-]*:/i.test(value)) return `https://${value}`;
  return null;
}

export interface DocsToolbarProps {
  editor: Editor;
  linkOpen: boolean;
  onLinkOpenChange: (open: boolean) => void;
  outlineOpen: boolean;
  onOutlineToggle: () => void;
  onPickPicture: () => void;
}

export function DocsToolbar({ editor, linkOpen, onLinkOpenChange, outlineOpen, onOutlineToggle, onPickPicture }: DocsToolbarProps) {
  const t = useT();
  const [newChart, setNewChart] = useState(false);
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => {
      const heading = [1, 2, 3, 4, 5, 6].find((level) => e.isActive("heading", { level })) ?? 0;
      const inSummary = e.state.selection.$from.parent.type.name === "summary";
      const calloutTone = e.isActive("callout") ? String(e.getAttributes("callout").tone ?? "note") : null;
      const inTable = e.isActive("table");
      const cellAlign = inTable
        ? String(e.getAttributes("tableCell").align ?? e.getAttributes("tableHeader").align ?? "")
        : "";
      return {
        heading,
        inSummary,
        bold: e.isActive("bold"),
        italic: e.isActive("italic"),
        strike: e.isActive("strike"),
        code: e.isActive("code"),
        link: e.isActive("link"),
        bulletList: e.isActive("bulletList"),
        orderedList: e.isActive("orderedList"),
        taskList: e.isActive("taskList"),
        blockquote: e.isActive("blockquote"),
        codeBlock: e.isActive("codeBlock"),
        calloutTone,
        inTable,
        cellAlign,
      };
    },
  });
  // The summary is one plain line: block and mark controls do not apply there.
  const off = state.inSummary;
  const run = () => editor.chain().focus();

  const blockValue = state.heading === 0 ? "paragraph" : `h${state.heading}`;
  const blockOptions = [
    ...BLOCK_KINDS.map((kind) => ({ value: kind, label: t(`nodes.editor.docs.block.${kind}`) })),
    // A heading level the select does not offer still shows what it is.
    ...(state.heading && ![2, 3, 4].includes(state.heading)
      ? [{ value: `h${state.heading}`, label: t("nodes.editor.docs.block.other").replace("{0}", String(state.heading)) }]
      : []),
  ];
  const setBlock = (value: string) => {
    if (value === "paragraph") run().setParagraph().run();
    else run().setHeading({ level: Number(value.slice(1)) as 1 | 2 | 3 | 4 | 5 | 6 }).run();
  };

  return (
    <>
      <ToolbarGroup label={t("nodes.editor.docs.groups.block")}>
        <Select
          value={blockValue}
          options={blockOptions}
          onChange={setBlock}
          label={t("nodes.editor.docs.block.label")}
          disabled={off || state.codeBlock}
          className="w-40"
          testId="docs-block-kind"
        />
      </ToolbarGroup>
      <ToolbarSeparator />
      <ToolbarGroup label={t("nodes.editor.docs.groups.marks")}>
        <ToolbarButton label={t("nodes.editor.docs.mark.bold")} shortcut={keys("Mod-b")} icon={<Bold aria-hidden />} active={state.bold} disabled={off} onClick={() => run().toggleBold().run()} data-testid="docs-bold" />
        <ToolbarButton label={t("nodes.editor.docs.mark.italic")} shortcut={keys("Mod-i")} icon={<Italic aria-hidden />} active={state.italic} disabled={off} onClick={() => run().toggleItalic().run()} data-testid="docs-italic" />
        <ToolbarButton label={t("nodes.editor.docs.mark.strike")} shortcut={keys("Mod-Shift-s")} icon={<Strikethrough aria-hidden />} active={state.strike} disabled={off} onClick={() => run().toggleStrike().run()} data-testid="docs-strike" />
        <ToolbarButton label={t("nodes.editor.docs.mark.code")} shortcut={keys("Mod-e")} icon={<Code aria-hidden />} active={state.code} disabled={off} onClick={() => run().toggleCode().run()} data-testid="docs-code" />
        <LinkControl editor={editor} open={linkOpen} onOpenChange={onLinkOpenChange} active={state.link} disabled={off} />
      </ToolbarGroup>
      <ToolbarSeparator />
      <ToolbarGroup label={t("nodes.editor.docs.groups.lists")}>
        <ToolbarButton label={t("nodes.editor.docs.list.bullet")} shortcut={keys("Mod-Shift-8")} icon={<List aria-hidden />} active={state.bulletList} disabled={off} onClick={() => run().toggleBulletList().run()} data-testid="docs-bullet-list" />
        <ToolbarButton label={t("nodes.editor.docs.list.ordered")} shortcut={keys("Mod-Shift-7")} icon={<ListOrdered aria-hidden />} active={state.orderedList} disabled={off} onClick={() => run().toggleOrderedList().run()} data-testid="docs-ordered-list" />
        <ToolbarButton label={t("nodes.editor.docs.list.task")} shortcut={keys("Mod-Shift-9")} icon={<ListChecks aria-hidden />} active={state.taskList} disabled={off} onClick={() => run().toggleTaskList().run()} data-testid="docs-task-list" />
      </ToolbarGroup>
      <ToolbarSeparator />
      <ToolbarGroup label={t("nodes.editor.docs.groups.blocks")}>
        <ToolbarButton label={t("nodes.editor.docs.block.quote")} shortcut={keys("Mod-Shift-b")} icon={<Quote aria-hidden />} active={state.blockquote} disabled={off} onClick={() => run().toggleBlockquote().run()} data-testid="docs-quote" />
        <Popover
          role="menu"
          label={t("nodes.editor.docs.callout.label")}
          trigger={
            <ToolbarButton
              label={t("nodes.editor.docs.callout.label")}
              icon={(() => {
                const Icon = TONE_ICON[isCalloutTone(state.calloutTone) ? state.calloutTone : "note"];
                return <Icon aria-hidden />;
              })()}
              trailing={<ChevronDown className="!h-3 !w-3" aria-hidden />}
              active={state.calloutTone !== null}
              disabled={off}
              data-testid="docs-callout-menu"
            />
          }
        >
          {(close) => (
            <>
              {CALLOUT_TONES.map((tone) => {
                const Icon = TONE_ICON[tone];
                return (
                  <MenuItem
                    key={tone}
                    label={t(`nodes.editor.docs.callout.tones.${tone}`)}
                    icon={<Icon aria-hidden />}
                    checked={state.calloutTone === tone}
                    onClick={() => {
                      run().setCallout(tone).run();
                      close();
                    }}
                    data-testid={`docs-callout-${tone}`}
                  />
                );
              })}
              {state.calloutTone !== null && (
                <MenuItem
                  label={t("nodes.editor.docs.callout.remove")}
                  onClick={() => {
                    run().unsetCallout().run();
                    close();
                  }}
                />
              )}
            </>
          )}
        </Popover>
        <ToolbarButton label={t("nodes.editor.docs.block.code")} shortcut={keys("Mod-Alt-c")} icon={<SquareCode aria-hidden />} active={state.codeBlock} disabled={off} onClick={() => run().toggleCodeBlock().run()} data-testid="docs-code-block" />
      </ToolbarGroup>
      <ToolbarSeparator />
      <Popover
        role="menu"
        label={t("nodes.editor.docs.insert.label")}
        trigger={
          <ToolbarButton
            label={t("nodes.editor.docs.insert.label")}
            icon={<Plus aria-hidden />}
            showLabel
            trailing={<ChevronDown className="!h-3 !w-3" aria-hidden />}
            disabled={off}
            data-testid="docs-insert"
          />
        }
      >
        {(close) => (
          <>
            <MenuItem
              label={t("nodes.editor.docs.insert.table")}
              icon={<Table aria-hidden />}
              onClick={() => {
                run().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
                close();
              }}
              data-testid="docs-insert-table"
            />
            <MenuItem
              label={t("nodes.editor.chart.insert")}
              icon={<BarChart3 aria-hidden />}
              onClick={() => {
                close();
                setNewChart(true);
              }}
              data-testid="docs-insert-chart"
            />
            <MenuItem
              label={t("nodes.editor.docs.insert.metrics")}
              icon={<Gauge aria-hidden />}
              onClick={() => {
                run().insertMetrics(t("nodes.editor.docs.insert.metrics_starter")).run();
                close();
              }}
              data-testid="docs-insert-metrics"
            />
            <MenuItem
              label={t("nodes.editor.docs.insert.picture")}
              icon={<ImageIcon aria-hidden />}
              onClick={() => {
                close();
                onPickPicture();
              }}
              data-testid="docs-insert-picture"
            />
            <MenuItem
              label={t("nodes.editor.docs.insert.rule")}
              icon={<Minus aria-hidden />}
              onClick={() => {
                run().setHorizontalRule().run();
                close();
              }}
              data-testid="docs-insert-rule"
            />
          </>
        )}
      </Popover>
      {state.inTable && (
        <>
          <ToolbarSeparator />
          <TableControls editor={editor} align={state.cellAlign} />
        </>
      )}
      <ToolbarSeparator />
      <ToolbarButton
        label={t("nodes.editor.docs.outline.toggle")}
        icon={<ListTree aria-hidden />}
        active={outlineOpen}
        onClick={onOutlineToggle}
        data-testid="docs-outline-toggle"
      />
      {newChart && (
        <ChartEditor
          open
          value={starterChart("column")}
          heading={t("nodes.editor.chart.new")}
          onCancel={() => {
            setNewChart(false);
            editor.commands.focus();
          }}
          onSave={(chart) => {
            setNewChart(false);
            run().insertChart(chartSource(chart)).run();
          }}
        />
      )}
    </>
  );
}

/** The table's rows, columns, column alignment, and removing it. */
function TableControls({ editor, align }: { editor: Editor; align: string }) {
  const t = useT();
  const run = () => editor.chain().focus();
  // Alignment belongs to the whole column in Markdown, so it is set on every cell of it.
  const alignColumn = (value: "left" | "center" | "right" | null) => {
    const { state } = editor;
    const $cell = state.selection.$from;
    let depth = $cell.depth;
    while (depth > 0 && !["tableCell", "tableHeader"].includes($cell.node(depth).type.name)) depth -= 1;
    if (depth < 3) return;
    const column = $cell.index(depth - 1);
    const table = $cell.node(depth - 2);
    const tableStart = $cell.start(depth - 2);
    const tr = state.tr;
    let offset = 0;
    table.forEach((row) => {
      let cellOffset = 0;
      row.forEach((cell, _pos, index) => {
        if (index === column && cell.attrs.align !== value) {
          tr.setNodeMarkup(tableStart + offset + 1 + cellOffset, undefined, { ...cell.attrs, align: value });
        }
        cellOffset += cell.nodeSize;
      });
      offset += row.nodeSize;
    });
    if (tr.docChanged) editor.view.dispatch(tr);
    editor.commands.focus();
  };
  return (
    <ToolbarGroup label={t("nodes.editor.docs.groups.table")}>
      <Popover
        role="menu"
        label={t("nodes.editor.docs.table.label")}
        trigger={
          <ToolbarButton
            label={t("nodes.editor.docs.table.label")}
            icon={<Table aria-hidden />}
            trailing={<ChevronDown className="!h-3 !w-3" aria-hidden />}
            data-testid="docs-table-menu"
          />
        }
      >
        {(close) => {
          const item = (label: string, action: () => boolean, testId: string, destructive = false) => (
            <MenuItem
              label={label}
              destructive={destructive}
              onClick={() => {
                action();
                close();
              }}
              data-testid={testId}
            />
          );
          return (
            <>
              {item(t("nodes.editor.docs.table.row_above"), () => run().addRowBefore().run(), "docs-row-above")}
              {item(t("nodes.editor.docs.table.row_below"), () => run().addRowAfter().run(), "docs-row-below")}
              {item(t("nodes.editor.docs.table.column_left"), () => run().addColumnBefore().run(), "docs-column-left")}
              {item(t("nodes.editor.docs.table.column_right"), () => run().addColumnAfter().run(), "docs-column-right")}
              {item(t("nodes.editor.docs.table.delete_row"), () => run().deleteRow().run(), "docs-delete-row", true)}
              {item(t("nodes.editor.docs.table.delete_column"), () => run().deleteColumn().run(), "docs-delete-column", true)}
              {item(t("nodes.editor.docs.table.delete"), () => run().deleteTable().run(), "docs-delete-table", true)}
            </>
          );
        }}
      </Popover>
      <ToolbarButton label={t("nodes.editor.docs.table.align_left")} icon={<AlignLeft aria-hidden />} active={align === "left" || align === ""} onClick={() => alignColumn(null)} data-testid="docs-align-left" />
      <ToolbarButton label={t("nodes.editor.docs.table.align_center")} icon={<AlignCenter aria-hidden />} active={align === "center"} onClick={() => alignColumn("center")} data-testid="docs-align-center" />
      <ToolbarButton label={t("nodes.editor.docs.table.align_right")} icon={<AlignRight aria-hidden />} active={align === "right"} onClick={() => alignColumn("right")} data-testid="docs-align-right" />
    </ToolbarGroup>
  );
}

/** Add, change or remove the link on the selection. */
function LinkControl({
  editor,
  open,
  onOpenChange,
  active,
  disabled,
}: {
  editor: Editor;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  active: boolean;
  disabled: boolean;
}) {
  const t = useT();
  const field = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [invalid, setInvalid] = useState(false);
  const opening = (next: boolean) => {
    if (next) {
      setText(String(editor.getAttributes("link").href ?? ""));
      setInvalid(false);
    }
    onOpenChange(next);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const href = linkHref(text);
    if (!href) {
      setInvalid(true);
      field.current?.focus();
      return;
    }
    const chain = editor.chain().focus().extendMarkRange("link");
    if (editor.state.selection.empty && !editor.isActive("link")) {
      // No words chosen: the address itself becomes the linked text.
      chain.insertContent({ type: "text", text: text.trim(), marks: [{ type: "link", attrs: { href } }] }).run();
    } else {
      chain.setLink({ href }).run();
    }
    onOpenChange(false);
  };
  return (
    <Popover
      label={t("nodes.editor.docs.link.label")}
      open={open}
      onOpenChange={opening}
      trigger={
        <ToolbarButton
          label={t("nodes.editor.docs.link.label")}
          shortcut={keys("Mod-k")}
          icon={<Link aria-hidden />}
          active={active}
          disabled={disabled}
          data-testid="docs-link"
        />
      }
    >
      <form onSubmit={submit} className="flex w-80 flex-col gap-2 p-1" data-testid="docs-link-form">
        <label className="text-xs text-muted-foreground" htmlFor="docs-link-address">
          {t("nodes.editor.docs.link.address")}
        </label>
        <input
          id="docs-link-address"
          ref={field}
          autoFocus
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setInvalid(false);
          }}
          placeholder="https://"
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? "docs-link-invalid" : undefined}
          className="h-8 rounded-md border border-border-strong bg-input px-2 text-sm text-foreground focus-visible:border-accent focus-visible:outline-none"
        />
        {invalid && (
          <p id="docs-link-invalid" className="text-xs text-warning">
            {t("nodes.editor.docs.link.invalid")}
          </p>
        )}
        <div className="flex justify-end gap-2">
          {active && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                editor.chain().focus().extendMarkRange("link").unsetLink().run();
                onOpenChange(false);
              }}
            >
              <Unlink aria-hidden />
              {t("nodes.editor.docs.link.remove")}
            </Button>
          )}
          <Button type="submit" size="sm" data-testid="docs-link-apply">
            {t("nodes.editor.docs.link.apply")}
          </Button>
        </div>
      </form>
    </Popover>
  );
}

