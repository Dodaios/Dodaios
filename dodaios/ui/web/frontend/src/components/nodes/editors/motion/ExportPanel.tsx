/**
 * The export: the clip as an MP4 file, rendered by the app frame by frame
 * from the very page the preview shows (`dodaios/nodes/clip/export.py`).
 *
 * The panel picks the size and the frame rate; the run goes on in the
 * background while the person keeps editing (what is exported is the clip as
 * it was when Export was pressed). When it is done the file can be saved from
 * here; it also stays in the node's folder.
 */
import { useEffect, useRef, useState } from "react";
import { Download, Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { fill, useT } from "@/i18n";
import { Select } from "../controls";
import { cancelExport, exportFileUrl, exportStatus, startExport, type ExportPreset, type ExportStatus } from "./clipApi";
import type { MotionSpec } from "./motionModel";

/** The pixel size each preset gives a format (the short side is the preset). */
export function exportSize(format: MotionSpec["format"], preset: ExportPreset): string {
  const short = preset === "720p" ? 720 : preset === "1080p" ? 1080 : 2160;
  const ratio = { wide: [16, 9], tall: [9, 16], square: [1, 1], portrait: [4, 5] }[format];
  const [w, h] = ratio;
  const even = (n: number) => Math.round(n / 2) * 2;
  return w >= h ? `${even((short * w) / h)} × ${short}` : `${short} × ${even((short * h) / w)}`;
}

export interface ExportJob {
  id: string;
  status: ExportStatus;
}

export function ExportPanel({
  nodeId,
  spec,
  job,
  onJob,
}: {
  nodeId: string;
  spec: MotionSpec;
  job: ExportJob | null;
  onJob: (job: ExportJob | null) => void;
}) {
  const t = useT();
  const k = (key: string) => t(`nodes.editor.motion.video.export.${key}`);
  const [preset, setPreset] = useState<ExportPreset>("1080p");
  const [fps, setFps] = useState("30");
  const [error, setError] = useState("");
  const live = useRef(onJob);
  live.current = onJob;

  // While a run goes on, ask for its state twice a second.
  useEffect(() => {
    if (!job || job.status.state !== "running") return;
    let alive = true;
    const timer = window.setInterval(() => {
      void exportStatus(nodeId, job.id)
        .then((status) => {
          if (alive) live.current({ id: job.id, status });
        })
        .catch(() => undefined);
    }, 500);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [nodeId, job]);

  const start = async () => {
    setError("");
    try {
      const id = await startExport(nodeId, spec, preset, Number(fps));
      onJob({ id, status: { state: "running", progress: 0 } });
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : k("failed"));
    }
  };

  const running = job?.status.state === "running";
  return (
    <div className="flex w-72 flex-col gap-3 p-1" data-testid="clip-export-panel">
      <h3 className="text-sm font-semibold">{k("title")}</h3>
      <div className="grid grid-cols-2 gap-2">
        <Select
          label={k("size")}
          showLabel
          value={preset}
          options={(["720p", "1080p", "2160p"] as const).map((p) => ({ value: p, label: `${p === "2160p" ? "4K" : p} · ${exportSize(spec.format, p)}` }))}
          onChange={(v) => setPreset(v as ExportPreset)}
          disabled={running}
          testId="clip-export-size"
        />
        <Select
          label={k("fps")}
          showLabel
          value={fps}
          options={["24", "30", "60"].map((f) => ({ value: f, label: `${f} fps` }))}
          onChange={setFps}
          disabled={running}
        />
      </div>
      <p className="text-xs text-muted-foreground">{k("hint")}</p>
      {running && job && (
        <div className="flex flex-col gap-1.5">
          <div className="h-1.5 overflow-hidden rounded bg-muted">
            <div className="h-full bg-accent transition-[width]" style={{ width: `${Math.round(job.status.progress * 100)}%` }} />
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {job.status.frames ? fill(k("frames"), { n: job.status.frame ?? 0, total: job.status.frames }) : k("starting")}
            </span>
            <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => void cancelExport(nodeId, job.id)}>
              <X className="h-3 w-3" aria-hidden />
              {k("cancel")}
            </button>
          </div>
        </div>
      )}
      {job?.status.state === "done" && (
        <div className="flex flex-col gap-1.5 rounded-md border border-border p-2 text-xs">
          <span className="font-medium">{k("done")}</span>
          {job.status.file && (
            <span className="break-all text-muted-foreground" title={job.status.file}>
              {job.status.file}
            </span>
          )}
          <a href={exportFileUrl(nodeId, job.id)} download className="inline-flex items-center gap-1 text-accent hover:underline" data-testid="clip-export-download">
            <Download className="h-3.5 w-3.5" aria-hidden />
            {k("download")}
          </a>
        </div>
      )}
      {(job?.status.state === "failed" || error) && <p className="text-xs text-destructive">{error || job?.status.error || k("failed")}</p>}
      <Button size="sm" onClick={() => void start()} disabled={running} className="gap-1.5" data-testid="clip-export-start">
        {running && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
        {running ? k("running") : k("start")}
      </Button>
    </div>
  );
}
