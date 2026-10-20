import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export interface QuickPickItem<T> {
  label: string;
  description?: string;
  detail?: string;
  icon?: ReactNode;
  value: T;
  /** Starts a titled block in the list ("Branches", "Tags"). */
  group?: string;
}

interface PickRequest {
  mode: "pick";
  items: QuickPickItem<unknown>[];
  placeholder: string;
  resolve: (value: unknown) => void;
}

interface InputRequest {
  mode: "input";
  prompt: string;
  placeholder: string;
  value: string;
  password?: boolean;
  validate?: (value: string) => string;
  resolve: (value: unknown) => void;
}

type Request = PickRequest | InputRequest;

export interface QuickInput {
  pick: <T>(items: QuickPickItem<T>[], placeholder: string) => Promise<T | undefined>;
  input: (options: { prompt: string; placeholder?: string; value?: string; validate?: (value: string) => string }) => Promise<string | undefined>;
  element: ReactNode;
}

const MAX_SHOWN = 300;

function matches(item: QuickPickItem<unknown>, words: string[]): boolean {
  const text = `${item.label} ${item.description ?? ""} ${item.detail ?? ""}`.toLowerCase();
  return words.every((word) => text.includes(word));
}

function Widget({ request, onDone }: { request: Request; onDone: (value: unknown) => void }) {
  const [text, setText] = useState(request.mode === "input" ? request.value : "");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    input.current?.focus();
    if (request.mode === "input") input.current?.select();
  }, [request]);

  const shown = useMemo(() => {
    if (request.mode !== "pick") return [];
    const words = text.toLowerCase().split(/\s+/).filter(Boolean);
    return request.items.filter((item) => matches(item, words)).slice(0, MAX_SHOWN);
  }, [request, text]);
  useEffect(() => setActive(0), [text]);
  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-pick-index="${active}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [active]);

  const error = request.mode === "input" && request.validate ? request.validate(text) : "";
  const accept = () => {
    if (request.mode === "pick") {
      const item = shown[active];
      if (item) onDone(item.value);
      return;
    }
    if (!error) onDone(text);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      data-testid="scm-quick-input"
      className="scm-portal absolute inset-x-[8px] top-[4px] z-[60] overflow-hidden rounded-[6px]"
      style={{ background: "var(--scm-menu-bg)", color: "var(--scm-menu-fg)", border: "1px solid var(--scm-menu-border)", boxShadow: "0 0 8px 2px rgba(0, 0, 0, 0.36)" }}
      onKeyDown={(event) => {
        if (event.key === "Escape") onDone(undefined);
        else if (event.key === "Enter") accept();
        else if (event.key === "ArrowDown" && shown.length) setActive((value) => (value + 1) % shown.length);
        else if (event.key === "ArrowUp" && shown.length) setActive((value) => (value - 1 + shown.length) % shown.length);
        else return;
        event.preventDefault();
        event.stopPropagation();
      }}
    >
      <div className="px-[6px] pb-[6px] pt-[6px]">
        <input
          ref={input}
          data-testid="scm-quick-input-box"
          value={text}
          type={request.mode === "input" && request.password ? "password" : "text"}
          placeholder={request.placeholder}
          aria-invalid={Boolean(error) || undefined}
          onChange={(event) => setText(event.target.value)}
          onBlur={(event) => {
            // A click inside the widget keeps it; anywhere else cancels, as Escape does.
            if (!event.currentTarget.closest("[data-testid=scm-quick-input]")?.contains(event.relatedTarget as Node | null)) onDone(undefined);
          }}
          className="scm-input h-[26px] w-full px-[6px] text-[13px]"
          style={error ? { borderColor: "var(--scm-error-border)", outlineColor: "var(--scm-error-border)" } : undefined}
        />
        {request.mode === "input" && (
          <p data-testid="scm-quick-input-prompt" className="px-[4px] pt-[6px] text-[12px] leading-[18px]" style={error ? { color: "var(--scm-deleted)" } : { opacity: 0.8 }}>
            {error || request.prompt}
          </p>
        )}
      </div>
      {request.mode === "pick" && (
        <div ref={list} role="listbox" className="max-h-[min(50vh,440px)] overflow-y-auto pb-[6px]">
          {shown.map((item, index) => (
            <div key={`${item.label}-${index}`}>
              {item.group && (index === 0 || shown[index - 1].group !== item.group) && (
                <div className="mx-[6px] flex h-[22px] items-center justify-end border-t px-[6px] text-[11px]" style={{ borderColor: "var(--scm-menu-separator)", color: "var(--scm-desc-fg)" }}>
                  {item.group}
                </div>
              )}
              <button
                type="button"
                role="option"
                tabIndex={-1}
                aria-selected={index === active}
                data-pick-index={index}
                data-testid="scm-quick-pick-item"
                onMouseMove={() => setActive(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => onDone(item.value)}
                style={index === active ? { background: "var(--scm-menu-selection)", color: "var(--scm-menu-selection-fg)" } : undefined}
                className="mx-[6px] flex h-[22px] w-[calc(100%-12px)] min-w-0 items-center gap-[6px] rounded-[3px] px-[6px] text-left text-[13px]"
              >
                {item.icon && <span className="flex h-4 w-4 shrink-0 items-center justify-center">{item.icon}</span>}
                <span className="min-w-0 flex-1">
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="truncate">{item.label}</span>
                    {item.description && <span className="min-w-0 truncate text-[0.9em] opacity-70">{item.description}</span>}
                  </span>
                  {item.detail && <span className="block truncate text-[11px] opacity-60">{item.detail}</span>}
                </span>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** A filterable pick list and a one-line input box at the top of the Git tab. */
export function useQuickInput(): QuickInput {
  const [request, setRequest] = useState<Request | null>(null);
  const pending = useRef<Request | null>(null);
  const open = useCallback((next: Request) => {
    pending.current?.resolve(undefined);
    pending.current = next;
    setRequest(next);
  }, []);
  useEffect(() => () => pending.current?.resolve(undefined), []);
  const pick = useCallback(
    <T,>(items: QuickPickItem<T>[], placeholder: string) =>
      new Promise<T | undefined>((resolve) =>
        open({ mode: "pick", items: items as QuickPickItem<unknown>[], placeholder, resolve: resolve as (value: unknown) => void }),
      ),
    [open],
  );
  const input = useCallback(
    (options: { prompt: string; placeholder?: string; value?: string; validate?: (value: string) => string }) =>
      new Promise<string | undefined>((resolve) =>
        open({
          mode: "input",
          prompt: options.prompt,
          placeholder: options.placeholder ?? "",
          value: options.value ?? "",
          validate: options.validate,
          resolve: resolve as (value: unknown) => void,
        }),
      ),
    [open],
  );
  const done = useCallback((value: unknown) => {
    const current = pending.current;
    pending.current = null;
    setRequest(null);
    current?.resolve(value);
  }, []);
  const element = request ? <Widget key={request.mode + (request.mode === "pick" ? request.placeholder : request.prompt)} request={request} onDone={done} /> : null;
  return { pick, input, element };
}
