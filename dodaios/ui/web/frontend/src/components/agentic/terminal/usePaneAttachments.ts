import { useCallback, useEffect, useState } from "react";
import { extractPaneDrop, extractPasteFiles, isEmptyPayload, nameClipboardFile, type PaneDropPayload } from "../paneDrop";
import { usePaneFileDrag } from "../paneFileDrag";
import { PANE_PASTE_EVENT, announceSkillRefused, pasteSkillText, type PanePasteDetail, type SkillDragPayload } from "../skillDrag";
import { useIdeSkillsStore } from "@/store/ideSkills";
import { attachToTerminal } from "@/lib/agenticIdeApi";
import { translate } from "@/i18n";
import type { PanePorts } from "./connect/paneRuntime";
import type { MutableRefObject } from "react";

export function usePaneAttachments({ containerRef, termRef, name, workspaceId, onAttachError, onFocus, takeOwnershipRef, flashDelivered }: {
  containerRef: MutableRefObject<HTMLDivElement | null>;
  termRef: PanePorts["termRef"];
  name: string;
  workspaceId: string | undefined;
  onAttachError: ((message: string) => void) | undefined;
  onFocus: (() => void) | undefined;
  takeOwnershipRef: PanePorts["takeOwnershipRef"];
  flashDelivered: (ms: number) => void;
}) {
  /*
   * Drag a file onto the pane, or paste a screenshot into it.
   *
   * A native terminal writes a dragged file's PATH into the prompt; a browser
   * cannot, because it never tells a web page where a file lives. So the drop is
   * read synchronously (a DataTransfer empties the instant this handler
   * returns — see ./paneDrop), handed to the backend, and what comes back is
   * already typed into the agent's input.
   *
   * Deliberately typed and NOT submitted: someone dropping a screenshot wants to
   * say what to do with it. The reference appears, the cursor sits after it.
   *
   * WHEN the pane arms for a drop — and when it must stay quiet — lives in
   * ./paneFileDrag, because getting that wrong is what made a pane offer itself
   * to a user who was holding nothing at all (BUG-110).
   */
  const [attaching, setAttaching] = useState(false);

  const attach = useCallback(
    async (payload: PaneDropPayload) => {
      if (isEmptyPayload(payload)) {
        onAttachError?.(translate("agentic_grid.pane.drop_empty"));
        return;
      }
      setAttaching(true);
      try {
        await attachToTerminal(name, payload);
        termRef.current?.focus();
      } catch (e) {
        onAttachError?.((e as Error).message);
      } finally {
        setAttaching(false);
      }
    },
    [name, onAttachError],
  );

  /*
   * A skill from the side panel's Skills tab: its Markdown goes into the
   * agent's prompt as ONE bracketed paste — the same thing Ctrl+V does — so a
   * multi-line text never submits itself line by line. Not sent: the user
   * still says what to do with it.
   */
  const pasteSkill = useCallback(
    (skill: SkillDragPayload) => {
      const term = termRef.current;
      if (!term || !skill.content) return;
      onFocus?.();
      takeOwnershipRef.current?.();
      if (!pasteSkillText(term, skill.content)) {
        announceSkillRefused(name);
        return;
      }
      flashDelivered(1_200);
      useIdeSkillsStore.getState().recordUse(skill.id, name);
    },
    [name, onFocus],
  );

  const { dragging, carrying, handlers: dragHandlers } = usePaneFileDrag(
    useCallback(
      (dt: DataTransfer) => {
        onFocus?.();
        // Read BEFORE any await — the DataTransfer is gone after this returns.
        void attach(extractPaneDrop(dt));
      },
      [attach, onFocus],
    ),
    pasteSkill,
  );
  const skillInFlight = useIdeSkillsStore((state) => (carrying === "skill" ? state.dragging : null));

  // "Paste into …" on a skill card: the same paste, addressed by name.
  useEffect(() => {
    const onPaste = (event: Event) => {
      const detail = (event as CustomEvent<PanePasteDetail>).detail;
      if (detail?.pane !== name || (workspaceId && detail.workspaceId !== workspaceId)) return;
      pasteSkill(detail.skill);
    };
    window.addEventListener(PANE_PASTE_EVENT, onPaste);
    return () => window.removeEventListener(PANE_PASTE_EVENT, onPaste);
  }, [name, workspaceId, pasteSkill]);

  // Clipboard images only — pasted TEXT belongs to xterm, which turns it into a
  // proper bracketed paste the agent's prompt box understands.
  //
  // Registered in the CAPTURE phase, and that is load-bearing rather than a
  // style choice: xterm's own paste handler calls `stopPropagation()`, so a
  // listener sitting on this container in the normal bubbling phase is never
  // reached at all and pasting a screenshot silently did nothing. Capture
  // travels down to the target, so it gets there first.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const onPaste = (event: ClipboardEvent) => {
      const images = extractPasteFiles(event.clipboardData).map((f) =>
        nameClipboardFile(f, name),
      );
      if (images.length === 0) return;
      event.preventDefault();
      void attach({ paths: [], files: images });
    };
    container.addEventListener("paste", onPaste, true);
    return () => container.removeEventListener("paste", onPaste, true);
  }, [attach, name]);
  return { dragging, carrying, dragHandlers, attaching, skillInFlight };
}
