import { createContext, lazy, Suspense, useContext, useEffect, useRef, useState } from "react";
import { AlertCircle, Download, Maximize2, X } from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";

import { useT } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";

/** `page` is a self-contained HTML file an answer shows: drawn in the visual frame, never loaded as a page of the app. */
export type MediaKind = "image" | "video" | "audio" | "page";

// The visual frame loads with the first page an answer shows.
const PagePreview = lazy(() => import("@/components/outputs/PagePreview").then(module => ({ default: module.PagePreview })));

/** Where the chat keeps the files an answer showed (`dodaios/agent_chat/media.py`). */
const CHAT_MEDIA_PREFIX = "/api/outputs/chat-media-";

/**
 * How a transcript draws its pictures: the picture itself, or only its name
 * and a download link. The Dodaios chat lists the pictures in answers as
 * files; the pictures the person sent are drawn in every transcript.
 */
export type PictureDisplay = "shown" | "files";

/** The picture display of the transcript a message sits in; pictures are shown unless a transcript lists them. */
export const PictureDisplayContext = createContext<PictureDisplay>("shown");

const EXTENSIONS: Record<string, MediaKind> = {
  png: "image", jpg: "image", jpeg: "image", gif: "image", webp: "image", avif: "image", svg: "image", bmp: "image",
  ico: "image", tif: "image", tiff: "image", heic: "image", heif: "image",
  mp4: "video", webm: "video", mov: "video", m4v: "video", ogv: "video",
  avi: "video", mkv: "video", mpeg: "video", mpg: "video", wmv: "video",
  mp3: "audio", wav: "audio", ogg: "audio", m4a: "audio", flac: "audio", aac: "audio",
};

export function safeMediaUrl(raw: string): string | null {
  if (/^data:image\/(?:png|jpeg|gif|webp|avif);base64,[a-zA-Z0-9+/=]+$/.test(raw) && raw.length <= 32 * 1024 * 1024) return raw;
  try {
    const url = new URL(raw, "http://chat.local");
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
    // Unarchived native paths must never turn into accidental app requests.
    if (!raw.startsWith("/") && !/^https?:\/\//i.test(raw)) return null;
    return raw;
  } catch { return null; }
}

/**
 * Whether an address lies outside the app. Drawing a picture, a video or a
 * sound from there makes this window ask a host the text chose, and the
 * address itself can carry what the text wants to tell that host. So such an
 * address is never loaded by drawing a message: it stays a link the reader
 * opens. What the app serves itself and `data:` pictures are not remote.
 *
 * Decided on the address as the browser resolves it: `//host/x` and `/\host/x`
 * begin like a path of the app and still lead to another host.
 */
export function isRemoteMedia(url: string): boolean {
  if (/^data:/i.test(url)) return false;
  try {
    return new URL(url, window.location.href).origin !== window.location.origin;
  } catch {
    return true; // An address nobody can read is not one of the app's.
  }
}

export function mediaKind(raw: string): MediaKind | null {
  if (!safeMediaUrl(raw)) return null;
  if (raw.startsWith("data:image/")) return "image";
  const url = new URL(raw, "http://chat.local");
  const hint = new URLSearchParams(url.hash.slice(1)).get("jarvis-media")?.split("/")[0];
  if (hint === "image" || hint === "video" || hint === "audio") return hint;
  let path: string;
  try { path = decodeURIComponent(url.pathname); } catch { return null; }
  path = path.replace(/\/(download|raw|view)$/, "");
  const extension = path.split(".").pop()?.toLowerCase() ?? "";
  // Only a page the chat stored itself is drawn; a web address ending in .html stays a link.
  if ((extension === "html" || extension === "htm") && raw.startsWith(CHAT_MEDIA_PREFIX)) return "page";
  return EXTENSIONS[extension] ?? null;
}

/**
 * The enlarged picture, or the playing video, of an open dialog. One viewer
 * for a picture in a message and for a file still waiting in a composer.
 * `src` is drawn as given: the caller vouches for it.
 */
export function MediaViewerContent({ src, label, kind = "image" }: { src: string; label: string; kind?: "image" | "video" }) {
  const t = useT();
  return <Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 z-50 bg-background/90" />
    <Dialog.Content aria-describedby={undefined} data-testid="chat-media-viewer" className="fixed left-1/2 top-1/2 z-50 grid max-h-[95vh] w-max max-w-[95vw] -translate-x-1/2 -translate-y-1/2 gap-3 overflow-auto rounded-lg border border-border bg-background p-4 text-foreground shadow-xl">
      <Dialog.Title className="pr-8 text-sm">{label}</Dialog.Title>
      <Dialog.Close aria-label={t("common.close")} className="absolute right-3 top-3 rounded p-1 focus-visible:ring-2 focus-visible:ring-ring"><X aria-hidden className="h-4 w-4" /></Dialog.Close>
      {kind === "video"
        ? <video src={src} aria-label={label} controls autoPlay playsInline className="mx-auto max-h-[80vh] max-w-full rounded bg-muted" />
        : <img src={src} alt={label} className="mx-auto max-h-[80vh] max-w-full object-contain" />}
    </Dialog.Content>
  </Dialog.Portal>;
}

/**
 * Image, video, or audio that a chat message can show without the markdown parser.
 * `bare` draws only the picture itself (no margin, no download line): a
 * thread's screenshot under its line. In a transcript that lists its pictures
 * as files, an image is its download link alone. `thumb` draws the picture
 * as a small fixed tile, cropped to fill it, the way a sent picture stands
 * above the person's message; a click opens it in full.
 *
 * Only what the app serves itself (and a `data:` picture) is drawn. A remote
 * address is the same link in every transcript, whatever its kind, and opens
 * in the browser on a click (`isRemoteMedia`).
 */
export function MediaPreview({ src, label, kind, bare = false, thumb = false }: { src: string; label: string; kind: MediaKind; bare?: boolean; thumb?: boolean }) {
  const t = useT();
  const display = useContext(PictureDisplayContext);
  const [failedSource, setFailedSource] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [revision, setRevision] = useState(0);
  const safe = safeMediaUrl(src);
  const failed = !safe || failedSource === src;
  const unavailable = t("chat_media.unavailable");
  const playerRef = useRef<HTMLMediaElement | null>(null);
  useEffect(() => {
    const player = playerRef.current;
    return () => {
      if (!player) return;
      if (!player.paused) player.pause();
      if (player.networkState !== player.NETWORK_EMPTY) {
        player.removeAttribute("src");
        player.load();
      }
    };
  }, [safe, kind, failed, revision]);
  const remote = safe !== null && isRemoteMedia(safe);
  if (safe && (remote || ((kind === "image" || kind === "page") && display === "files"))) return <span className="block min-w-0 max-w-full" data-testid="chat-media" data-kind={kind} data-display="files" data-remote={remote || undefined}>
    <MediaDownloadLink href={safe} label={label} />
  </span>;
  // The page's figure brings its own margins, caption and download.
  if (kind === "page" && safe) return <span className="block min-w-0 max-w-full" data-testid="chat-media" data-kind="page">
    <Suspense fallback={null}><PagePreview src={safe} label={label} /></Suspense>
  </span>;
  return <Dialog.Root open={expanded} onOpenChange={setExpanded}><span className={cn("block min-w-0 max-w-full", !bare && "my-3")} data-testid="chat-media" data-kind={kind}>
    {failed ? thumb ? <span role="status" title={`${label}: ${unavailable}`}
      // A picture that will not load keeps its tile, so the row stays a row.
      className="flex h-32 w-44 max-w-full flex-col items-center justify-center gap-1.5 rounded-lg border border-border/60 bg-muted/30 px-2 text-center text-xs text-muted-foreground">
      <AlertCircle aria-hidden className="h-4 w-4 shrink-0" />
      <span className="sr-only">{unavailable}</span>
      <span className="w-full truncate">{label}</span>
      {safe ? <button type="button" onClick={() => { setFailedSource(null); setRevision(value => value + 1); }} className="shrink-0 rounded px-2 py-0.5 text-foreground underline focus-visible:ring-2 focus-visible:ring-ring">{t("chat_media.retry")}</button> : null}
    </span> : <span role="status" className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
      <AlertCircle aria-hidden className="h-4 w-4 shrink-0" />{unavailable}
      {safe ? <button type="button" onClick={() => { setFailedSource(null); setRevision(value => value + 1); }} className="shrink-0 rounded px-2 py-1 text-foreground underline focus-visible:ring-2 focus-visible:ring-ring">{t("chat_media.retry")}</button> : null}
    </span> : kind === "image" ? <Dialog.Trigger asChild><button type="button"
      aria-label={t("chat_media.expand").replace("{file}", label)}
      className={cn("group relative block max-w-full rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        // A thumbnail is a fixed tile, so the row never moves while the
        // picture loads, however wide or tall the picture is.
        thumb && "h-32 w-44 overflow-hidden border border-border/60 bg-muted/30")}>
      <img key={revision} src={safe!} alt={label} loading="lazy" decoding="async" onError={() => { setFailedSource(src); setExpanded(false); }}
        className={cn("m-0 max-w-full", thumb ? "h-full w-full object-cover" : cn("rounded-lg object-contain", bare ? "max-h-[440px] border border-border/70" : "max-h-[520px]"))} />
      <Maximize2 aria-hidden className={cn("absolute rounded bg-background/90 p-1 text-foreground opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100", thumb ? "bottom-1.5 right-1.5 h-5 w-5" : "bottom-2 right-2 h-6 w-6")} />
    </button></Dialog.Trigger> : kind === "video" ? <video ref={node => { playerRef.current = node; }} key={`${revision}:${safe}`} src={safe!} aria-label={label} controls playsInline preload="metadata"
      onError={() => { setFailedSource(src); setExpanded(false); }} className="max-h-[520px] w-full rounded-lg bg-muted" />
      : <audio ref={node => { playerRef.current = node; }} key={`${revision}:${safe}`} src={safe!} aria-label={label} controls preload="metadata" onError={() => { setFailedSource(src); setExpanded(false); }} className="w-full" />}
    {bare ? null : safe ? <MediaDownloadLink href={safe} label={label} /> : <span className="text-xs text-muted-foreground">{label}</span>}
    {kind === "image" && safe ? <MediaViewerContent src={safe} label={label} /> : null}
  </span></Dialog.Root>;
}

/**
 * A picture in a Markdown text, drawn by the rule of a chat message
 * (`MediaPreview`): what the app serves itself is shown, a remote address
 * stays a link. For every Markdown renderer besides the chat's own that draws
 * text the person did not write (a trace, the profile, a memory, a document
 * an agent made): the plain `<img>` it would draw otherwise loads whatever
 * address the text names.
 */
export function MarkdownPicture({ src, alt }: { src?: string; alt?: string }) {
  const t = useT();
  const address = src ?? "";
  return <MediaPreview src={address} label={alt || t("chat_media.image_fallback")} kind={mediaKind(address) ?? "image"} />;
}

/** The `components` of a Markdown renderer that draws its pictures by that rule. */
export const MARKDOWN_PICTURES = { img: MarkdownPicture };

/** The address as the browser resolves it; as written when it cannot be read. */
function absoluteAddress(href: string): string {
  try { return new URL(href, window.location.href).href; } catch { return href; }
}

/**
 * A picture's or file's link under it: a file the chat stored downloads, any other address opens outside the app.
 * A remote address shows where it leads when the pointer rests on it: the link's words are the answer's own.
 */
function MediaDownloadLink({ href, label }: { href: string; label: string }) {
  const t = useT();
  return <a href={href} download={href.startsWith("/api/outputs/") ? true : undefined}
    title={isRemoteMedia(href) ? absoluteAddress(href) : undefined}
    onClick={event => {
      if (!href.startsWith("/api/outputs/")) {
        event.preventDefault();
        void openExternalUrl(absoluteAddress(href));
      }
    }} className="mt-1 inline-flex items-center gap-1.5 text-xs text-muted-foreground underline underline-offset-2">
    <Download aria-hidden className="h-3 w-3" />{t(href.startsWith("/api/outputs/") ? "chat_media.download" : "chat_media.open_file")} · {label}
  </a>;
}
