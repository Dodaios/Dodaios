import { useEffect, useState } from "react";
import { AlertCircle, Check, Cpu, Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { localInstallStatus, type ManagedServerRuntime, startGpuLibrariesInstall, gpuLibrariesInstallStatus, startLocalInstall, type LocalInstallProgress, type ProviderDescriptor } from "@/hooks/useProviders";
import { cn } from "@/lib/utils";
import { useT } from "@/i18n";

/**
 * The on-device half of a local provider's card: is the engine here, are the
 * weights here, and — when they are not — the one button that fixes it.
 *
 * This panel is the reason the local Whisper card could come back. Its
 * predecessor rendered as ready on installs where nothing was installed, so the
 * rule here is that NOTHING is inferred client-side: `ready` and `detail` come
 * from the server's on-disk probe and are rendered verbatim. While an install
 * runs we poll, because a 3 GB download finishes minutes after the click and a
 * card frozen on "Installing…" would be its own kind of lie.
 */
export function LocalRuntimePanel({
  descriptor,
  onChanged,
}: {
  descriptor: ProviderDescriptor;
  onChanged: () => void;
}) {
  const t = useT();
  const status = descriptor.local_runtime;
  const [progress, setProgress] = useState<LocalInstallProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = progress?.state === "running";
  // The GPU-library install is its own run: it serves every on-device
  // recognizer at once and is offered only when the card's accelerator truth
  // names the missing libraries as the reason for a CPU fallback.
  const [gpuProgress, setGpuProgress] = useState<LocalInstallProgress | null>(null);
  const [gpuError, setGpuError] = useState<string | null>(null);
  const gpuRunning = gpuProgress?.state === "running";

  useEffect(() => {
    if (!gpuRunning) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const next = await gpuLibrariesInstallStatus();
        if (cancelled) return;
        setGpuProgress(next);
        if (next.state === "done" || next.state === "error") {
          window.clearInterval(timer);
          onChanged();
        }
      } catch (err) {
        if (cancelled) return;
        window.clearInterval(timer);
        setGpuError(err instanceof Error ? err.message : String(err));
        setGpuProgress(null);
      }
    }, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [gpuRunning, onChanged]);

  // Poll only while an install is actually in flight, and stop on the terminal
  // state. A finished run refreshes the provider list so the card's own
  // readiness (and the "Set active" control that depends on it) update too.
  useEffect(() => {
    if (!running) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const next = await localInstallStatus(descriptor.id);
        if (cancelled) return;
        setProgress(next);
        if (next.state === "done" || next.state === "error") {
          window.clearInterval(timer);
          onChanged();
        }
      } catch (err) {
        if (cancelled) return;
        window.clearInterval(timer);
        setError(err instanceof Error ? err.message : String(err));
        setProgress(null);
      }
    }, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [running, descriptor.id, onChanged]);

  if (!status) return null;

  const start = async () => {
    setError(null);
    try {
      setProgress(await startLocalInstall(descriptor.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const startGpu = async () => {
    setGpuError(null);
    try {
      setGpuProgress(await startGpuLibrariesInstall());
    } catch (err) {
      setGpuError(err instanceof Error ? err.message : String(err));
    }
  };

  const failed = progress?.state === "error";
  const gpuFailed = gpuProgress?.state === "error";
  const accelerator = status.accelerator ?? null;
  // Only a CPU fallback the person did not ask for is worth a line and a
  // button; "CPU, as configured" and a verified GPU are the quiet cases.
  const showAccelerator =
    accelerator !== null && accelerator.reason !== "not_requested" && accelerator.reason !== "";
  return (
    <div className="space-y-2 border-t border-border pt-3">
      <div className="flex items-start gap-2 text-xs">
        {status.ready ? (
          <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-foreground" />
        )}
        <span className="text-muted-foreground">
          {progress?.message ?? status.detail}
        </span>
      </div>
      {showAccelerator && accelerator && (
        <div
          className="flex items-start gap-2 text-xs"
          data-testid="local-accelerator"
        >
          <Cpu
            className={cn(
              "mt-0.5 h-3.5 w-3.5 shrink-0",
              accelerator.effective === "cpu" && accelerator.installable
                ? "text-foreground"
                : "text-muted-foreground",
            )}
          />
          <span className="text-muted-foreground">
            {gpuProgress?.message ?? accelerator.detail}
          </span>
        </div>
      )}
      {showAccelerator && accelerator?.installable && (
        <Button
          size="sm"
          variant="secondary"
          onClick={startGpu}
          disabled={gpuRunning}
          className="gap-2"
          data-testid="install-gpu-libraries"
        >
          {gpuRunning ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Download className="h-3.5 w-3.5" />
          )}
          {gpuRunning
            ? t("apikeys_view.gpu_libraries_installing")
            : gpuFailed
              ? t("apikeys_view.local_install_retry")
              : t("apikeys_view.gpu_libraries_install_cta")}
        </Button>
      )}
      {gpuRunning && (
        <p className="text-xs text-muted-foreground">
          {t("apikeys_view.gpu_libraries_install_hint")}
        </p>
      )}
      {gpuError && <p className="text-xs text-destructive">{gpuError}</p>}
      {!status.ready && (
        <Button
          size="sm"
          variant="secondary"
          onClick={start}
          disabled={running}
          className="gap-2"
        >
          {running ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Download className="h-3.5 w-3.5" />
          )}
          {running
            ? t("apikeys_view.local_installing")
            : failed
              ? t("apikeys_view.local_install_retry")
              : t("apikeys_view.local_install_cta")}
        </Button>
      )}
      {running && (
        <p className="text-xs text-muted-foreground">
          {t("apikeys_view.local_install_hint")}
        </p>
      )}
      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}
    </div>
  );
}

export type ManagedRuntimeBadge = {
  key: string;
  tone: "ok" | "warn" | "muted";
};

/**
 * The live server verdict, in one place because it is a RULE, not decoration.
 *
 * Honest about ownership: reachable-and-not-ours is a port conflict (or an
 * orphan of a removed install), never claimed as ours. Honest about
 * readiness: "running" means the server could take a call, not merely that a
 * socket answers. The old port-only badge stayed green through the whole
 * model load, so the card said "Server running" while every call died on a
 * cold pool (live 2026-08-09 11:50:47).
 *
 * A pool with every slot in use is still healthy — that is a busy server, not
 * a broken one. Backends older than this rule omit `ready`/`available`;
 * treating only an explicit `false` as bad keeps the badge exactly as honest
 * as its input instead of inventing a warning from a missing field.
 */
export function managedRuntimeBadge(
  runtime: ManagedServerRuntime | null,
  installReady: boolean,
): ManagedRuntimeBadge | null {
  if (runtime === null) return null;
  const ours = runtime.owned || installReady;
  const serving = (runtime.pool?.in_use ?? 0) > 0;
  const canTakeACall =
    runtime.ready !== false && (runtime.available !== false || serving);
  if (runtime.reachable && ours) {
    if (canTakeACall) {
      return { key: "apikeys_view.managed_server_running", tone: "ok" };
    }
    return runtime.ready === false
      ? { key: "apikeys_view.managed_server_starting", tone: "warn" }
      : { key: "apikeys_view.managed_server_no_capacity", tone: "warn" };
  }
  if (runtime.reachable) {
    return { key: "apikeys_view.managed_server_port_conflict", tone: "warn" };
  }
  if (runtime.owned) {
    return { key: "apikeys_view.managed_server_starting", tone: "warn" };
  }
  // Two consecutive readiness timeouts mean whole five-minute boot budgets
  // burned with nothing to show — "Server stopped" would hide a crash loop
  // behind the same muted badge as a deliberate stop (live 2026-08-09, four
  // reaped generations in forty minutes read as an endless quiet "starting").
  if ((runtime.boot?.failed_streak ?? 0) >= 2) {
    return { key: "apikeys_view.managed_server_crash_loop", tone: "warn" };
  }
  return { key: "apikeys_view.managed_server_stopped", tone: "muted" };
}
