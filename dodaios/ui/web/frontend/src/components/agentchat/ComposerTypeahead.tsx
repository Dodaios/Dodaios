import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

import { groupRuns, type TypeaheadItem } from "@/components/agentchat/typeahead";
import { ToolChoiceIcon } from "@/components/agentchat/ToolChoiceChips";
import { toolIdentityStyle } from "@/components/agentchat/toolIdentity";
import { AgentSwatch } from "@/components/society/AgentSwatch";
import { useSocietyRoster } from "@/components/society/data";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

const PANEL_MAX_HEIGHT = 320;
const VIEWPORT_MARGIN = 8;

/**
 * The list over the composer: what `/`, `@` or `$` offers on this seat.
 *
 * It reads like the list a coding CLI shows in its terminal, because for a
 * coding thread it IS that list: one line per entry, the name in a fixed
 * column of monospace type, the description beside it, nothing else. No icon
 * per kind and, in a coding thread, no headings. A file shows its whole path
 * with the folder part held back. The highlighted entry takes the command
 * colour, and the line under the list says what it takes after its name.
 *
 * The assistant's and the agents' own chats (`grouped`) keep their headings
 * and the faces of the things they name: an agent's swatch, a plugin's mark.
 *
 * Drawn above the card, portalled and fixed like the Combobox panel, so the
 * page's scroll columns cannot clip it. The highlighted row follows the
 * arrow keys the text box receives (`useComposerTypeahead`); the mouse
 * hovers to move it and clicks to pick. `onMouseDown` prevents default so a
 * click never takes focus from the text box — the caret is the whole state.
 */
export function ComposerTypeahead({
  anchorRef,
  open,
  grouped = false,
  trigger,
  items,
  loading,
  activeIndex,
  onHover,
  onPick,
}: {
  anchorRef: RefObject<HTMLElement | null>;
  open: boolean;
  /** Head each run of one group with its name (the assistant's and the agents' chats). */
  grouped?: boolean;
  trigger: string | null;
  items: TypeaheadItem[];
  loading: boolean;
  activeIndex: number;
  onHover: (index: number) => void;
  onPick: (item: TypeaheadItem) => void;
}) {
  const t = useT();
  const listId = useId();
  const listRef = useRef<HTMLDivElement | null>(null);
  const [position, setPosition] = useState<{
    left: number;
    bottom: number;
    width: number;
    maxHeight: number;
  } | null>(null);

  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const anchor = anchorRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      setPosition({
        left: rect.left,
        bottom: window.innerHeight - rect.top + 6,
        width: rect.width,
        maxHeight: Math.max(120, Math.min(PANEL_MAX_HEIGHT, rect.top - VIEWPORT_MARGIN - 6)),
      });
    };
    measure();
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open, anchorRef, items.length]);

  // The highlighted row stays in view as the arrows move it.
  useEffect(() => {
    if (!open) return;
    const row = listRef.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`);
    // jsdom draws no layout and has no scrollIntoView; the browser does.
    if (row && typeof row.scrollIntoView === "function") row.scrollIntoView({ block: "nearest" });
  }, [open, activeIndex]);

  if (!open || !position || !trigger) return null;

  const runs = grouped ? groupRuns(items) : [{ group: "", items }];
  const usage = items[activeIndex]?.argument_hint ? items[activeIndex] : null;
  let runningIndex = 0;

  return createPortal(
    <div
      data-testid="composer-typeahead"
      data-trigger={trigger}
      style={{
        left: position.left,
        bottom: position.bottom,
        width: position.width,
        maxHeight: position.maxHeight,
      }}
      onMouseDown={(ev) => ev.preventDefault()}
      className="fixed z-[70] flex flex-col overflow-hidden rounded-lg border border-border-strong bg-popover text-sm text-foreground shadow-float"
    >
      <div
        role="listbox"
        id={listId}
        aria-label={t("agent_chat.typeahead_label")}
        ref={listRef}
        // One grid for the whole list, so every description starts at the
        // same column (each row is a subgrid of it). The names take the room
        // the longest one needs, up to two fifths of the list.
        className="grid min-h-0 flex-1 grid-cols-[fit-content(40%)_minmax(0,1fr)] content-start gap-x-4 overflow-y-auto p-1"
      >
        {items.length === 0 ? (
          <div className="col-span-2 px-2 py-1.5 text-xs text-muted-foreground" data-testid="composer-typeahead-empty">
            {loading ? t("agent_chat.typeahead_loading") : t("agent_chat.typeahead_empty")}
          </div>
        ) : (
          runs.map((run, runIndex) => (
            <div
              key={`${run.group}-${runIndex}`}
              role="group"
              aria-label={grouped ? groupLabel(run.group, t) : undefined}
              className="col-span-2 grid grid-cols-subgrid"
            >
              {grouped && (
                <div className="col-span-2 px-2 pb-0.5 pt-1.5 text-micro font-semibold text-muted-foreground">
                  {groupLabel(run.group, t)}
                </div>
              )}
              {run.items.map((item) => {
                const index = runningIndex;
                runningIndex += 1;
                const active = index === activeIndex;
                return (
                  <div
                    key={`${item.group}:${item.value}`}
                    role="option"
                    aria-selected={active}
                    data-index={index}
                    data-kind={item.kind}
                    data-testid="composer-typeahead-item"
                    onMouseEnter={() => onHover(index)}
                    onClick={() => onPick(item)}
                    className={cn(
                      "col-span-2 grid cursor-pointer grid-cols-subgrid items-baseline rounded-md px-2 py-1",
                      active && "bg-secondary",
                    )}
                  >
                    <Row item={item} trigger={trigger} active={active} />
                  </div>
                );
              })}
            </div>
          ))
        )}
      </div>
      {usage && (
        <div
          data-testid="composer-typeahead-usage"
          className="shrink-0 truncate border-t border-border px-3 py-1.5 font-mono text-xs text-muted-foreground"
        >
          <span className="text-foreground">
            {trigger}
            {usage.value}
          </span>{" "}
          {usage.argument_hint}
        </div>
      )}
    </div>,
    document.body,
  );
}

/** The two cells of one row: the name column, then what there is to say about it. */
function Row({ item, trigger, active }: { item: TypeaheadItem; trigger: string; active: boolean }) {
  // A plugin or tool of the assistant's catalog, or one of the user's agents:
  // a named thing, shown with its own face and read by its name first.
  const teammate = item.group === "teammates";
  if (item.choice || teammate) {
    return (
      <span className="col-span-2 flex min-w-0 items-center gap-2">
        {teammate ? (
          <TeammateAvatar name={item.label} />
        ) : (
          <span className="tool-identity inline-flex shrink-0" style={toolIdentityStyle(item.choice!)} aria-hidden>
            <ToolChoiceIcon row={item.choice!} size={16} />
          </span>
        )}
        <span className="shrink-0 font-medium">{item.label}</span>
        <Name trigger={trigger} active={active} className="shrink-0 text-xs">
          {item.value}
        </Name>
        {item.hint && <span className="min-w-0 truncate text-xs text-muted-foreground">{item.hint}</span>}
      </span>
    );
  }
  if (item.kind === "file" || item.kind === "folder") {
    // The whole path on one line; when it is too long the folder part gives
    // way and the file's own name stays readable.
    const path = item.value;
    const cut = path.replace(/\/$/, "").lastIndexOf("/") + 1;
    return (
      <span className="col-span-2 flex min-w-0 font-mono text-meta">
        <span className={cn("shrink-0", active ? "text-info" : "text-muted-foreground")}>{trigger}</span>
        <span className="min-w-0 truncate text-muted-foreground">{path.slice(0, cut)}</span>
        <span className={cn("shrink-0", active && "text-info")}>{path.slice(cut)}</span>
      </span>
    );
  }
  return (
    <>
      <Name trigger={trigger} active={active} className="min-w-0 truncate text-meta">
        {item.value}
      </Name>
      <span className="min-w-0 truncate text-xs text-muted-foreground">{item.hint}</span>
    </>
  );
}

/** `/goal`, `@reviewer`, `$deploy`: the word as it will stand in the message. */
function Name({
  trigger,
  active,
  className,
  children,
}: {
  trigger: string;
  active: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span className={cn("font-mono", active ? "text-info" : "text-foreground", className)}>
      {trigger}
      {children}
    </span>
  );
}

/**
 * One of the user's agents, wearing the face it has everywhere else (roster,
 * agent chat, the agents' own "@" list). Mounted only while such a row is on
 * screen, so the roster is read only when the list names an agent; a name the
 * roster does not know still gets its deterministic symbol.
 */
function TeammateAvatar({ name }: { name: string }) {
  const roster = useSocietyRoster();
  const agent = roster.data?.agents.find((a) => a.name === name);
  return (
    <AgentSwatch
      agent={agent ?? ({ name } as Parameters<typeof AgentSwatch>[0]["agent"])}
      size={22}
      className="rounded-md"
    />
  );
}

function groupLabel(group: string, t: (key: string) => string): string {
  // Catalog rows head their runs with the Add menu's own category names.
  if (group.startsWith("tool:")) return t(`chat_tools.${group.slice(5)}`);
  switch (group) {
    case "project":
      return t("agent_chat.typeahead_group_project");
    case "account":
      return t("agent_chat.typeahead_group_account");
    case "plugins":
      return t("agent_chat.typeahead_group_plugins");
    case "cli":
      return t("agent_chat.typeahead_group_cli");
    case "jarvis":
      return t("agent_chat.typeahead_group_jarvis");
    case "agents":
      return t("agent_chat.typeahead_group_agents");
    case "teammates":
      return t("nav.agents");
    case "files":
      return t("agent_chat.typeahead_group_files");
    default:
      return group;
  }
}
