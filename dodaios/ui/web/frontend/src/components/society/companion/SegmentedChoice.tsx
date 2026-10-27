import "../calmSheet.css";

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
  return <div className="cs-tabs" data-fill="true" role={role} aria-label={label}>
    {options.map(option => <button key={option.id} type="button" onClick={() => onChange(option.id)}
      {...(role === "tablist" ? { role: "tab", "aria-selected": value === option.id } : { "aria-pressed": value === option.id })}
      className="cs-tab">
      {option.label}
      {marked?.has(option.id) && <span aria-hidden className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-current align-middle" />}
    </button>)}
  </div>;
}
