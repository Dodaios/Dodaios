/**
 * The ways the Nodes section talks to the assistant.
 *
 * `requestNewNode` SENDS: the reader said what the new node should be about,
 * and that sentence goes into the lead conversation as their own message.
 *
 * `sendNodeComment` SENDS too: a comment the reader left on a place of the
 * node, with the text it was left on, so the assistant revises that place.
 *
 * `askDodaiosToChange` only DRAFTS: it opens the lead conversation with the
 * start of a sentence in the composer ("Change the node … : "), and the
 * reader finishes and sends it.
 *
 * Store-level on purpose (no hooks), so a menu item can call it directly.
 */
import { writeComposerDraft } from "@/components/agentchat/composerDrafts";
import { translate } from "@/i18n";
import { fetchLeadSession, sendAgentChatMessage } from "@/lib/agentChatApi";
import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import { useHomeStore } from "@/store/home";
import type { NodeComment } from "./nodeBridge";
import type { NodeCard, NodeType } from "./nodeModel";
import { NODE_TYPE_LABEL_KEY } from "./nodeTheme";

/** How many frames to wait for the composer to mount after the section switch. */
const FOCUS_ATTEMPTS = 40;

/** The message that asks for a new node of `type` about `text`. */
export function newNodeRequestText(type: NodeType, text: string): string {
  // Function replacers: a `$` in what the reader typed must stay a `$`.
  return translate("nodes.new.request")
    .replace("{0}", () => translate(NODE_TYPE_LABEL_KEY[type]))
    .replace("{1}", () => text.trim());
}

/** Ask the assistant for a new node, as the reader's own message. Rejects when it could not be sent. */
export async function requestNewNode(type: NodeType, text: string): Promise<void> {
  const session = await fetchLeadSession();
  await sendAgentChatMessage(session.session_id, newNodeRequestText(type, text));
}

/**
 * The message that asks for the change a comment describes: the node, the
 * text the comment was left on, where that is in the node, and the comment.
 */
export function nodeCommentText(card: NodeCard, comment: Pick<NodeComment, "text" | "quote" | "where">): string {
  let place = comment.quote === "" ? "" : translate("nodes.comment.at").replace("{0}", () => comment.quote);
  if (comment.where !== "") place += ` (${comment.where})`;
  return translate("nodes.comment.request")
    .replace("{0}", () => card.title)
    .replace("{1}", () => card.id ?? card.key)
    .replace("{2}", () => place)
    .replace("{3}", () => comment.text.trim());
}

/** Send a comment on a node to the assistant, as the reader's own message. Rejects when it could not be sent. */
export async function sendNodeComment(
  card: NodeCard,
  comment: Pick<NodeComment, "text" | "quote" | "where">,
): Promise<void> {
  const session = await fetchLeadSession();
  await sendAgentChatMessage(session.session_id, nodeCommentText(card, comment));
}

/** The start of the sentence that asks for a change to `card`. */
export function changeDraftText(card: NodeCard): string {
  return translate("nodes.ask.change_draft")
    .replace("{0}", () => card.title)
    .replace("{1}", () => card.id ?? card.key);
}

/** Put the caret at the end of the visible chat composer, once it is on screen. */
function focusComposerAtEnd(): void {
  let attempts = 0;
  const tryFocus = () => {
    const field = [...document.querySelectorAll<HTMLElement>("[data-jarvis-chat-input]")].find(
      (node) => node.isContentEditable && node.offsetParent !== null,
    );
    // The draft reaches the field a frame after it mounts; wait for both.
    if (field && (field.textContent ?? "") !== "") {
      field.focus();
      const selection = window.getSelection();
      if (selection) {
        const range = document.createRange();
        range.selectNodeContents(field);
        range.collapse(false);
        selection.removeAllRanges();
        selection.addRange(range);
      }
      return;
    }
    attempts += 1;
    if (attempts < FOCUS_ATTEMPTS) window.requestAnimationFrame(tryFocus);
    else field?.focus();
  };
  window.requestAnimationFrame(tryFocus);
}

/**
 * Open the lead conversation with a draft that names the node, and leave the
 * caret behind it. Nothing is sent.
 */
export async function askDodaiosToChange(card: NodeCard): Promise<void> {
  const chat = useAgentChatStore;
  let sessionId = chat.getState().activeSessionId;
  try {
    const lead = await fetchLeadSession();
    if (lead?.session_id) {
      sessionId = lead.session_id;
      if (chat.getState().activeSessionId !== sessionId) chat.getState().openSession(sessionId);
    }
  } catch {
    // The lead route did not answer: the conversation that is open takes the draft.
  }
  writeComposerDraft(chat, sessionId, { text: changeDraftText(card), choices: [] });
  useHomeStore.getState().openAgentChat(null);
  if (useHomeStore.getState().surface !== "chat") useHomeStore.getState().setSurface("chat");
  useEventStore.getState().setActiveSection("chats");
  focusComposerAtEnd();
}
