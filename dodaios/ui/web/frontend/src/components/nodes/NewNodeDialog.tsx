/**
 * The dialog behind "Describe it to …", the last entry of the library's
 * "New" menu (the kinds above it start a blank node without asking).
 *
 * It asks one thing: what the new node should be about. With an answer, the
 * primary action hands it to the assistant as the reader's own message in
 * the lead conversation and closes; the library then shows a placeholder
 * until the node arrives. Without one (or for someone who would rather start
 * from a blank), the secondary action creates a starter node of the type and
 * opens it.
 *
 * An Analytics node also asks where its data comes from and whether the
 * assistant should keep it current (`AnalyticsFields`); both go into the
 * request.
 *
 * A request that could not be sent keeps the dialog open with what was
 * typed and says so.
 */
import { useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useT, useUiLanguage } from "@/i18n";
import { cn } from "@/lib/utils";
import { AnalyticsFields, DEFAULT_ANALYTICS_CADENCE, type AnalyticsCadence } from "./AnalyticsFields";
import { requestNewNode, type AnalyticsRequest } from "./askDodaios";
import { NODE_TYPES, type NodeCard, type NodeType } from "./nodeModel";
import { NODE_TYPE_LABEL_KEY, nodeHueStyle } from "./nodeTheme";
import { NodeTypeIcon } from "./NodeTypeIcon";
import { useNodeActions } from "./useNodes";

/** The three example requests each type offers (`nodes.new.examples.<type>.<id>`). */
const EXAMPLE_IDS = ["a", "b", "c"] as const;
/** A starter node takes what was typed as its name, up to a title's length. */
const MAX_TITLE_CHARS = 80;

export interface NewNodeDialogProps {
  /** The type the new node starts as; null keeps the dialog closed. */
  type: NodeType | null;
  /** The reader chose another type in the dialog. */
  onType: (type: NodeType) => void;
  onClose: () => void;
  /** The request went out: the library registers a placeholder for it. */
  onRequested: (type: NodeType, request: string) => void;
  /** A starter node was created: the library opens it. */
  onCreated: (card: NodeCard) => void;
}

export function NewNodeDialog({ type, onType, onClose, onRequested, onCreated }: NewNodeDialogProps) {
  const [busy, setBusy] = useState(false);
  const content = useRef<HTMLDivElement>(null);

  return (
    <Dialog.Root open={type !== null} onOpenChange={(open) => !open && !busy && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-scrim/50 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          ref={content}
          data-testid="new-node-dialog"
          onOpenAutoFocus={(event) => {
            const field = content.current?.querySelector("textarea");
            if (!field) return;
            event.preventDefault();
            field.focus();
          }}
          className="fixed left-1/2 top-[14%] z-[90] max-h-[calc(100vh-14%-1rem)] w-[min(540px,calc(100vw-2rem))] -translate-x-1/2 overflow-y-auto rounded-xl border border-border bg-popover p-6 text-popover-foreground shadow-float data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
        >
          {type !== null && (
            <NewNodeForm
              type={type}
              onType={onType}
              busy={busy}
              onBusy={setBusy}
              onClose={onClose}
              onRequested={onRequested}
              onCreated={onCreated}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * Mounted while the dialog is open, so it opens on an empty field every time
 * and keeps what was typed when the reader switches the type.
 */
function NewNodeForm({
  type,
  onType,
  busy,
  onBusy,
  onClose,
  onRequested,
  onCreated,
}: {
  type: NodeType;
  busy: boolean;
  onBusy: (busy: boolean) => void;
} & Pick<NewNodeDialogProps, "onType" | "onClose" | "onRequested" | "onCreated">) {
  const t = useT();
  const language = useUiLanguage();
  const actions = useNodeActions();
  const [text, setText] = useState("");
  // Analytics only: where the data comes from, and whether it stays current.
  const [sources, setSources] = useState("");
  const [live, setLive] = useState(false);
  const [every, setEvery] = useState<AnalyticsCadence>(DEFAULT_ANALYTICS_CADENCE);
  const [error, setError] = useState<string | null>(null);
  /** Which of the two actions is under way, for its spinner. */
  const [working, setWorking] = useState<"request" | "empty" | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);

  const request = text.trim();
  const analytics: AnalyticsRequest | undefined =
    type === "data" ? { sources, everyMinutes: live ? every : null } : undefined;
  // An analysis can be asked for by its sources alone ("my portfolio").
  const canRequest = request !== "" || (analytics !== undefined && sources.trim() !== "");
  const typeName = t(NODE_TYPE_LABEL_KEY[type]);

  const begin = (which: "request" | "empty") => {
    setWorking(which);
    setError(null);
    onBusy(true);
  };
  const fail = (sentence: string) => {
    setWorking(null);
    onBusy(false);
    setError(sentence);
  };

  const createWithAssistant = async () => {
    if (busy || !canRequest) return;
    begin("request");
    try {
      await requestNewNode(type, request, analytics);
    } catch {
      // Nothing reached the assistant: the dialog stays, with what was typed.
      fail(t("nodes.new.send_failed"));
      return;
    }
    setWorking(null);
    onBusy(false);
    onRequested(type, request || sources.trim());
    onClose();
  };

  const startEmpty = async () => {
    if (busy) return;
    begin("empty");
    let card: NodeCard;
    try {
      card = await actions.createNode({
        type,
        title: request === "" ? undefined : request.slice(0, MAX_TITLE_CHARS),
        language,
      });
    } catch {
      fail(t("nodes.new.create_failed"));
      return;
    }
    setWorking(null);
    onBusy(false);
    onClose();
    onCreated(card);
  };

  const onFieldKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    // Enter is a new line in a text area; with the platform's modifier it sends.
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void createWithAssistant();
    }
  };

  return (
    <>
      <div className="flex items-center gap-3.5">
        <span
          aria-hidden
          style={nodeHueStyle(type)}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--node-hue)/0.14)] text-[hsl(var(--node-hue))]"
        >
          <NodeTypeIcon type={type} className="h-6 w-6" />
        </span>
        <div className="min-w-0">
          <Dialog.Title className="text-xl font-semibold text-foreground-strong">{typeName}</Dialog.Title>
          <Dialog.Description className="text-base text-muted-foreground">
            {t(`nodes.new.about.${type}`)}
          </Dialog.Description>
        </div>
      </div>

      <div
        role="radiogroup"
        aria-label={t("nodes.new.type_label")}
        className="mt-5 flex flex-wrap gap-1.5"
        data-testid="new-node-types"
      >
        {NODE_TYPES.map((option) => {
          const chosen = option === type;
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={chosen}
              disabled={busy}
              onClick={() => {
                onType(option);
                setError(null);
              }}
              style={nodeHueStyle(option)}
              data-testid={`new-node-type-${option}`}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-sm transition-colors duration-fast",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
                chosen
                  ? "border-[hsl(var(--node-hue)/0.5)] bg-[hsl(var(--node-hue)/0.14)] text-foreground-strong"
                  : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
              )}
            >
              <NodeTypeIcon
                type={option}
                className={cn("h-3.5 w-3.5", chosen && "text-[hsl(var(--node-hue))]")}
              />
              {t(NODE_TYPE_LABEL_KEY[option])}
            </button>
          );
        })}
      </div>

      <label htmlFor="new-node-request" className="mt-5 block text-base font-medium text-foreground">
        {t("nodes.new.prompt_label")}
      </label>
      <Textarea
        id="new-node-request"
        ref={field}
        rows={4}
        value={text}
        disabled={busy}
        placeholder={t(`nodes.new.placeholder.${type}`)}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onFieldKeyDown}
        data-testid="new-node-request"
        className="mt-2 min-h-[104px] resize-none"
      />

      <ul aria-label={t("nodes.new.examples_label")} className="mt-3 flex flex-wrap gap-2">
        {EXAMPLE_IDS.map((id) => {
          const example = t(`nodes.new.examples.${type}.${id}`);
          return (
            <li key={id} className="min-w-0 max-w-full">
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setText(example);
                  setError(null);
                  field.current?.focus();
                }}
                data-testid="new-node-example"
                className="max-w-full truncate rounded-full border border-border bg-transparent px-3 py-1 text-left text-sm text-muted-foreground transition-colors duration-fast hover:border-border-strong hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
              >
                {example}
              </button>
            </li>
          );
        })}
      </ul>

      {type === "data" && (
        <AnalyticsFields
          sources={sources}
          onSources={(value) => {
            setSources(value);
            setError(null);
          }}
          live={live}
          onLive={setLive}
          every={every}
          onEvery={setEvery}
          disabled={busy}
        />
      )}

      {error && (
        <p role="alert" className="mt-4 text-sm text-destructive" data-testid="new-node-error">
          {error}
        </p>
      )}

      <div className="mt-6 flex flex-wrap items-center justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={() => void startEmpty()}
          data-testid="new-node-empty"
        >
          {working === "empty" && <Loader2 className="animate-spin" aria-hidden />}
          {t("nodes.new.empty")}
        </Button>
        <Button
          type="button"
          disabled={busy || !canRequest}
          onClick={() => void createWithAssistant()}
          data-testid="new-node-create"
        >
          {working === "request" && <Loader2 className="animate-spin" aria-hidden />}
          {t("nodes.new.create")}
        </Button>
      </div>
    </>
  );
}
