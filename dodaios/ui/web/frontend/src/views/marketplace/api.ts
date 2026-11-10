/**
 * The marketplace's requests, as hooks.
 *
 * One query holds the index; installing, removing and refreshing write the
 * server's answer back into it or mark it stale, so every part of the store
 * reads the same state.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { fill, translate } from "@/i18n";
import type { CommunityResponse, EntryContentsWire } from "@/views/PluginsCommunity";
import type { Entry, InstallResultWire } from "./model";

export const INDEX_KEY = ["marketplace-community"] as const;

/** The reason a request failed, in the server's words when it gave any. */
async function failure(res: Response, fallbackKey: string): Promise<Error> {
  const detail = await res
    .json()
    .then((body: { detail?: unknown }) => (typeof body.detail === "string" ? body.detail : undefined))
    .catch(() => undefined);
  return new Error(detail ?? fill(translate(fallbackKey), { status: res.status }));
}

async function fetchIndex(): Promise<CommunityResponse> {
  const res = await fetch("/api/marketplace/community", { cache: "no-store" });
  if (!res.ok) throw await failure(res, "marketplace.request_failed");
  return res.json();
}

export function useStoreIndex() {
  return useQuery({
    queryKey: INDEX_KEY,
    queryFn: fetchIndex,
    // The store stays live while it is open: a publish that just merged shows
    // up on its own. Cheap on purpose: the server answers from memory inside
    // its cache window and revalidates with a conditional request after it.
    // "revalidating" means the server answered from an older index and is
    // fetching the current one right now, so ask again in a moment.
    refetchInterval: (query) => (query.state.data?.status === "revalidating" ? 2_000 : 60_000),
    refetchIntervalInBackground: false,
  });
}

/** Everything that lists installed things must notice an arrival or a removal. */
function invalidateInstalled(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: INDEX_KEY });
  queryClient.invalidateQueries({ queryKey: ["marketplace-plugins"] });
  queryClient.invalidateQueries({ queryKey: ["skills"] });
  queryClient.invalidateQueries({ queryKey: ["society", "roster"] });
}

export function useRefreshIndex() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<CommunityResponse> => {
      const res = await fetch("/api/marketplace/community/refresh", { method: "POST" });
      if (!res.ok) throw await failure(res, "marketplace.refresh_failed");
      return res.json();
    },
    onSuccess: (fresh) => queryClient.setQueryData(INDEX_KEY, fresh),
  });
}

export function useInstallEntry(onInstalled: (result: InstallResultWire, entry: Entry) => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (entry: Entry): Promise<InstallResultWire> => {
      const res = await fetch(
        `/api/marketplace/community/install/${encodeURIComponent(entry.name)}`,
        { method: "POST" },
      );
      // A failure names its cause — a bare "that did not work" is a bug.
      if (!res.ok) throw await failure(res, "marketplace.install_failed");
      return res.json();
    },
    onSuccess: (result, entry) => {
      onInstalled(result, entry);
      invalidateInstalled(queryClient);
    },
  });
}

export function useRemoveEntry(onRemoved: (entry: Entry) => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (entry: Entry): Promise<void> => {
      const res = await fetch(
        `/api/marketplace/community/install/${encodeURIComponent(entry.name)}`,
        { method: "DELETE" },
      );
      if (!res.ok) throw await failure(res, "marketplace.remove_failed");
    },
    onSuccess: (_result, entry) => {
      onRemoved(entry);
      invalidateInstalled(queryClient);
    },
  });
}

/** The published files of one entry, fetched only when its page opens. */
export function useEntryContents(name: string | null) {
  return useQuery({
    queryKey: ["marketplace-community-contents", name],
    enabled: name !== null,
    staleTime: 5 * 60 * 1000,
    queryFn: async (): Promise<EntryContentsWire> => {
      const res = await fetch(
        `/api/marketplace/community/${encodeURIComponent(name ?? "")}/contents`,
        { cache: "no-store" },
      );
      if (!res.ok) throw await failure(res, "marketplace.contents_failed");
      return res.json();
    },
  });
}
