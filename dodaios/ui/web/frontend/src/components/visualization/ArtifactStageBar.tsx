import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { Check, FileText, Image as ImageIcon, Loader2, MoreHorizontal, X } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { robustCopy } from "@/lib/clipboard";
import { anchorOf, canNativeShare, shareFilesNatively } from "@/lib/nativeShare";
import { shareArtifact, type ShareFormat } from "@/hooks/useOutputs";
import { useEventStore } from "@/store/events";

/**
 * The Artifacts stage's one bar, kept quiet on purpose.
 *
 * In the middle a single pill names what is open. On the right: "Share",
 * one overflow menu for everything used now and then (the view — preview,
 * code, files, run —, the star, open in the browser, save a copy, show in
 * folder, previous / next), and a round close button that goes back to the
 * library. No status word for a run that simply succeeded, no icon row.
 */

const ROUND_BUTTON =
  "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border/70 text-muted-foreground " +
  "transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-ring [&_svg]:h-[18px] [&_svg]:w-[18px]";

const TEXT_BUTTON =
  "inline-flex h-9 shrink-0 items-center justify-center rounded-full border border-border/70 px-4 text-base " +
  "text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-ring";

export function StageBar({
  onClose,
  center,
  actions,
}: {
  onClose: () => void;
  /** The title pill (and a run's own actions while it works). */
  center?: ReactNode;
  /** Share and the overflow menu, left of the close button. */
  actions?: ReactNode;
}) {
  const t = useT();
  return (
    <div
      className="grid shrink-0 grid-cols-[1fr_minmax(0,auto)_1fr] items-center gap-3 border-b border-border px-4 py-2.5"
      data-testid="visualization-stage-bar"
    >
      <span aria-hidden />
      <div className="flex min-w-0 items-center justify-center gap-2">{center}</div>
      <div className="flex shrink-0 items-center justify-end gap-2">
        {actions}
        <button
          type="button"
          onClick={onClose}
          aria-label={t("visualization.close")}
          data-testid="visualization-back"
          className={ROUND_BUTTON}
        >
          <X aria-hidden />
        </button>
      </div>
    </div>
  );
}

/** The name of what is open, in one calm pill. */
export function TitlePill({
  title,
  picture,
  suffix,
  status,
}: {
  title: string;
  /** A picture gets a picture glyph; everything else a document. */
  picture: boolean;
  /** The view when it is not the preview ("Code", "Files", …). */
  suffix?: string;
  /** A run's state when it is worth saying (running, failed, …). */
  status?: ReactNode;
}) {
  const Icon = picture ? ImageIcon : FileText;
  return (
    <div className="inline-flex h-10 min-w-0 max-w-[min(40rem,56vw)] items-center gap-2.5 rounded-full border border-border/70 bg-secondary/40 px-4">
      <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden />
      <span
        className="truncate text-base font-medium text-foreground-strong"
        data-testid="visualization-title"
      >
        {title}
      </span>
      {suffix && <span className="shrink-0 text-base text-muted-foreground">· {suffix}</span>}
      {status}
    </div>
  );
}

/* ------------------------------------------------------------------------- */

/** A button that opens a small panel under it; outside click or Escape close it. */
export function BarPopover({
  label,
  trigger,
  triggerClassName,
  testId,
  triggerRef,
  children,
}: {
  label: string;
  trigger: ReactNode;
  triggerClassName: string;
  testId: string;
  triggerRef?: RefObject<HTMLButtonElement>;
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Escape closes the panel, not the stage behind it.
      event.stopPropagation();
      event.preventDefault();
      setOpen(false);
      root.current?.querySelector<HTMLButtonElement>("button")?.focus();
    };
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        onClick={() => setOpen((value) => !value)}
        data-testid={testId}
        className={cn(triggerClassName, open && "bg-secondary text-foreground")}
      >
        {trigger}
      </button>
      {open && (
        <div
          role="menu"
          aria-label={label}
          className={cn(
            "absolute right-0 top-full z-50 mt-2 w-72 rounded-xl border border-border bg-popover p-1.5 shadow-float",
            "animate-in fade-in-0 zoom-in-95 duration-150",
          )}
        >
          {children(close)}
        </div>
      )}
    </div>
  );
}

const ITEM =
  "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-base text-foreground transition-colors " +
  "hover:bg-secondary focus-visible:bg-secondary focus-visible:outline-none disabled:pointer-events-none disabled:opacity-40";

export function MenuItem({
  onSelect,
  disabled,
  testId,
  hint,
  trailing,
  children,
}: {
  onSelect: () => void;
  disabled?: boolean;
  testId?: string;
  /** A quieter second line. */
  hint?: string;
  trailing?: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onSelect}
      disabled={disabled}
      data-testid={testId}
      className={ITEM}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate">{children}</span>
        {hint && <span className="block text-sm text-muted-foreground">{hint}</span>}
      </span>
      {trailing}
    </button>
  );
}

export function MenuChoice({
  chosen,
  onSelect,
  testId,
  children,
}: {
  chosen: boolean;
  onSelect: () => void;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={chosen}
      onClick={onSelect}
      data-testid={testId}
      className={ITEM}
    >
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {chosen && <Check className="h-4 w-4 shrink-0 text-foreground" aria-hidden />}
    </button>
  );
}

export function MenuSeparator() {
  return <div role="separator" className="my-1.5 h-px bg-border" />;
}

export function MenuHeading({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="px-2.5 pb-1.5 pt-1">
      <p className="truncate text-sm font-medium text-foreground-strong">{title}</p>
      {detail && <p className="truncate text-sm text-muted-foreground">{detail}</p>}
    </div>
  );
}

export function MoreMenu({ children }: { children: (close: () => void) => ReactNode }) {
  const t = useT();
  return (
    <BarPopover
      label={t("visualization.more")}
      trigger={<MoreHorizontal aria-hidden />}
      triggerClassName={ROUND_BUTTON}
      testId="visualization-more"
    >
      {children}
    </BarPopover>
  );
}

/* ------------------------------------------------------------------------- */

/** What "Share" acts on: the artifact's file, its name, and whether it is a page. */
export interface ShareTarget {
  slug: string;
  /** The file inside the run; null for a run that left no file to send. */
  path: string | null;
  title: string;
  /** An HTML page — the one kind that can also go out as PDF or picture. */
  page: boolean;
}

/**
 * The address that opens this artifact in the person's own Dodaios — never a
 * public link. It works wherever their Dodaios is reachable (this computer,
 * their own devices), and nowhere else; nothing is uploaded to make it.
 */
export function artifactLink(origin: string, target: { slug: string; path: string | null }): string {
  const params = new URLSearchParams({ view: "visualization", run: target.slug });
  if (target.path) params.set("artifact", target.path);
  return `${origin}/?${params.toString()}`;
}

/** The desktop window opens the share sheet; a browser downloads instead. */
const SHARE_LABELS: Record<ShareFormat, { sheet: string; download: string }> = {
  file: { sheet: "visualization.share_file_sheet", download: "visualization.share_file_download" },
  pdf: { sheet: "visualization.share_pdf_sheet", download: "visualization.share_pdf_download" },
  png: { sheet: "visualization.share_image_sheet", download: "visualization.share_image_download" },
};

function downloadStaged(url: string, name: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

/**
 * "Share": copy the Dodaios link, or hand the file — as it is, or a page as a
 * PDF or picture — to the macOS share sheet. Outside the desktop window the
 * same choices download the file instead. Nothing is ever published: where it
 * goes is the person's own choice in the sheet.
 */
export function ShareMenu({
  target,
  pageExport,
  theme,
}: {
  target: ShareTarget;
  /** The server can draw a page as PDF / picture. */
  pageExport: boolean;
  theme: "light" | "dark";
}) {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [busy, setBusy] = useState<ShareFormat | null>(null);
  const native = canNativeShare();

  const copyLink = useCallback(
    async (close: () => void) => {
      close();
      const ok = await robustCopy(artifactLink(window.location.origin, target));
      pushToast(ok ? "success" : "error", t(ok ? "visualization.share_link_copied" : "visualization.share_link_failed"));
    },
    [pushToast, t, target],
  );

  const shareAs = useCallback(
    async (format: ShareFormat, close: () => void) => {
      if (!target.path) return;
      setBusy(format);
      try {
        const staged = await shareArtifact(target.slug, target.path, {
          format,
          title: target.title,
          theme,
        });
        close();
        if (staged.path && shareFilesNatively([staged.path], anchorOf(triggerRef.current))) return;
        downloadStaged(staged.url, staged.name);
      } catch {
        pushToast("error", t(format === "file" ? "visualization.share_failed" : "visualization.share_export_failed"));
      } finally {
        setBusy(null);
      }
    },
    [pushToast, t, target, theme],
  );

  const label = (format: ShareFormat): string => {
    if (busy === format) return t("visualization.share_preparing");
    return t(SHARE_LABELS[format][native ? "sheet" : "download"]);
  };

  const formats: ShareFormat[] = target.path
    ? target.page && pageExport
      ? ["file", "pdf", "png"]
      : ["file"]
    : [];

  return (
    <BarPopover
      label={t("visualization.share")}
      trigger={t("visualization.share")}
      triggerClassName={TEXT_BUTTON}
      testId="visualization-share"
      triggerRef={triggerRef}
    >
      {(close) => (
        <>
          <MenuItem
            onSelect={() => void copyLink(close)}
            hint={t("visualization.share_link_hint")}
            testId="visualization-share-link"
          >
            {t("visualization.share_link")}
          </MenuItem>
          {formats.length > 0 && <MenuSeparator />}
          {formats.map((format) => (
            <MenuItem
              key={format}
              onSelect={() => void shareAs(format, close)}
              disabled={busy !== null}
              testId={`visualization-share-${format}`}
              trailing={
                busy === format ? (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" aria-hidden />
                ) : null
              }
            >
              {label(format)}
            </MenuItem>
          ))}
          <p className="px-2.5 pb-1 pt-2 text-sm text-muted-foreground">
            {t("visualization.share_private_note")}
          </p>
        </>
      )}
    </BarPopover>
  );
}
