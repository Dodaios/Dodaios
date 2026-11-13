import { Children, useState, type MouseEvent, type ReactNode } from "react";
import { ArrowUpRight, Globe } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { HoverCard } from "@/components/ui/hover-card";
import { displayAddress, linkIconUrl, type WebLinkInfo } from "./webLinks";

/** Sites whose logo did not load in this window: drawn with the globe from then on. */
const failedIcons = new Set<string>();

export function resetLinkIconsForTests(): void {
  failedIcons.clear();
}

/** The website's own logo, or a globe while it has none. */
export function SiteIcon({ host, className }: { host: string; className?: string }) {
  const [failed, setFailed] = useState(() => failedIcons.has(host));
  if (failed) return <Globe aria-hidden data-testid="web-link-globe" className={cn("text-muted-foreground", className)} />;
  return <img src={linkIconUrl(host)} alt="" aria-hidden draggable={false} data-testid="web-link-icon"
    onError={() => { failedIcons.add(host); setFailed(true); }}
    className={cn("rounded-[3px] object-contain", className)} />;
}

/**
 * A web link in a chat answer: the website's logo and a short name, the way a
 * person would write it ("Reddit thread", "Dodaios repo"), not the address.
 * Resting the pointer on it shows a card with the website and the full
 * address; a click on either opens the page in the browser.
 */
export function WebLink({ info, children, onOpen }: {
  info: WebLinkInfo;
  /** The words the answer wrote; used when {@link WebLinkInfo.label} is null. */
  children: ReactNode;
  onOpen: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  const t = useT();
  const kind = info.kind;
  const label = kind?.type === "x_post" ? fill(t("chat_links.x_post"), { user: kind.user })
    : kind?.type === "video" ? t("chat_links.video")
    : kind?.type === "discussion" ? t("chat_links.discussion")
    : info.label;
  const openHint = fill(t("chat_links.open"), { site: info.site });
  const card = (
    <a href={info.url} onClick={onOpen} data-testid="web-link-card" aria-label={openHint}
      className="group/card flex min-w-0 flex-col gap-1 rounded-md py-0.5 no-underline outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span className="text-[13px] font-semibold text-popover-foreground">{info.site}</span>
      <span className="flex min-w-0 items-center gap-2 text-[12.5px] text-muted-foreground">
        <SiteIcon host={info.host} className="h-4 w-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate" data-testid="web-link-address">{displayAddress(info.url)}</span>
        <ArrowUpRight aria-hidden className="h-4 w-4 shrink-0 transition-colors group-hover/card:text-popover-foreground" />
      </span>
    </a>
  );
  const words = label ?? (Children.toArray(children).every(child => typeof child === "string") ? Children.toArray(children).join("") : null);
  // The logo stays on the line of the first word: it never ends a line alone.
  const space = words ? words.search(/\s/) : -1;
  const first = words === null ? null : space === -1 ? words : words.slice(0, space);
  const rest = words === null || space === -1 ? "" : words.slice(space);
  const underline = "underline decoration-foreground/40 decoration-1 underline-offset-4 group-hover/link:decoration-foreground";
  const icon = <SiteIcon host={info.host} className="mr-[0.3em] inline-block h-[1em] w-[1em] -translate-y-[0.1em] align-middle" />;
  return (
    <HoverCard content={card} label={info.site} side="above" className="inline" cardClassName="w-[300px] px-3 py-2">
      <a href={info.url} onClick={onOpen} data-testid="web-link" data-host={info.host}
        // `not-prose`: the reading style gives every picture a block margin, which tore the line apart.
        className="not-prose group/link text-foreground no-underline">
        {first === null
          ? <>{icon}<span className={underline}>{children}</span></>
          : <><span className="whitespace-nowrap">{icon}<span className={underline}>{first}</span></span>{rest && <span className={underline}>{rest}</span>}</>}
      </a>
    </HoverCard>
  );
}
