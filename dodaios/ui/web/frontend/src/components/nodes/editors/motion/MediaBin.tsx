/**
 * The video editor's left panel: what goes INTO the clip.
 *
 * * Media: the clip's library. Files come in with the import button or by
 *   dropping them anywhere on the panel; each shows its poster, name and
 *   length, and goes onto the timeline with its "+" (at the playhead) or by
 *   being dragged there.
 * * Text: a text layer of each style, at the playhead.
 * * Cards: the animated cards the clip always had (title, number, chart...).
 * * Captions: captions from the speech, by local speech recognition, and
 *   their look.
 */
import { useRef, useState, type DragEvent as ReactDragEvent, type ReactNode } from "react";
import { AudioLines, Captions, Film, Image as ImageIcon, LayoutTemplate, Loader2, Plus, Type, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { MenuItem } from "../controls";
import { mediaUrl, sideFile } from "./clipApi";
import { TEXT_STYLES, CaptionStyle, type Change } from "./ClipInspector";
import { SCENE_KINDS, formatClock, type CardKind, type MediaEntry, type MotionSpec } from "./motionModel";
import { SCENE_ICONS, kindKey } from "./sceneKinds";
import { MEDIA_DRAG_TYPE } from "./TrackTimeline";

export type BinTab = "media" | "text" | "cards" | "captions";

export interface Upload {
  name: string;
  share: number;
  error?: string;
}

export interface MediaBinProps {
  nodeId: string;
  spec: MotionSpec;
  tab: BinTab;
  onTab: (tab: BinTab) => void;
  uploads: Upload[];
  onFiles: (files: File[]) => void;
  onAddMedia: (id: string) => void;
  onAddText: (style: string) => void;
  onAddCard: (kind: CardKind) => void;
  onCaptions: () => void;
  captionsBusy: boolean;
  captionsError: string;
  changeSpec: Change<MotionSpec>;
}

const TABS: { id: BinTab; icon: typeof Film }[] = [
  { id: "media", icon: Film },
  { id: "text", icon: Type },
  { id: "cards", icon: LayoutTemplate },
  { id: "captions", icon: Captions },
];

export function MediaBin(props: MediaBinProps) {
  const { nodeId, spec, tab, uploads } = props;
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.bin.${key}`);
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const onDrop = (event: ReactDragEvent<HTMLDivElement>) => {
    setOver(false);
    if (!event.dataTransfer.files.length) return;
    event.preventDefault();
    props.onFiles([...event.dataTransfer.files]);
  };

  const media = Object.entries(spec.media ?? {});
  let body: ReactNode;
  if (tab === "media") {
    body = (
      <div className="flex flex-col gap-2">
        <Button size="sm" className="gap-1.5" onClick={() => input.current?.click()} data-testid="clip-import">
          <Upload className="h-3.5 w-3.5" aria-hidden />
          {k("import")}
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          accept="video/*,audio/*,image/*,.mkv,.mov,.m4a"
          className="hidden"
          onChange={(event) => {
            if (event.target.files?.length) props.onFiles([...event.target.files]);
            event.target.value = "";
          }}
          data-testid="clip-import-input"
        />
        {uploads.map((upload) => (
          <div key={upload.name} className="rounded-md border border-border px-2 py-1.5 text-xs">
            <div className="flex items-center gap-1.5">
              {!upload.error && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
              <span className="min-w-0 flex-1 truncate">{upload.name}</span>
            </div>
            {upload.error ? (
              <p className="mt-1 text-destructive">{upload.error}</p>
            ) : (
              <div className="mt-1 h-1 overflow-hidden rounded bg-muted">
                <div className="h-full bg-accent transition-[width]" style={{ width: `${Math.round(upload.share * 100)}%` }} />
              </div>
            )}
          </div>
        ))}
        {media.length === 0 && !uploads.length && <p className="px-1 py-6 text-center text-xs text-muted-foreground">{k("empty")}</p>}
        <div className="grid grid-cols-2 gap-2">
          {media.map(([id, entry]) => (
            <MediaCard key={id} nodeId={nodeId} id={id} entry={entry} onAdd={() => props.onAddMedia(id)} />
          ))}
        </div>
      </div>
    );
  } else if (tab === "text") {
    body = (
      <div className="flex flex-col gap-1.5">
        {TEXT_STYLES.map((style) => (
          <button
            key={style}
            type="button"
            onClick={() => props.onAddText(style)}
            className="flex items-center justify-between rounded-md border border-border bg-background/40 px-3 py-2 text-left hover:border-accent"
            data-testid={`clip-add-text-${style}`}
          >
            <span className={cn(style === "title" && "text-base font-extrabold", style === "subtitle" && "font-semibold", style === "label" && "text-xs font-bold uppercase tracking-widest", style === "quote" && "font-serif italic", "text-sm")}>
              {t(`nodes.editor.motion.video.styles.${style}`)}
            </span>
            <Plus className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
          </button>
        ))}
        <p className="pt-1 text-xs text-muted-foreground">{k("textHint")}</p>
      </div>
    );
  } else if (tab === "cards") {
    body = (
      <div className="-mx-1">
        <AddSceneItems onAdd={props.onAddCard} />
        <p className="px-2 pt-2 text-xs text-muted-foreground">{k("cardsHint")}</p>
      </div>
    );
  } else {
    const count = spec.captions?.items.length ?? 0;
    body = (
      <div className="flex flex-col gap-3">
        <p className="text-xs text-muted-foreground">{k("captionsHint")}</p>
        <Button size="sm" className="gap-1.5" onClick={props.onCaptions} disabled={props.captionsBusy} data-testid="clip-auto-captions">
          {props.captionsBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Captions className="h-3.5 w-3.5" aria-hidden />}
          {props.captionsBusy ? k("captionsBusy") : count ? k("captionsAgain") : k("captionsMake")}
        </Button>
        {props.captionsError && <p className="text-xs text-destructive">{props.captionsError}</p>}
        {count > 0 && <p className="text-xs text-muted-foreground">{fill(k("captionsCount"), { n: count })}</p>}
        <CaptionStyle spec={spec} changeSpec={props.changeSpec} />
      </div>
    );
  }

  return (
    <div
      className={cn("flex h-full min-h-0 w-64 shrink-0 flex-col border-r border-border bg-sidebar", over && "bg-accent/10")}
      onDragOver={(event) => {
        if (!event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      data-testid="clip-bin"
    >
      <div role="tablist" aria-label={k("label")} className="flex shrink-0 border-b border-border">
        {TABS.map(({ id, icon: Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => props.onTab(id)}
            className={cn(
              "flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px]",
              tab === id ? "border-b-2 border-accent text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
            data-testid={`clip-tab-${id}`}
          >
            <Icon className="h-4 w-4" aria-hidden />
            {k(`tabs.${id}`)}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">{body}</div>
    </div>
  );
}

function MediaCard({ nodeId, id, entry, onAdd }: { nodeId: string; id: string; entry: MediaEntry; onAdd: () => void }) {
  const t = useT();
  const Icon = entry.kind === "video" ? Film : entry.kind === "audio" ? AudioLines : ImageIcon;
  const poster = entry.kind !== "audio" ? mediaUrl(nodeId, sideFile(entry.file, "poster.jpg")) : "";
  return (
    <div
      className="group relative overflow-hidden rounded-md border border-border bg-background/50"
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData(MEDIA_DRAG_TYPE, id);
        event.dataTransfer.effectAllowed = "copy";
      }}
      title={entry.name}
      data-testid={`clip-media-${id}`}
    >
      <div className="relative grid place-items-center overflow-hidden bg-black/60" style={{ aspectRatio: "16 / 9" }}>
        {poster ? <img src={poster} alt="" className="h-full w-full object-cover" draggable={false} /> : <Icon className="h-6 w-6 text-emerald-300" aria-hidden />}
        {entry.kind !== "image" && <span className="absolute bottom-0.5 right-1 rounded bg-black/60 px-1 text-[10px] tabular-nums text-white">{formatClock(entry.seconds)}</span>}
        <button
          type="button"
          onClick={onAdd}
          className="absolute right-1 top-1 grid h-6 w-6 place-items-center rounded-full bg-accent text-accent-foreground opacity-0 shadow transition-opacity focus:opacity-100 group-hover:opacity-100"
          aria-label={fill(t("nodes.editor.motion.video.bin.add"), { file: entry.name })}
          data-testid={`clip-media-add-${id}`}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
      <div className="flex items-center gap-1 px-1.5 py-1 text-[11px]">
        <Icon className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden />
        <span className="truncate">{entry.name}</span>
      </div>
    </div>
  );
}

/** The animated cards a clip can hold, each added after the piece under the playhead. */
export function AddSceneItems({ onAdd }: { onAdd: (kind: CardKind) => void }) {
  const t = useT();
  return (
    <div className="w-full">
      {SCENE_KINDS.map((kind) => {
        const Icon = SCENE_ICONS[kind];
        return <MenuItem key={kind} label={t(kindKey(kind))} icon={<Icon aria-hidden />} onClick={() => onAdd(kind)} data-testid={`motion-add-${kind}`} />;
      })}
    </div>
  );
}
