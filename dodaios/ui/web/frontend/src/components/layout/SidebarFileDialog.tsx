import * as Dialog from "@radix-ui/react-dialog";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { fileOf, useSoulProfile, type SoulFileId } from "@/views/assistant/api";
import { FilePage } from "@/views/assistant/FilePage";

/**
 * One of the assistant's own files, opened from the sidebar in a dialog over
 * the conversation: its character, its standing instructions, its memory or
 * what it knows about the person. The file's own page does the reading and
 * the editing; this only gives it a place to stand.
 */
export default function SidebarFileDialog({ fileId, onClose }: { fileId: SoulFileId; onClose: () => void }) {
  const t = useT();
  const profile = useSoulProfile();
  const file = profile.data ? fileOf(profile.data, fileId) : undefined;

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-[#090909]/70 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-reduce:animate-none" />
        <Dialog.Content
          data-testid="sidebar-file-dialog"
          aria-describedby={undefined}
          className={cn(
            "fixed left-1/2 top-1/2 z-[90] flex max-h-[min(88dvh,52rem)] w-[min(760px,calc(100vw-2rem))]",
            "-translate-x-1/2 -translate-y-1/2 flex-col overflow-y-auto rounded-lg bg-popover p-6 shadow-float outline-none",
            "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 motion-reduce:animate-none",
          )}
        >
          <Dialog.Title className="sr-only">{file?.filename ?? t("assistant_view.files_title")}</Dialog.Title>
          {file && profile.data
            ? <FilePage file={file} name={profile.data.name} canForget={profile.data.learning} onBack={onClose} />
            : <p role="status" className="py-6 text-center text-sm text-muted-foreground">
              {profile.isLoading ? t("common.loading") : t("sidebar.files_empty")}
            </p>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
