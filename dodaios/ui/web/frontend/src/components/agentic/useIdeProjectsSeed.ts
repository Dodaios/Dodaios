import { useEffect } from "react";
import { fetchIdeProjects } from "@/lib/agenticIdeApi";
import { useIdeProjectsStore } from "@/store/ideProjects";

/**
 * Fill the project list once when nobody has yet.
 *
 * The Agentic IDE view publishes the list, but it mounts on the first visit
 * to the IDE. The sidebar lists the folders beside the conversation too, so
 * on a fresh start it asks for them itself. A list the IDE published in the
 * meantime wins; a failed request leaves the list empty until the IDE opens.
 */
export function useIdeProjectsSeed(): void {
  const known = useIdeProjectsStore((state) => state.projects.length > 0);
  useEffect(() => {
    if (known) return;
    let live = true;
    void fetchIdeProjects().then((listing) => {
      const store = useIdeProjectsStore.getState();
      // An answer without a list (an older backend, a proxy's error page) is no list.
      if (!live || !Array.isArray(listing?.projects) || store.projects.length > 0) return;
      store.publish(listing.projects, listing.active_workspace_id ?? null);
    }, () => undefined);
    return () => { live = false; };
  }, [known]);
}
