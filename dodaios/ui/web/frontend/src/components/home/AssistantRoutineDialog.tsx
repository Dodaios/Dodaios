import * as Dialog from "@radix-ui/react-dialog";
import { useLocaleChunk, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { AgentRoutineDetail } from "@/components/society/card/AgentRoutineDetail";
import { useAgentRoutines } from "@/components/society/cardData";

/**
 * One of the assistant's routines, opened from the sidebar: its schedule, its
 * runs and the pause / run-now controls, in a dialog over the conversation.
 * The routine's own page does the work; this only gives it a place to stand.
 */
export default function AssistantRoutineDialog({ agentId, routineId, onClose }: {
  agentId: string; routineId: string; onClose: () => void;
}) {
  const t = useT();
  useLocaleChunk("society");
  const routines = useAgentRoutines(agentId);
  const routine = routines.data?.find((row) => row.id === routineId) ?? null;

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-[#090909]/70 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-reduce:animate-none" />
        <Dialog.Content
          data-testid="assistant-routine-dialog"
          aria-describedby={undefined}
          className={cn(
            "fixed left-1/2 top-1/2 z-[90] flex max-h-[min(84dvh,44rem)] w-[min(560px,calc(100vw-2rem))]",
            "-translate-x-1/2 -translate-y-1/2 flex-col overflow-y-auto rounded-lg bg-popover p-4 shadow-float outline-none",
            "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 motion-reduce:animate-none",
          )}
        >
          <Dialog.Title className="sr-only">{routine?.title ?? t("sidebar.automations")}</Dialog.Title>
          {routine
            ? <AgentRoutineDetail agentId={agentId} routine={routine} onClose={onClose} />
            : <p role="status" className="py-6 text-center text-sm text-muted-foreground">
              {routines.isLoading ? t("common.loading") : t("sidebar.automations_empty")}
            </p>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
