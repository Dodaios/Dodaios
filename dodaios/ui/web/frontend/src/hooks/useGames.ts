/**
 * React Query hooks for Settings → Game settings. Every write invalidates
 * the index and the game it touched; nothing polls (AP-33).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchGame,
  fetchGames,
  resetGameProfile,
  saveDefaultDpi,
  saveGameProfile,
  type ProfilePatch,
} from "@/lib/gamesApi";

export const gameKeys = {
  all: ["games"] as const,
  detail: (id: string) => ["games", "detail", id] as const,
};

export function useGamesIndex() {
  return useQuery({ queryKey: gameKeys.all, queryFn: fetchGames });
}

export function useGameDetail(gameId: string | null) {
  return useQuery({
    queryKey: gameKeys.detail(gameId ?? ""),
    queryFn: () => fetchGame(gameId as string),
    enabled: Boolean(gameId),
  });
}

export function useSaveGameProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ gameId, patch }: { gameId: string; patch: ProfilePatch }) =>
      saveGameProfile(gameId, patch),
    onSuccess: (_data, { gameId }) => {
      void client.invalidateQueries({ queryKey: gameKeys.detail(gameId) });
      void client.invalidateQueries({ queryKey: gameKeys.all, exact: true });
    },
  });
}

export function useResetGameProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (gameId: string) => resetGameProfile(gameId),
    onSuccess: (_data, gameId) => {
      void client.invalidateQueries({ queryKey: gameKeys.detail(gameId) });
      void client.invalidateQueries({ queryKey: gameKeys.all, exact: true });
    },
  });
}

export function useSaveDefaultDpi() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (dpi: number) => saveDefaultDpi(dpi),
    onSuccess: () => void client.invalidateQueries({ queryKey: gameKeys.all }),
  });
}
