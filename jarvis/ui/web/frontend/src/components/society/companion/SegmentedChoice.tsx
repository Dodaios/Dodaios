/**
 * One of a few choices as a single switch across the full width: the look
 * editor's rows (look, eyes, accessory slot) all read and click alike.
 */
export function SegmentedChoice<T extends string>({ options, value, onChange, label, role = "group", marked }: {
  options: readonly { id: T; label: string }[]; value: T; onChange: (next: T) => void;
  /** What the row chooses, for assistive technology. */
  label: string;
  /** "tablist" when the choice swaps the panel below it. */
  role?: "group" | "tablist";
  /** Choices that carry a small dot (a slot that already wears something). */
  marked?: ReadonlySet<T>;
}) {
  return <div className="flex gap-1 rounded-lg border border-border p-1" role={role} aria-label={label}>
    {options.map(option => <button key={option.id} type="button" onClick={() => onChange(option.id)}
      {...(role === "tablist" ? { role: "tab", "aria-selected": value === option.id } : { "aria-pressed": value === option.id })}
      className={`min-w-0 flex-1 truncate rounded-md px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${value === option.id ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"}`}>
      {option.label}
      {marked?.has(option.id) && <span aria-hidden className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-current align-middle" />}
    </button>)}
  </div>;
}
