import type { SessionGitHubStatus } from "./useSessionGitHub";

/** GitHub's own colour for each pull request state (Primer, light and dark); "" for a plain branch. */
export const PULL_REQUEST_TONE: Record<SessionGitHubStatus["state"], string> = {
  branch: "",
  open: "text-[#1a7f37] dark:text-[#3fb950]",
  draft: "text-[#59636e] dark:text-[#9198a1]",
  queued: "text-[#9a6700] dark:text-[#d29922]",
  merged: "text-[#8250df] dark:text-[#ab7df8]",
  closed: "text-[#cf222e] dark:text-[#f85149]",
};
