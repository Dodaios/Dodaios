/**
 * The right-hand sheet a case file opens in: "Built for you" shows a build in
 * it, the Self-improvement page a learned change. Escape or a click beside it
 * closes it; focus moves into it when it opens.
 */
import { useEffect, useRef, type ReactNode } from "react";

export function DetailSheet({
  onClose,
  children,
  testId = "build-sheet",
}: {
  onClose: () => void;
  children: ReactNode;
  testId?: string;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[100] flex justify-end" data-testid={testId}>
      <div role="presentation" className="absolute inset-0 bg-background/50" onPointerDown={onClose} />
      <div
        ref={panel}
        tabIndex={-1}
        className="relative flex h-full w-full max-w-[520px] flex-col p-3 outline-none motion-safe:animate-in motion-safe:slide-in-from-right-4 [&>article]:h-full [&>article]:shadow-float"
      >
        {children}
      </div>
    </div>
  );
}
