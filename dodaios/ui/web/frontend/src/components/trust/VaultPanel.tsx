import { useCallback, useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import {
  Asterisk,
  Database,
  FileKey,
  Fingerprint,
  Globe,
  IdCard,
  KeyRound,
  Loader2,
  Lock,
  Plus,
  Ticket,
  Trash2,
  LockKeyhole,
  Webhook,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { BrandedSelect } from "@/components/ui/select";
import { fill, useT } from "@/i18n";
import {
  deleteVaultLogin,
  deleteVaultSecret,
  envNameFor,
  fetchVault,
  storeVaultLogin,
  storeVaultSecret,
  type SecretKind,
  type VaultOverview,
  type VaultSecret,
} from "@/lib/trustApi";
import { useEventStore } from "@/store/events";

/**
 * Settings → Trust → Vault: everything the owner gives the assistant to use.
 *
 * Secrets of every kind (API keys, tokens, client IDs and secrets, passwords,
 * connection strings, webhook URLs, private keys) and website logins. The
 * assistant uses a secret by its name inside its commands and never sees a
 * value: this page shows names, kinds and notes, and a value only ever travels
 * one way, from a field here (or the secure field in the chat) into the
 * system's credential store. Replacing a secret means pasting a new value;
 * nothing is ever shown again, not even here.
 */

const KIND_ICONS: Record<SecretKind, typeof KeyRound> = {
  api_key: KeyRound,
  token: Ticket,
  client_id: IdCard,
  client_secret: Fingerprint,
  password: Asterisk,
  connection_string: Database,
  webhook_url: Webhook,
  private_key: FileKey,
  other: Lock,
};

const FIELD_SAFETY = {
  autoComplete: "new-password",
  autoCorrect: "off",
  autoCapitalize: "off",
  spellCheck: false,
  "data-1p-ignore": true,
  "data-lpignore": "true",
} as const;

function Tile({ children }: { children: ReactNode }) {
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-foreground-secondary [&>svg]:h-4 [&>svg]:w-4">
      {children}
    </span>
  );
}

export function VaultPanel() {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const [data, setData] = useState<VaultOverview | null>(null);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState<VaultSecret | "new" | null>(null);
  const [addingLogin, setAddingLogin] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await fetchVault());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const remove = async (id: string, run: () => Promise<unknown>) => {
    if (confirming !== id) {
      setConfirming(id);
      return;
    }
    setBusy(true);
    try {
      await run();
      pushToast("success", t("trust.page.vault_deleted"));
      await load();
    } catch {
      pushToast("error", t("trust.page.vault_delete_failed"));
    } finally {
      setConfirming(null);
      setBusy(false);
    }
  };

  if (failed) return <p className="py-6 text-sm text-destructive">{t("trust.page.vault_load_failed")}</p>;
  if (!data) {
    return (
      <p className="flex items-center gap-2 py-6 text-sm text-muted-foreground" data-testid="vault-loading">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("trust.page.loading")}
      </p>
    );
  }

  const kindLabel = (kind: SecretKind) => t(`trust.page.vault_kind_${kind}`);

  return (
    <div className="flex flex-col gap-10 pt-6" data-testid="vault-panel">
      <section>
        <h2 className="m-0 flex items-center gap-2 text-base font-semibold text-foreground">
          <LockKeyhole aria-hidden className="h-4 w-4" />
          {t("trust.page.vault_title")}
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("trust.page.vault_intro")}</p>
      </section>

      <section>
        <div className="flex items-center gap-3">
          <h2 className="m-0 flex-1 text-base font-semibold text-foreground">{t("trust.page.vault_secrets_title")}</h2>
          {editing === null && (
            <Button variant="outline" size="sm" onClick={() => setEditing("new")} data-testid="vault-add-secret">
              <Plus aria-hidden className="h-4 w-4" />
              {t("trust.page.vault_add_secret")}
            </Button>
          )}
        </div>
        {editing !== null && (
          <SecretForm
            key={editing === "new" ? "new" : editing.env}
            kinds={data.kinds}
            existing={editing === "new" ? null : editing}
            taken={data.secrets.map((s) => s.env)}
            kindLabel={kindLabel}
            onDone={async (saved) => {
              setEditing(null);
              if (saved) {
                pushToast("success", t("trust.page.vault_saved"));
                await load();
              }
            }}
          />
        )}
        {data.secrets.length === 0 ? (
          editing === null && (
            <p className="mt-4 text-sm text-foreground-secondary" data-testid="vault-secrets-empty">
              {t("trust.page.vault_secrets_empty")}
            </p>
          )
        ) : (
          <ul className="mt-4 divide-y divide-border rounded-lg border border-border" data-testid="vault-secrets">
            {data.secrets.map((secret) => {
              const Icon = KIND_ICONS[secret.kind] ?? Lock;
              const id = `secret:${secret.env}`;
              return (
                <li key={secret.env} className="flex items-center gap-3 px-4 py-3" data-testid="vault-secret">
                  <Tile>
                    <Icon aria-hidden />
                  </Tile>
                  <div className="min-w-0 flex-1">
                    <p className="m-0 truncate text-sm font-medium text-foreground">{secret.label || secret.env}</p>
                    <p className="m-0 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                      <span className="shrink-0">{kindLabel(secret.kind)}</span>
                      <span aria-hidden>·</span>
                      <code className="truncate">{secret.env}</code>
                    </p>
                    {secret.note && <p className="m-0 truncate text-xs text-muted-foreground">{secret.note}</p>}
                    {!secret.present && (
                      <p className="m-0 text-xs text-destructive" data-testid="vault-secret-missing">
                        {t("trust.page.vault_value_missing")}
                      </p>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy || editing !== null}
                    onClick={() => setEditing(secret)}
                    data-testid="vault-secret-replace"
                  >
                    {t("trust.page.vault_replace")}
                  </Button>
                  <Button
                    variant={confirming === id ? "destructive" : "ghost"}
                    size="sm"
                    disabled={busy}
                    onClick={() => void remove(id, () => deleteVaultSecret(secret.env))}
                    onBlur={() => setConfirming((c) => (c === id ? null : c))}
                    aria-label={fill(t("trust.page.vault_delete_named"), { label: secret.label || secret.env })}
                    data-testid="vault-secret-delete"
                  >
                    {confirming === id ? t("trust.page.vault_delete_confirm") : <Trash2 aria-hidden className="h-4 w-4" />}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section>
        <div className="flex items-center gap-3">
          <h2 className="m-0 flex-1 text-base font-semibold text-foreground">{t("trust.page.vault_logins_title")}</h2>
          {!addingLogin && (
            <Button variant="outline" size="sm" onClick={() => setAddingLogin(true)} data-testid="vault-add-login">
              <Plus aria-hidden className="h-4 w-4" />
              {t("trust.page.vault_add_login")}
            </Button>
          )}
        </div>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("trust.page.vault_logins_intro")}</p>
        {addingLogin && (
          <LoginForm
            onDone={async (saved) => {
              setAddingLogin(false);
              if (saved) {
                pushToast("success", t("trust.page.vault_saved"));
                await load();
              }
            }}
          />
        )}
        {data.logins.length === 0 ? (
          !addingLogin && (
            <p className="mt-4 text-sm text-foreground-secondary" data-testid="vault-logins-empty">
              {t("trust.page.vault_logins_empty")}
            </p>
          )
        ) : (
          <ul className="mt-4 divide-y divide-border rounded-lg border border-border" data-testid="vault-logins">
            {data.logins.map((login) => {
              const id = `login:${login.key}`;
              return (
                <li key={login.key} className="flex items-center gap-3 px-4 py-3" data-testid="vault-login">
                  <Tile>
                    <Globe aria-hidden />
                  </Tile>
                  <div className="min-w-0 flex-1">
                    <p className="m-0 truncate text-sm font-medium text-foreground">{login.label}</p>
                    <p className="m-0 truncate text-xs text-muted-foreground">{login.domain}</p>
                  </div>
                  <Button
                    variant={confirming === id ? "destructive" : "ghost"}
                    size="sm"
                    disabled={busy}
                    onClick={() => void remove(id, () => deleteVaultLogin(login.key))}
                    onBlur={() => setConfirming((c) => (c === id ? null : c))}
                    aria-label={fill(t("trust.page.vault_delete_named"), { label: login.label })}
                    data-testid="vault-login-delete"
                  >
                    {confirming === id ? t("trust.page.vault_delete_confirm") : <Trash2 aria-hidden className="h-4 w-4" />}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

function FormFrame({ onSubmit, children, testId }: { onSubmit: (e: FormEvent) => void; children: ReactNode; testId: string }) {
  return (
    <form
      onSubmit={onSubmit}
      className="mt-4 flex flex-col gap-3 rounded-lg border border-border bg-card p-4"
      data-testid={testId}
    >
      {children}
    </form>
  );
}

function Field({ label, children, htmlFor }: { label: string; children: ReactNode; htmlFor: string }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-foreground-secondary">
        {label}
      </label>
      {children}
    </div>
  );
}

function SecretForm({
  kinds,
  existing,
  taken,
  kindLabel,
  onDone,
}: {
  kinds: SecretKind[];
  existing: VaultSecret | null;
  taken: string[];
  kindLabel: (kind: SecretKind) => string;
  onDone: (saved: boolean) => void | Promise<void>;
}) {
  const t = useT();
  const ids = useId();
  const [kind, setKind] = useState<SecretKind>(existing?.kind ?? "api_key");
  const [label, setLabel] = useState(existing?.label ?? "");
  const [env, setEnv] = useState(existing?.env ?? "");
  const [envTouched, setEnvTouched] = useState(Boolean(existing));
  const [value, setValue] = useState("");
  const [note, setNote] = useState(existing?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const name = envTouched ? env : envNameFor(label);
  const clash = !existing && taken.includes(name);
  const multiline = kind === "private_key";
  const ready = label.trim() !== "" && /^[A-Z][A-Z0-9_]{1,63}$/.test(name) && value.trim() !== "" && !clash;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      await storeVaultSecret(name, { value: value.trim(), label: label.trim(), kind, note: note.trim() });
      setValue("");
      await onDone(true);
    } catch (err) {
      setError(err instanceof Error && err.message && !err.message.startsWith("HTTP") ? err.message : t("trust.page.vault_save_failed"));
      setBusy(false);
    }
  };

  const fieldClass = "w-full";
  return (
    <FormFrame onSubmit={(e) => void submit(e)} testId="vault-secret-form">
      <div className="flex flex-col gap-3 sm:flex-row">
        <Field label={t("trust.page.vault_field_kind")} htmlFor={`${ids}-kind`}>
          <BrandedSelect
            id={`${ids}-kind`}
            value={kind}
            options={kinds.map((k) => ({ value: k, label: kindLabel(k) }))}
            onValueChange={(v) => setKind(v as SecretKind)}
            ariaLabel={t("trust.page.vault_field_kind")}
            disabled={busy}
            testId="vault-secret-kind"
          />
        </Field>
        <Field label={t("trust.page.vault_field_label")} htmlFor={`${ids}-label`}>
          <Input
            id={`${ids}-label`}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={t("trust.page.vault_field_label_hint")}
            maxLength={120}
            disabled={busy}
            className={fieldClass}
            data-testid="vault-secret-label"
          />
        </Field>
      </div>
      <Field label={t("trust.page.vault_field_value")} htmlFor={`${ids}-value`}>
        {multiline ? (
          <textarea
            id={`${ids}-value`}
            {...FIELD_SAFETY}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={5}
            maxLength={16384}
            disabled={busy}
            className="w-full rounded-md border border-border-strong bg-input px-3 py-2 font-mono text-xs text-foreground focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [-webkit-text-security:disc]"
            data-testid="vault-secret-value"
          />
        ) : (
          <Input
            id={`${ids}-value`}
            type="password"
            {...FIELD_SAFETY}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            maxLength={16384}
            placeholder={existing ? t("trust.page.vault_field_value_new") : undefined}
            disabled={busy}
            className={fieldClass}
            data-testid="vault-secret-value"
          />
        )}
      </Field>
      <div className="flex flex-col gap-3 sm:flex-row">
        <Field label={t("trust.page.vault_field_env")} htmlFor={`${ids}-env`}>
          <Input
            id={`${ids}-env`}
            value={name}
            onChange={(e) => {
              setEnvTouched(true);
              setEnv(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "_").slice(0, 64));
            }}
            readOnly={Boolean(existing)}
            disabled={busy}
            className={`${fieldClass} font-mono text-sm`}
            data-testid="vault-secret-env"
          />
        </Field>
        <Field label={t("trust.page.vault_field_note")} htmlFor={`${ids}-note`}>
          <Input
            id={`${ids}-note`}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("trust.page.vault_field_note_hint")}
            maxLength={300}
            disabled={busy}
            className={fieldClass}
            data-testid="vault-secret-note"
          />
        </Field>
      </div>
      <p className="m-0 text-xs text-muted-foreground">
        {clash ? t("trust.page.vault_env_taken") : fill(t("trust.page.vault_env_hint"), { env: name || "NAME" })}
      </p>
      {error && (
        <p role="alert" className="m-0 text-xs text-destructive">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void onDone(false)}>
          {t("trust.page.vault_cancel")}
        </Button>
        <Button type="submit" size="sm" disabled={!ready || busy} data-testid="vault-secret-save">
          {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
          {t("trust.page.vault_save")}
        </Button>
      </div>
    </FormFrame>
  );
}

function LoginForm({ onDone }: { onDone: (saved: boolean) => void | Promise<void> }) {
  const t = useT();
  const ids = useId();
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = label.trim() && url.trim() && username.trim() && password;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      await storeVaultLogin({ label: label.trim(), url: url.trim(), username: username.trim(), password });
      setPassword("");
      await onDone(true);
    } catch (err) {
      setError(err instanceof Error && err.message && !err.message.startsWith("HTTP") ? err.message : t("trust.page.vault_save_failed"));
      setBusy(false);
    }
  };

  return (
    <FormFrame onSubmit={(e) => void submit(e)} testId="vault-login-form">
      <div className="flex flex-col gap-3 sm:flex-row">
        <Field label={t("trust.page.vault_field_site")} htmlFor={`${ids}-label`}>
          <Input id={`${ids}-label`} value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120}
            placeholder={t("trust.page.vault_field_site_hint")} disabled={busy} data-testid="vault-login-label" />
        </Field>
        <Field label={t("trust.page.vault_field_url")} htmlFor={`${ids}-url`}>
          <Input id={`${ids}-url`} value={url} onChange={(e) => setUrl(e.target.value)} maxLength={300}
            placeholder="https://" disabled={busy} data-testid="vault-login-url" />
        </Field>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row">
        <Field label={t("trust.page.vault_field_username")} htmlFor={`${ids}-user`}>
          <Input id={`${ids}-user`} {...FIELD_SAFETY} autoComplete="off" value={username}
            onChange={(e) => setUsername(e.target.value)} maxLength={1024} disabled={busy} data-testid="vault-login-username" />
        </Field>
        <Field label={t("trust.page.vault_field_password")} htmlFor={`${ids}-pass`}>
          <Input id={`${ids}-pass`} type="password" {...FIELD_SAFETY} value={password}
            onChange={(e) => setPassword(e.target.value)} maxLength={1024} disabled={busy} data-testid="vault-login-password" />
        </Field>
      </div>
      {error && (
        <p role="alert" className="m-0 text-xs text-destructive">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void onDone(false)}>
          {t("trust.page.vault_cancel")}
        </Button>
        <Button type="submit" size="sm" disabled={!ready || busy} data-testid="vault-login-save">
          {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
          {t("trust.page.vault_save")}
        </Button>
      </div>
    </FormFrame>
  );
}
