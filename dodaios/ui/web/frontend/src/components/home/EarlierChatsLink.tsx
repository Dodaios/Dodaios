import { useState } from "react";
import { Archive } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { AllChatsDialog } from "@/components/home/AllChatsDialog";

/**
 * The front page keeps ONE conversation, so the sidebar lists no chats.
 * Chats from before (and archived voice calls) stay one click away in the
 * archive dialog.
 */
export function EarlierChatsLink() {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="earlier-chats"
        className={cn(
          "flex h-8 w-full items-center gap-3 rounded-lg px-3 text-left transition-colors",
          "text-muted-foreground hover:bg-secondary hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        <Archive aria-hidden className="h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0 flex-1 truncate text-sm">{t("sidebar.earlier_chats")}</span>
      </button>
      <AllChatsDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
