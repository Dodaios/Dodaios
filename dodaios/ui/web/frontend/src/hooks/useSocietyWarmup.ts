import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useEventStore } from "@/store/events";

/**
 * Keeps the agent roster and the teams loaded before the Agents section asks.
 *
 * Mounted once at the shell. The lists are read at app start and again on
 * every switch to the section: the store reports the switch before React
 * renders the section, so the requests leave ahead of everything the section
 * itself starts (see `warmSocietyLists`). A detached window of another section
 * never shows them and stays quiet.
 */
export function useSocietyWarmup(): void {
  const client = useQueryClient();
  useEffect(() => {
    const failed = (error: unknown) => console.debug("Agent lists not warmed", error);
    // The society data module stays out of the entry bundle. Once loaded it is called directly, with no
    // promise in between: the requests then leave inside the store update, before React mounts the section.
    let lists: ((queryClient: typeof client) => Promise<void>) | null = null;
    const warm = () => {
      if (lists) {
        void lists(client).catch(failed);
        return;
      }
      void import("@/components/society/data")
        .then((module) => {
          lists = module.warmSocietyLists;
          return lists(client);
        })
        .catch(failed);
    };
    const { solo, activeSection } = useEventStore.getState();
    if (!solo || activeSection === "agents") warm();
    return useEventStore.subscribe((state, previous) => {
      if (state.activeSection === "agents" && previous.activeSection !== "agents") warm();
    });
  }, [client]);
}
