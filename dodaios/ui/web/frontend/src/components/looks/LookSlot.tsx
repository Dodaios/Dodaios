/**
 * Where the voice orb sits: the active look (`docs/looks.md`) if one is
 * picked and working, otherwise the orb itself (`children`).
 */
import type { ReactNode } from "react";
import { LookFrame } from "@/components/looks/LookFrame";
import { useActiveLook, useLooksStore } from "@/store/looks";
import type { VoiceState } from "@/store/events";

export function LookSlot({
  state,
  className,
  children,
}: {
  state: VoiceState;
  /** Size and position of the frame; match the orb it replaces. */
  className?: string;
  children: ReactNode;
}) {
  const look = useActiveLook();
  const markFailed = useLooksStore((s) => s.markFailed);
  if (!look) return <>{children}</>;
  return (
    <LookFrame
      key={look.id}
      look={look}
      state={state}
      onFail={() => markFailed(look.id)}
      className={className}
    />
  );
}
