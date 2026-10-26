import type { ReactNode } from "react";

/** The letter tile in front of a row; filled in the agent's colour once chosen. */
export function KeyCap({ children, on = false, size }: { children: ReactNode; on?: boolean; size?: "sm" }) {
  return (
    <span className="qc-keycap" data-on={on ? "" : undefined} data-size={size} aria-hidden>
      {children}
    </span>
  );
}
