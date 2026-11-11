import type { ReactNode, SVGProps } from "react";

/**
 * The four start rows atop the thread sidebar draw their own marks instead of
 * stock glyphs: one family on a 20px grid, a 1.5 stroke with round ends, so
 * the rows read as one designed set. A new thread is a speech bubble with a
 * plus, a team thread two bubbles talking, search a magnifier, Dodaios Live
 * a voice's waveform.
 */
type IconProps = Omit<SVGProps<SVGSVGElement>, "children">;

function Frame({ children, ...props }: IconProps & { children: ReactNode }) {
  return <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.5}
    strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false" {...props}>{children}</svg>;
}

export function NewThreadIcon(props: IconProps) {
  return <Frame {...props}>
    <path d="M6 3.75h8A3 3 0 0 1 17 6.75v4.5a3 3 0 0 1-3 3H9.25L6 16.75v-2.5a3 3 0 0 1-3-3v-4.5a3 3 0 0 1 3-3z" />
    <path d="M10 6.9v4.7M7.65 9.25h4.7" />
  </Frame>;
}

export function SearchThreadsIcon(props: IconProps) {
  return <Frame {...props}>
    <circle cx="8.75" cy="8.75" r="5" />
    <path d="M12.5 12.5 16.5 16.5" />
  </Frame>;
}

export function TeamThreadIcon(props: IconProps) {
  return <Frame {...props}>
    <path d="M5 7.25h5a2.5 2.5 0 0 1 2.5 2.5v2.25a2.5 2.5 0 0 1-2.5 2.5H7.5L5 16.5v-2A2.5 2.5 0 0 1 2.5 12V9.75A2.5 2.5 0 0 1 5 7.25z" />
    <path d="M7.75 5.25v-.25A2.25 2.25 0 0 1 10 2.75h5.25A2.25 2.25 0 0 1 17.5 5v2.75a2.25 2.25 0 0 1-2.25 2.25V12l-1.75-1.6" />
  </Frame>;
}

export function LiveVoiceIcon(props: IconProps) {
  return <Frame {...props}>
    <path d="M3.5 8.75v2.5M6.75 6v8M10 3.5v13M13.25 7v6M16.5 8.5v3" />
  </Frame>;
}
