import { useQuery } from "@tanstack/react-query";

interface ProfileUser {
  user?: { name?: string | null; display_name?: string | null } | null;
}

/**
 * The person's own name, as the Profile section knows it or the memory has
 * learned it — for the front page greeting and the sidebar footer. Same query key as the Profile view, so the two share one
 * fetch and one cache. Null while loading, on a headless host, or when the
 * profile simply has no name yet; the greeting then drops the name rather
 * than inventing one.
 */
export function useUserName(): string | null {
  const { data } = useQuery({
    queryKey: ["profile"],
    queryFn: async (): Promise<ProfileUser> => {
      const res = await fetch("/api/profile");
      if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status });
      return (await res.json()) as ProfileUser;
    },
    staleTime: 60_000,
    // The window often loads before the backend has finished booting. With no
    // retry that first failed fetch stuck, and the sidebar footer said
    // "Profile" instead of the person's name until the next restart. Keep
    // asking for about a minute; a host without the route (404) stays quiet.
    retry: (failures, error) =>
      failures < 6 && (error as { status?: number }).status !== 404,
    retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 15_000),
  });
  // The name set in the Profile, else the one the memory has learned
  // (`display_name`, from the user's wiki entity page — profile_routes.py).
  const name = data?.user?.name || data?.user?.display_name;
  return typeof name === "string" && name.trim() ? name.trim() : null;
}
