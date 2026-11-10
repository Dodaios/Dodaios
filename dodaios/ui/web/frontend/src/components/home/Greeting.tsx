import { lazy, Suspense } from "react";

import { useUserName } from "@/hooks/useUserName";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { PetMark } from "@/components/pets/PetMark";

// The chips under the greeting fetch and read the roster; they are not
// needed for the first paint, so they arrive in their own chunk.
const GreetingSuggestions = lazy(() => import("@/components/home/GreetingSuggestions"));

/**
 * "Good morning, Ruben" — the front page's opening line, on both stages.
 *
 * The name comes from the Profile (useUserName); without one the greeting
 * simply has no name, it never invents one. The time of day follows the
 * machine's clock. `muted` shrinks it once a conversation is on screen so
 * the words being said, not the greeting, carry the page.
 *
 * `suggestions` adds two or three tappable chips under the line, drawn from
 * what falls due soon and the agents at work (GreetingSuggestions); on a
 * quiet day there are none and the greeting stands alone.
 */
export function Greeting({
  subtitle,
  muted = false,
  suggestions = false,
}: {
  subtitle?: string;
  muted?: boolean;
  suggestions?: boolean;
}) {
  const t = useT();
  const name = useUserName();
  const text = fill(t(greetingKey(new Date().getHours())), {
    name_part: name ? `, ${name}` : "",
  });

  return (
    <div
      className={cn(
        "flex w-full flex-col items-center text-center transition-[opacity,transform] duration-base ease-out-soft",
        muted && "scale-[0.88] opacity-70",
      )}
      data-testid="home-greeting"
    >
      {/* The user's pet above, the line under it in regular weight — the
          a quiet opening, softer than a bold headline beside a logo.
          The pet follows the voice: it listens, thinks and talks along. */}
      <PetMark size={48} reactive className="mb-3" />
      <h1 className="text-2xl font-normal tracking-tight text-foreground [text-wrap:balance]">
        {text}
      </h1>
      {subtitle && !muted && (
        <p className="mt-2 max-w-md text-base text-muted-foreground">{subtitle}</p>
      )}
      {suggestions && !muted && (
        <Suspense fallback={null}>
          <GreetingSuggestions />
        </Suspense>
      )}
    </div>
  );
}

/** Morning until 12, afternoon until 18, evening after. */
export function greetingKey(hour: number): string {
  if (hour < 12) return "home.greeting_morning";
  if (hour < 18) return "home.greeting_afternoon";
  return "home.greeting_evening";
}
