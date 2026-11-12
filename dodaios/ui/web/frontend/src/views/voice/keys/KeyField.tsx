import { useState } from "react";
import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  deleteSecret,
  postSecret,
  type SecretSaveResult,
  type SecretSaveScope,
} from "@/hooks/useProviders";
import { fill, useT } from "@/i18n";
import { keyMatchesSecret } from "@/lib/keyFormat";
import { providerName } from "@/views/voice/keys/names";
import { RowNote } from "@/views/voice/keys/RowNote";
import { IconAction } from "@/views/voice/kit";

/**
 * Tell every mounted screen that a key slot changed. `useProviders` and the
 * section health listen for this event, so the main API Keys screen and this
 * one never disagree. Only the slot's name travels, never a value.
 */
function announceKeyChange(slot: string, action: "set" | "delete") {
  window.dispatchEvent(
    new CustomEvent("jarvis:secret-configured", { detail: { key: slot, action } }),
  );
}

export interface KeyFieldProps {
  /** The key slot this field writes. */
  slot: string;
  /** The provider's name, for the field's accessible name. */
  provider: string;
  /** Whether this slot holds a key now. */
  stored: boolean;
  /** Names of the other places that read the same slot. */
  sharedWith?: readonly string[];
  /** Called after a key was saved or removed, to read the provider list again. */
  onChanged?: () => void;
  onSaved?: () => void;
  onRemoved?: () => void;
  testId?: string;
}

/**
 * One key: a field and Save, and Remove when a key is stored.
 *
 * Two questions can come up, each as one sentence with its answers: the
 * provider already holds a different key (replace it everywhere, or keep this
 * one for this place only), and the key to remove is used elsewhere too.
 */
export function KeyField({
  slot,
  provider,
  stored,
  sharedWith = [],
  onChanged,
  onSaved,
  onRemoved,
  testId,
}: KeyFieldProps) {
  const t = useT();
  const [value, setValue] = useState("");
  const [pending, setPending] = useState(false);
  const [fault, setFault] = useState<"save_failed" | "remove_failed" | null>(null);
  const [scopeQuestion, setScopeQuestion] = useState<SecretSaveResult | null>(null);
  const [confirmingRemove, setConfirmingRemove] = useState(false);

  const entered = value.trim();
  const others = [...new Set(sharedWith.map(providerName))].filter((name) => name !== provider);
  // A key of another provider pasted into this field. Read from the shape of
  // the text in the browser; it never blocks the save.
  const format = entered ? keyMatchesSecret(slot, entered) : null;
  const wrongKind = format && !format.match ? (format.detected?.label ?? null) : null;

  async function save(scope?: SecretSaveScope) {
    if (!entered || pending) return;
    setPending(true);
    setFault(null);
    try {
      const result = await postSecret(slot, entered, scope);
      if (result?.choice_required) {
        // Nothing was written: the provider holds a different key already.
        setScopeQuestion(result);
        return;
      }
      setScopeQuestion(null);
      setValue("");
      onChanged?.();
      onSaved?.();
      // The provider's shared slot may have been written as well.
      for (const written of new Set([slot, ...(result?.written ?? [])])) {
        announceKeyChange(written, "set");
      }
    } catch {
      setFault("save_failed");
    } finally {
      setPending(false);
    }
  }

  async function remove() {
    if (pending) return;
    if (sharedWith.length > 0 && !confirmingRemove) {
      setConfirmingRemove(true);
      return;
    }
    setConfirmingRemove(false);
    setPending(true);
    setFault(null);
    try {
      await deleteSecret(slot);
      onChanged?.();
      onRemoved?.();
      announceKeyChange(slot, "delete");
    } catch {
      setFault("remove_failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-stack" data-testid={testId}>
      <div className="flex items-center gap-row">
        <Input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setScopeQuestion(null);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !scopeQuestion) void save();
          }}
          aria-label={fill(t("voiceui.keys.key_named"), { provider })}
          placeholder={t(stored ? "voiceui.keys.new_key" : "voiceui.keys.paste_key")}
          className="h-10 text-title"
          data-testid={testId ? `${testId}-input` : undefined}
        />
        <Button
          size="lg"
          onClick={() => void save()}
          disabled={pending || !entered || Boolean(scopeQuestion)}
          data-testid={testId ? `${testId}-save` : undefined}
        >
          {t("voiceui.common.save")}
        </Button>
        {stored && (
          <IconAction
            label={t("voiceui.keys.remove_key")}
            onClick={() => void remove()}
            disabled={pending}
            testId={testId ? `${testId}-remove` : undefined}
          >
            <Trash2 aria-hidden="true" />
          </IconAction>
        )}
      </div>

      {wrongKind && !scopeQuestion && (
        <RowNote testId={testId ? `${testId}-wrong-kind` : undefined}>
          {fill(t("voiceui.keys.wrong_kind"), { kind: wrongKind })}
        </RowNote>
      )}

      {scopeQuestion && (
        <div className="flex flex-col gap-row" data-testid={testId ? `${testId}-scope` : undefined}>
          <p className="text-body text-foreground">
            {fill(t("voiceui.keys.family_has_key"), {
              family: scopeQuestion.family_label || provider,
            })}
          </p>
          <div className="flex flex-wrap items-center gap-row">
            <Button onClick={() => void save("everywhere")} disabled={pending}>
              {t("voiceui.keys.replace_everywhere")}
            </Button>
            <Button variant="outline" onClick={() => void save("here")} disabled={pending}>
              {t("voiceui.keys.only_here")}
            </Button>
            <Button variant="ghost" onClick={() => setScopeQuestion(null)} disabled={pending}>
              {t("voiceui.common.cancel")}
            </Button>
          </div>
        </div>
      )}

      {confirmingRemove && (
        <div className="flex flex-col gap-row" data-testid={testId ? `${testId}-shared` : undefined}>
          <p className="text-body text-foreground">
            {fill(t("voiceui.keys.shared"), { others: (others.length ? others : sharedWith).join(", ") })}
          </p>
          <div className="flex flex-wrap items-center gap-row">
            <Button variant="destructive" onClick={() => void remove()} disabled={pending}>
              {t("voiceui.keys.remove_anyway")}
            </Button>
            <Button variant="ghost" onClick={() => setConfirmingRemove(false)} disabled={pending}>
              {t("voiceui.common.cancel")}
            </Button>
          </div>
        </div>
      )}

      {fault && (
        <RowNote testId={testId ? `${testId}-fault` : undefined}>
          {t(`voiceui.keys.${fault}`)}
        </RowNote>
      )}
    </div>
  );
}
