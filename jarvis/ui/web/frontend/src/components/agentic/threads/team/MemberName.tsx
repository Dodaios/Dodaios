import { cn } from "@/lib/utils";
import { nameParts } from "./teamGraph";

/**
 * A member's name whose distinguishing tail never truncates away: in a narrow
 * place "Anthropic Claude · Opus 5.5" reads "Anthropic Cl… · Opus 5.5", so two
 * members on one seat still read apart.
 */
export function MemberName({ name, className }: { name: string; className?: string }) {
  const { head, tail } = nameParts(name);
  return <span className={cn("flex min-w-0 items-baseline", className)} title={name}>
    <span className="min-w-0 truncate">{head}</span>
    {tail && <span className="ml-[0.3em] max-w-[60%] shrink-0 truncate">{tail.trim()}</span>}
  </span>;
}
