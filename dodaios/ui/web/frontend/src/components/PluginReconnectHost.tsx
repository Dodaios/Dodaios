import { lazy, Suspense, useEffect, useState } from "react";
import { usePluginAttention } from "@/hooks/usePluginAttention";

/**
 * The reconnect notices, loaded only once a connection has ended: the cards
 * draw service logos and run sign-ins, which the startup bundle must not carry
 * for the usual case of nothing to report.
 */
const Notices = lazy(() =>
  import("./PluginReconnectNotices").then((m) => ({ default: m.PluginReconnectNotices })),
);

export function PluginReconnectHost() {
  const attention = usePluginAttention();
  const needed = attention.items.some((item) => item.status === "needs_reauth");
  // Stays mounted afterwards: a card that just reconnected says so before it leaves.
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    if (needed) setMounted(true);
  }, [needed]);

  if (!mounted) return null;
  return (
    <Suspense fallback={null}>
      <Notices />
    </Suspense>
  );
}
