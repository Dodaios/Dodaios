import { useState } from "react";
import { Pencil, Undo2 } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { ApprovalEdits, ApprovalPreview, PreviewField } from "./approvalInfo";

type T = (key: string) => string;

/** The edits worth sending: only fields whose text differs from the original. */
export function changedEdits(preview: ApprovalPreview, drafts: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const field of preview.fields) {
    const draft = drafts[field.key];
    if (field.editable && draft !== undefined && draft !== field.value) out[field.key] = draft;
  }
  return out;
}

/**
 * The exact action as it will run: every field, new recipients marked, a diff for
 * an overwrite, an irreversible action named as such. Plain-text fields can be
 * edited in place; the edited version is what runs (the backend checks it again).
 */
export function ApprovalPreviewView({ preview, drafts, onDraft, disabled }: {
  preview: ApprovalPreview;
  drafts?: Record<string, string>;
  /** Present on an open card only: without it the fields are read-only. */
  onDraft?: (key: string, value: string | null) => void;
  disabled?: boolean;
}) {
  const t = useT();
  const editing = Boolean(onDraft);
  return <div className="approval-preview" data-testid="approval-preview" data-class={preview.cls}>
    {preview.irreversible ? <p className="approval-preview-flag" data-testid="approval-preview-irreversible">
      {t("action_card.preview.irreversible")}
    </p> : null}
    <dl className="approval-preview-fields">
      {preview.fields.map((field) => <PreviewRow key={field.key} field={field} t={t}
        draft={drafts?.[field.key]} editable={editing && field.editable} disabled={disabled}
        onDraft={(value) => onDraft?.(field.key, value)} />)}
    </dl>
    {preview.diff ? <PreviewDiffView diff={preview.diff} t={t} /> : null}
  </div>;
}

function PreviewRow({ field, draft, editable, disabled, onDraft, t }: {
  field: PreviewField; draft: string | undefined; editable: boolean; disabled?: boolean;
  onDraft: (value: string | null) => void; t: T;
}) {
  const [open, setOpen] = useState(false);
  const label = t(`action_card.preview.field.${field.key}`);
  const edited = draft !== undefined && draft !== field.value;
  const shown = draft ?? field.value;
  const editLabel = fill(t("action_card.preview.edit_field"), { field: label });
  return <div className="approval-preview-row" data-testid={`approval-preview-${field.key}`} data-edited={edited || undefined}>
    <dt>{label}</dt>
    <dd>
      {field.kind === "people"
        ? <ul className="approval-preview-people">
          {field.items.map((item) => <li key={item.text} data-new={item.new || undefined}>
            <span>{item.text}</span>
            {item.new ? <span className="approval-preview-new" data-testid="approval-preview-new">{t("action_card.preview.new_recipient")}</span> : null}
          </li>)}
        </ul>
        : editable && open
          ? <PreviewEditor field={field} value={shown} label={label} disabled={disabled} onChange={(value) => onDraft(value)} />
          : <span className={cn("approval-preview-value", field.kind === "multiline" && "approval-preview-multiline", field.kind === "code" && "approval-preview-code")}>
            {shown || "-"}
          </span>}
      {editable ? <span className="approval-preview-tools">
        {!open ? <button type="button" className="approval-preview-icon" onClick={() => setOpen(true)} disabled={disabled}
          aria-label={editLabel} title={editLabel} data-testid={`approval-preview-edit-${field.key}`}>
          <Pencil aria-hidden />
        </button> : null}
        {edited ? <button type="button" className="approval-preview-icon" onClick={() => { onDraft(null); setOpen(false); }} disabled={disabled}
          aria-label={t("action_card.preview.reset_field")} title={t("action_card.preview.reset_field")}>
          <Undo2 aria-hidden />
        </button> : null}
      </span> : null}
      {edited ? <span className="approval-preview-edited">{t("action_card.preview.edited")}</span> : null}
    </dd>
  </div>;
}

function PreviewEditor({ field, value, label, disabled, onChange }: {
  field: PreviewField; value: string; label: string; disabled?: boolean; onChange: (value: string) => void;
}) {
  const common = {
    value, disabled, "aria-label": label, className: "approval-preview-input", "data-testid": `approval-preview-input-${field.key}`,
  };
  return field.kind === "multiline"
    ? <textarea {...common} rows={Math.min(10, Math.max(3, value.split("\n").length + 1))} onChange={(e) => onChange(e.target.value)} />
    : <input {...common} type="text" spellCheck={false} onChange={(e) => onChange(e.target.value)} />;
}

function PreviewDiffView({ diff, t }: { diff: NonNullable<ApprovalPreview["diff"]>; t: T }) {
  return <div className="approval-preview-diff" data-testid="approval-preview-diff">
    <p className="approval-preview-diff-head">
      <span>{diff.creates ? t("action_card.preview.diff_new") : t("action_card.preview.diff_changes")}</span>
      <span className="approval-preview-diff-add">+{diff.added}</span>
      <span className="approval-preview-diff-del">-{diff.removed}</span>
    </p>
    <pre>
      {diff.lines.map((line, i) => <span key={i} data-op={line.op} className="approval-preview-diff-line">{line.op === "@" ? line.text : `${line.op} ${line.text}`}{"\n"}</span>)}
      {diff.truncated ? <span className="approval-preview-diff-line" data-op="@">…</span> : null}
    </pre>
  </div>;
}

/** What the person changed, as the settled card reads it. */
export function EditedSummary({ edited }: { edited: ApprovalEdits }) {
  const t = useT();
  const keys = Object.keys(edited);
  if (!keys.length) return null;
  return <div className="approval-preview-edits" data-testid="approval-edited">
    <p className="m-0 text-[13px] font-medium text-foreground-secondary">{t("action_card.preview.you_edited")}</p>
    {keys.map((key) => <p key={key} className="m-0 text-[13px] leading-5 text-muted-foreground [overflow-wrap:anywhere]">
      {t(`action_card.preview.field.${key}`)}: <del>{edited[key].before}</del> {edited[key].after}
    </p>)}
  </div>;
}
