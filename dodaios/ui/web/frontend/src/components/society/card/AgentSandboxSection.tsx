import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { BrandedSelect } from "@/components/ui/select";
import { useT } from "@/i18n";
import type { SocietyAgent } from "../data";

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(typeof body.detail === "string" ? body.detail : body.detail?.detail ?? "Sandbox request failed");
  }
  return body as T;
}

export function SandboxChoice({ value, onChange, disabled = false, layout = "field" }: {
  value: "local" | "sandbox"; onChange: (value: "local" | "sandbox") => void; disabled?: boolean;
  /** "row": a label on the left and a quiet picker on the right, as a line of a pane card. */
  layout?: "field" | "row";
}) {
  const t = useT();
  if (layout === "row") {
    return <div className="ap-line">
      <span className="ap-line-label">{t("society.sandbox.environment")}</span>
      <span className="ml-auto shrink-0">
        <BrandedSelect ariaLabel={t("society.sandbox.environment")} value={value} disabled={disabled} className="ap-pick"
          onValueChange={(next) => onChange(next as "local" | "sandbox")}
          options={[
            { value: "local", label: t("society.sandbox.local") },
            { value: "sandbox", label: t("society.sandbox.code") },
          ]} />
      </span>
    </div>;
  }
  return <div className="flex flex-col gap-2">
    <span className="text-[14px] font-medium">{t("society.sandbox.environment")}</span>
    <BrandedSelect ariaLabel={t("society.sandbox.environment")} value={value} disabled={disabled}
      onValueChange={(next) => onChange(next as "local" | "sandbox")}
      options={[
        { value: "local", label: t("society.sandbox.local") },
        { value: "sandbox", label: t("society.sandbox.code") },
      ]} />
    {value === "sandbox" ? <span className="text-[13px] leading-snug text-muted-foreground">{t("society.sandbox.scope")}</span> : null}
  </div>;
}

/**
 * `choice` is the environment picker alone (the agent pane's placement
 * section), `files` the sandbox file browser alone (its Files page), `all`
 * both, as the create dialog and older surfaces use it.
 */
export function AgentSandboxSection({ agent, show = "all", layout = "field" }: { agent: SocietyAgent; show?: "all" | "choice" | "files"; layout?: "field" | "row" }) {
  const t = useT();
  const client = useQueryClient();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [path, setPath] = useState(".");
  // Leaving the sandbox gives the agent this computer's files, shell and
  // network back: that widening asks once before it is saved.
  const [confirmLocal, setConfirmLocal] = useState(false);
  const enabled = agent.executionEnvironment === "sandbox";
  const base = `/api/society/agents/${encodeURIComponent(agent.agentId)}/sandbox`;
  const ready = useQuery({
    queryKey: ["society", "sandbox", "status"], enabled: enabled && show !== "choice", retry: false,
    queryFn: () => json<{ available: boolean; needs_image: boolean; message: string }>("/api/society/sandbox"),
  });
  const files = useQuery({
    queryKey: ["society", "sandbox", agent.agentId, path],
    enabled: enabled && show !== "choice" && ready.data?.available === true, retry: false,
    queryFn: () => json<{ files: { name: string; directory: boolean }[] }>(`${base}/files?path=${encodeURIComponent(path)}`),
  });
  async function perform(work: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await work(); } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  }
  const place = (value: "local" | "sandbox") => void perform(async () => {
    setConfirmLocal(false);
    await json(`/api/society/agents/${encodeURIComponent(agent.agentId)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ execution_environment: value }),
    });
    await client.invalidateQueries({ queryKey: ["society", "roster"] });
  });
  return <section className={layout === "row" ? "flex flex-col" : "flex flex-col gap-3"} data-testid="agent-sandbox">
    {show !== "files" ? <SandboxChoice layout={layout} value={enabled ? "sandbox" : "local"} disabled={busy || agent.runtime !== "jarvis" && !!agent.runtime}
      onChange={(value) => {
        if (enabled && value === "local") setConfirmLocal(true);
        else place(value);
      }} /> : null}
    {confirmLocal ? <div role="alertdialog" aria-label={t("society.agent_pane.leave_sandbox")} className="m-1 flex flex-col gap-2 rounded-2xl bg-warning/10 p-3 text-[13px]" data-testid="agent-sandbox-confirm-local">
      <p className="text-foreground">{t("society.agent_pane.leave_sandbox_body")}</p>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" className="rounded-full" onClick={() => setConfirmLocal(false)}>{t("society.agent_pane.go_back")}</Button>
        <Button size="sm" className="rounded-full" onClick={() => place("local")} data-testid="agent-sandbox-confirm-local-yes">{t("society.agent_pane.allow_and_save")}</Button>
      </div>
    </div> : null}
    {enabled && show !== "choice" ? <>
      <p className="text-xs text-muted-foreground">{t("society.sandbox.storage")}</p>
      {ready.isLoading ? <p role="status">{t("society.sandbox.checking")}</p> : null}
      {ready.data?.message ? <p role="status" className="text-xs">{ready.data.message}</p> : null}
      {ready.data?.needs_image ? <Button disabled={busy} onClick={() => void perform(async () => {
        await json("/api/society/sandbox/prepare", { method: "POST" });
        await ready.refetch();
      })}>{t("society.sandbox.prepare")}</Button> : null}
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={busy} onClick={() => void perform(async () => {
          const result = await ready.refetch();
          if (result.data?.available) await files.refetch();
        })}>{t("society.sandbox.refresh")}</Button>
        {path !== "." ? <Button size="sm" variant="ghost" onClick={() => setPath(".")}>{t("society.sandbox.root")}</Button> : null}
        <span className="truncate text-xs text-muted-foreground">{path}</span>
      </div>
      {files.isLoading ? <p role="status">{t("society.sandbox.loading")}</p> : null}
      {files.data?.files.length === 0 ? <p className="text-xs text-muted-foreground">{t("society.sandbox.empty")}</p> : null}
      <ul className="space-y-1 text-sm">
        {files.data?.files.map((file) => {
          const child = path === "." ? file.name : `${path}/${file.name}`;
          return <li key={file.name} className="break-all">
            {file.directory ? <button className="text-accent underline" onClick={() => setPath(child)}>{file.name}/</button>
              : <a className="text-accent underline" href={`${base}/file?path=${encodeURIComponent(child)}`} download>{file.name}</a>}
          </li>;
        })}
      </ul>
    </> : null}
    {error || ready.error || files.error ? <p role="alert" className="text-xs text-destructive">{error || ready.error?.message || files.error?.message}</p> : null}
  </section>;
}
