/**
 * The fixed lines a coding policy adds to the first brief, as the agent reads
 * them. They are written in the code (dodaios/rsi/mining.py) and stay English,
 * because English is what the agents are briefed in.
 */
export function PolicyLines({ lines, testId = "si-policy-lines" }: { lines: string[]; testId?: string }) {
  return (
    <span className="mb-1 block space-y-0.5" data-testid={testId}>
      {lines.map((line) => (
        <span key={line} lang="en" className="block whitespace-normal text-[15px] leading-snug text-foreground">
          “{line}”
        </span>
      ))}
    </span>
  );
}
