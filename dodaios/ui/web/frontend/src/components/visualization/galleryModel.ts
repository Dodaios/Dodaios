/**
 * What a run is called and when it happened: the pure rules the stage of the
 * Nodes section shares with nothing but tests.
 *
 * No React and no fetching. (The library's own rules, which cards a tab holds
 * and in what order, live in `components/nodes/libraryModel.ts`.)
 */
import type { OutputSummary } from "@/hooks/useOutputs";
import { requestHeadline } from "@/lib/runRequest";

/**
 * A `create_artifact` mission's prompt leads with `Artifact: <title>` and the
 * user's request right after (dodaios/artifacts/brief.py). The run list
 * already strips the quality lead, so the run's `utterance` starts with that
 * line — which is how a running build is recognised and labelled here.
 */
export function parseArtifactUtterance(
  utterance: string | undefined,
): { title: string; request: string } | null {
  const text = (utterance ?? "").trim();
  const match = /^Artifact:[ \t]*([^\n]+)/.exec(text);
  if (!match) return null;
  const rest = text.slice(match[0].length).trim();
  const request = rest.split(/\n\s*\n/)[0]?.trim() ?? "";
  return { title: match[1].trim(), request };
}

/** What a run is called when it has no page title of its own. */
export function runTitle(run: OutputSummary): string {
  return (
    parseArtifactUtterance(run.utterance)?.title || requestHeadline(run.utterance ?? "") || run.slug
  );
}

/** The run's moment for ordering — when it ended, else when it began. */
export function runWhen(run: OutputSummary): number {
  return run.completed_at ?? run.started_at ?? 0;
}
