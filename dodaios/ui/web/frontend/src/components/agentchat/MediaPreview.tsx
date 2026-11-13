import { createContext, useContext, useEffect, useRef, useState } from "react";
import { AlertCircle, Download, Maximize2, X } from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";

import { useT } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";

export type MediaKind = "image" | "video" | "audio";

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

export function mediaKind(raw: string): MediaKind | null {
  if (!safeMediaUrl(raw)) return null;
  if (raw.startsWith("data:image/")) return "image";
  const url = new URL(raw, "http://chat.local");
  const hint = new URLSearchParams(url.hash.slice(1)).get("jarvis-media")?.split("/")[0];
  if (hint === "image" || hint === "video" || hint === "audio") return hint;
  let path: string;
  try { path = decodeURIComponent(url.pathname); } catch { return null; }
  path = path.replace(/\/(download|raw|view)$/, "");
  return EXTENSIONS[path.split(".").pop()?.toLowerCase() ?? ""] ?? null;
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
 * small, the way a sent picture stands above the person's message.
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
  if (kind === "image" && display === "files" && safe) return <span className="block min-w-0 max-w-full" data-testid="chat-media" data-kind="image" data-display="files">
    <MediaDownloadLink href={safe} label={label} />
  </span>;
  return <Dialog.Root open={expanded} onOpenChange={setExpanded}><span className={cn("block min-w-0 max-w-full", !bare && "my-3")} data-testid="chat-media" data-kind={kind}>
    {failed ? <span role="status" className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
      <AlertCircle aria-hidden className="h-4 w-4 shrink-0" />{unavailable}
      {safe ? <button type="button" onClick={() => { setFailedSource(null); setRevision(value => value + 1); }} className="shrink-0 rounded px-2 py-1 text-foreground underline focus-visible:ring-2 focus-visible:ring-ring">{t("chat_media.retry")}</button> : null}
    </span> : kind === "image" ? <Dialog.Trigger asChild><button type="button"
      aria-label={t("chat_media.expand").replace("{file}", label)}
      className="group relative block max-w-full rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <img key={revision} src={safe!} alt={label} loading="lazy" decoding="async" onError={() => { setFailedSource(src); setExpanded(false); }}
        className={cn("m-0 max-w-full rounded-lg object-contain", thumb ? "max-h-[260px] max-w-[min(100%,360px)] border border-border/70" : bare ? "max-h-[440px] border border-border/70" : "max-h-[520px]")} />
      <Maximize2 aria-hidden className="absolute bottom-2 right-2 h-6 w-6 rounded bg-background/90 p-1 text-foreground opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100" />
    </button></Dialog.Trigger> : kind === "video" ? <video ref={node => { playerRef.current = node; }} key={`${revision}:${safe}`} src={safe!} aria-label={label} controls playsInline preload="metadata"
      onError={() => { setFailedSource(src); setExpanded(false); }} className="max-h-[520px] w-full rounded-lg bg-muted" />
      : <audio ref={node => { playerRef.current = node; }} key={`${revision}:${safe}`} src={safe!} aria-label={label} controls preload="metadata" onError={() => { setFailedSource(src); setExpanded(false); }} className="w-full" />}
    {bare ? null : safe ? <MediaDownloadLink href={safe} label={label} /> : <span className="text-xs text-muted-foreground">{label}</span>}
    {kind === "image" && safe ? <MediaViewerContent src={safe} label={label} /> : null}
  </span></Dialog.Root>;
}

/** A picture's or file's link under it: a file the chat stored downloads, any other address opens outside the app. */
function MediaDownloadLink({ href, label }: { href: string; label: string }) {
  const t = useT();
  return <a href={href} download={href.startsWith("/api/outputs/") ? true : undefined}
    onClick={event => {
      if (!href.startsWith("/api/outputs/")) {
        event.preventDefault();
        void openExternalUrl(new URL(href, window.location.href).href);
      }
    }} className="mt-1 inline-flex items-center gap-1.5 text-xs text-muted-foreground underline underline-offset-2">
    <Download aria-hidden className="h-3 w-3" />{t(href.startsWith("/api/outputs/") ? "chat_media.download" : "chat_media.open_file")} · {label}
  </a>;
}
