import { cn } from "@/lib/utils";

/** One glyph of the codicon font (`git-branch`, `check`, `discard`, …), 16 px. */
export function Codicon({ name, className, spin = false }: { name: string; className?: string; spin?: boolean }) {
  return <span aria-hidden className={cn("codicon", `codicon-${name}`, spin && "codicon-modifier-spin", className)} />;
}

/** The fold arrow in front of a tree row: 16 px wide plus 6 px before the label. */
export function Twistie({ open, visible = true }: { open?: boolean; visible?: boolean }) {
  return (
    <span className="flex h-[22px] w-[22px] shrink-0 items-center pr-[6px]" aria-hidden>
      {visible && <Codicon name={open ? "chevron-down" : "chevron-right"} />}
    </span>
  );
}
