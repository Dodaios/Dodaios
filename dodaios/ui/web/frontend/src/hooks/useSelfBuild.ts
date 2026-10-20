/**
 * React Query hooks for "Built for you" (the self-building ledger).
 *
 * Nothing here polls fast: the backend publishes `SelfBuildChanged` on every
 * committed change and the WebSocket invalidates `selfBuildKeys.all`
 * (hooks/useWebSocket.ts), so the view repaints when a build moves. The slow
 * interval only covers a dropped socket. Every action writes its answer into
 * the cached list, so a click paints before the refetch lands.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  selfBuildApi,
  societyKillSwitchApi,
  type Build,
  type BuildList,
  type ProvenanceItem,
  type SelfBuildSettings,
  type SelfBuildSettingsPayload,
} from "@/lib/selfBuildApi";

export const selfBuildKeys = {
  all: ["self-build"] as const,
  list: () => ["self-build", "list"] as const,
  detail: (id: string) => ["self-build", "detail", id] as const,
  digest: (hours: number) => ["self-build", "digest", hours] as const,
  settings: () => ["self-build", "settings"] as const,
  provenance: () => ["self-build", "provenance"] as const,
  societyKill: () => ["society", "kill-switch"] as const,
};

const SAFETY_POLL_MS = 5 * 60_000;

export function useSelfBuildList() {
  return useQuery({
    queryKey: selfBuildKeys.list(),
    queryFn: ({ signal }) => selfBuildApi.list(signal),
    refetchInterval: SAFETY_POLL_MS,
    retry: false,
  });
}

/** How many proposals wait for the person — the quiet number on the nav row. */
export function useSelfBuildWaiting(): number | undefined {
  const { data } = useSelfBuildList();
  if (!Array.isArray(data?.builds)) return undefined;
  return data.builds.filter((b) => b.state === "proposed").length;
}

export function useSelfBuildDetail(id: string | null) {
  return useQuery({
    queryKey: selfBuildKeys.detail(id ?? ""),
    queryFn: ({ signal }) => selfBuildApi.detail(id ?? "", signal),
    enabled: Boolean(id),
    retry: false,
  });
}

export function useSelfBuildDigest(hours = 24) {
  return useQuery({
    queryKey: selfBuildKeys.digest(hours),
    queryFn: ({ signal }) => selfBuildApi.digest(hours, signal),
    refetchInterval: SAFETY_POLL_MS,
    retry: false,
  });
}

function patchList(list: BuildList | undefined, build: Build): BuildList | undefined {
  if (!list) return list;
  const builds = list.builds.some((b) => b.id === build.id)
    ? list.builds.map((b) => (b.id === build.id ? build : b))
    : [build, ...list.builds];
  return { ...list, builds };
}

export type BuildAction = "accept" | "keep" | "undo";

export function useBuildAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: BuildAction }) =>
      action === "accept"
        ? selfBuildApi.accept(id)
        : action === "keep"
          ? selfBuildApi.keep(id)
          : selfBuildApi.undo(id),
    onSuccess: ({ build }) => {
      client.setQueryData<BuildList>(selfBuildKeys.list(), (old) => patchList(old, build));
      void client.invalidateQueries({ queryKey: selfBuildKeys.all });
    },
  });
}

export function useSelfBuildPause() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (paused: boolean) => selfBuildApi.pause(paused),
    onSuccess: (status) => {
      client.setQueryData<BuildList>(selfBuildKeys.list(), (old) =>
        old ? { ...old, status } : old,
      );
      void client.invalidateQueries({ queryKey: selfBuildKeys.list() });
    },
  });
}

export function useSelfBuildSettings() {
  return useQuery({
    queryKey: selfBuildKeys.settings(),
    queryFn: ({ signal }) => selfBuildApi.settings(signal),
    retry: false,
  });
}

export function useSaveSelfBuildSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<SelfBuildSettings>) => selfBuildApi.saveSettings(patch),
    onSuccess: (payload) => {
      client.setQueryData<SelfBuildSettingsPayload>(selfBuildKeys.settings(), payload);
      // The status block (autonomy per kind) is derived from the same section.
      void client.invalidateQueries({ queryKey: selfBuildKeys.list() });
    },
  });
}

/** Every artefact a build created, keyed `"<type>:<id>"`; one shared query for every badge. */
export function useProvenance() {
  return useQuery({
    queryKey: selfBuildKeys.provenance(),
    queryFn: async ({ signal }) => (await selfBuildApi.provenance(undefined, signal)).items,
    staleTime: 60_000,
    retry: false,
  });
}

export function useProvenanceFor(type: string, id: string | null | undefined): ProvenanceItem | null {
  const { data } = useProvenance();
  if (!data || !id) return null;
  return data[`${type}:${id}`] ?? null;
}

export function useSocietyKillSwitch() {
  return useQuery({
    queryKey: selfBuildKeys.societyKill(),
    queryFn: ({ signal }) => societyKillSwitchApi.status(signal),
    refetchInterval: SAFETY_POLL_MS,
    retry: false,
  });
}

export function useSetSocietyKillSwitch() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (engaged: boolean) => societyKillSwitchApi.set(engaged),
    onSuccess: (_void, engaged) => {
      client.setQueryData(selfBuildKeys.societyKill(), engaged);
      // Engaging it pauses the loop too (dodaios/society/runtime.py).
      void client.invalidateQueries({ queryKey: selfBuildKeys.list() });
      void client.invalidateQueries({ queryKey: ["society"] });
    },
  });
}
