/**
 * "New whiteboard": a blank board, made at once and opened.
 *
 * A board needs no brief to start from, so unlike the other types it skips
 * the new-node dialog: the stage's toolbar and the library's whiteboard shelf
 * both make one straight away. (Asking the assistant to draw something still
 * goes through the dialog, or through the board itself.)
 *
 * Kept apart from the editor so that offering the button does not load the
 * editor's large chunk.
 */
import { useCallback, useState } from "react";

import { useT, useUiLanguage } from "@/i18n";
import { useEventStore } from "@/store/events";
import type { NodeCard } from "../nodeModel";
import { useNodeActions } from "../useNodes";

export function useNewWhiteboard(onCreated: (card: NodeCard) => void): { create: () => Promise<void>; creating: boolean } {
  const t = useT();
  const language = useUiLanguage();
  const actions = useNodeActions();
  const pushToast = useEventStore((s) => s.pushToast);
  const [creating, setCreating] = useState(false);

  const create = useCallback(async () => {
    if (creating) return;
    setCreating(true);
    let card: NodeCard;
    try {
      card = await actions.createNode({ type: "whiteboard", language });
    } catch {
      pushToast("error", t("nodes.whiteboard.new_failed"));
      setCreating(false);
      return;
    }
    setCreating(false);
    onCreated(card);
  }, [actions, creating, language, onCreated, pushToast, t]);

  return { create, creating };
}
