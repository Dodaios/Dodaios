import { useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { CodeXml, File, FileCode, FileText, Film, Image, Music, type LucideIcon } from "lucide-react";

import { PANEL_ICON, PANEL_ROW_BUTTON, PanelEmpty, PanelSection, ShowMore } from "@/components/home/panelParts";
import { fetchOutputsList, type ArtifactSummary, type ArtifactsResponse, type OutputSummary } from "@/hooks/useOutputs";
import { classifyVisual, toVisuals } from "@/hooks/useVisualArtifacts";
import { fill, useT } from "@/i18n";
import { useEventStore } from "@/store/events";

/** How many files show before the rest folds away, and how many unfold. */
export const OUTPUTS_SHOWN = 6;
const OUTPUTS_UNFOLDED = 20;
/** The newest finished runs whose files are read; one listing per run. */
const RUNS_READ = 6;
const RUNS_STALE_MS = 2 * 60_000;
const LISTING_STALE_MS = 5 * 60_000;

export type OutputKind = "image" | "page" | "document" | "video" | "audio" | "code" | "file";

const VIDEO = /\.(mp4|mov|webm|mkv|m4v)$/i;
const AUDIO = /\.(mp3|wav|m4a|ogg|flac)$/i;
const CODE = /\.(m?js|cjs|jsx?|tsx?|py|json|css|sh|rs|go|ya?ml|toml|sql)$/i;
const TEXT = /\.(md|txt|docx?|csv|xlsx?|pptx?)$/i;

/** What a file is, for its icon: the gallery's own kinds, then media and code. */
export function outputKind(path: string): OutputKind {
  const visual = classifyVisual(path);
  if (visual === "image" || visual === "vector") return "image";
  if (visual === "page") return "page";
  if (visual === "document" || TEXT.test(path)) return "document";
  if (VIDEO.test(path)) return "video";
  if (AUDIO.test(path)) return "audio";
  return CODE.test(path) ? "code" : "file";
}

const ICONS: Record<OutputKind, LucideIcon> = {
  image: Image,
  page: CodeXml,
  document: FileText,
  video: Film,
  audio: Music,
  code: FileCode,
  file: File,
};

export interface OutputRow {
  slug: string;
  path: string;
  /** A page's own title, else the file's name. */
  label: string;
  kind: OutputKind;
  mtime: number;
}

/** A run's files as rows; a page is called by its title, like in the library. */
export function outputRows(run: OutputSummary, files: ArtifactSummary[]): OutputRow[] {
  const titles = new Map(toVisuals(run, files).map((visual) => [visual.path, visual.title]));
  return files.map((file) => ({
    slug: run.slug,
    path: file.path,
    label: titles.get(file.path) ?? file.path.split("/").pop() ?? file.path,
    kind: outputKind(file.path),
    mtime: file.mtime,
  }));
}

/**
 * What the assistant made: the files of its newest finished runs, the
 * newest file first — pages, pictures, videos, documents, code. A row opens
 * the file on the Artifacts page (a file that page cannot draw opens its
 * run there).
 *
 * Reads under the keys the navigation rail and the Artifacts page read
 * under, so the three share one answer and the panel adds no listing of
 * its own while they are fresh.
 */
export function PanelOutputs({ name }: { name: string }) {
  const t = useT();
  const requestVisual = useEventStore((s) => s.requestVisual);
  const [open, setOpen] = useState(false);
  const runs = useQuery<OutputSummary[]>({
    queryKey: ["outputs"],
    queryFn: fetchOutputsList,
    staleTime: RUNS_STALE_MS,
    refetchInterval: import.meta.env.MODE === "test" ? false : RUNS_STALE_MS,
    retry: false,
  });
  const recent = useMemo(
    () => (runs.data ?? []).filter((run) => run.status !== "running").slice(0, RUNS_READ),
    [runs.data],
  );
  const rows = useQueries({
    queries: recent.map((run) => ({
      queryKey: ["output-artifacts", run.slug],
      queryFn: async (): Promise<ArtifactsResponse> => {
        const response = await fetch(`/api/outputs/${encodeURIComponent(run.slug)}/artifacts`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      },
      staleTime: LISTING_STALE_MS,
      retry: false,
    })),
    combine: (results) => ({
      loading: results.some((result) => result.isLoading),
      files: results
        .flatMap((result, index) => (result.data ? outputRows(recent[index], result.data.files ?? []) : []))
        .sort((a, b) => b.mtime - a.mtime),
    }),
  });
  const shown = rows.files.slice(0, open ? OUTPUTS_UNFOLDED : OUTPUTS_SHOWN);

  return (
    <PanelSection id="outputs" title={t("sidebar.outputs")}>
      {shown.map((row) => {
        const Icon = ICONS[row.kind];
        return (
          <button key={`${row.slug}::${row.path}`} type="button" data-testid="assistant-output" data-kind={row.kind}
            onClick={() => requestVisual(`${row.slug}::${row.path}`)} title={row.path.split("/").pop()}
            className={PANEL_ROW_BUTTON}>
            <Icon aria-hidden strokeWidth={1.75} className={PANEL_ICON} />
            <span className="min-w-0 flex-1 truncate text-sm text-foreground">{row.label}</span>
          </button>
        );
      })}
      {rows.files.length === 0 && (
        <PanelEmpty testId="assistant-outputs-empty">
          {runs.isLoading || rows.loading ? t("common.loading") : fill(t("sidebar.outputs_empty"), { assistant: name })}
        </PanelEmpty>
      )}
      {rows.files.length > OUTPUTS_SHOWN && (
        <ShowMore testId="assistant-outputs-more" open={open} onToggle={() => setOpen((value) => !value)} />
      )}
    </PanelSection>
  );
}
