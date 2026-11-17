import { lazy, Suspense, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useAgentChatStore } from "@/store/agentChat";
import { useHomeStore } from "@/store/home";
import { useNodePeek } from "@/store/nodePeek";
import { moveKeepingPlace } from "@/components/nodes/peek/moveKeepingPlace";
import { AssistantChat } from "@/components/home/AssistantChat";
import { startNewTextChat } from "@/lib/newChat";
import { useAgentBrowserStaged } from "@/components/home/chatBrowser/slot";

// Not needed for first paint.
// Who the assistant is and what belongs to it; reads its routines, files and skills.
const AssistantPanel = lazy(() => import("@/components/home/AssistantPanel"));

/**
 * The front page — the "chats" section.
 *
 * ONE endless conversation with the assistant, with a voice mode inside it
 * (components/home/AssistantChat), and on wide windows one panel on the
 * right. It is the assistant's own panel: its face, what it is doing right
 * now, the ways to reach it, its computers, the chats it handed a task to
 * and the files it made (components/home/AssistantPanel). A running call
 * shows as a card over the conversation.
 *
 * The conversation is drawn into an element of its own, which stands in its
 * column here and is offered to the node window (`lender` in
 * store/nodePeek). When a node is opened from the conversation, the window
 * moves that element beside the node, as it is: nothing is drawn twice, so
 * the window is there at the click however long the conversation is. The
 * window puts it back when it closes.
 */
export function HomeView() {
  const agentChatId = useHomeStore((s) => s.agentChatId);
  // The assistant's browser stage, opened large, takes the panel's place.
  const browserStaged = useAgentBrowserStaged();
  const showPanel = !agentChatId && !browserStaged;

  /* The conversation's own element. Made once; React draws into it through a
   * portal, so moving it in the page moves the conversation and keeps every
   * state in it (what is typed, a running call, where the reader is). */
  const conversation = useMemo(() => {
    const element = document.createElement("div");
    element.className = "relative flex min-h-0 min-w-0 flex-1 flex-col";
    element.dataset.testid = "home-conversation";
    return element;
  }, []);
  const home = useRef<HTMLDivElement>(null);
  /* Whether the element is in the page yet. The conversation is drawn into it
   * only from then on: drawn into an element that is not in the page, it has
   * no height, so its first move to the end went nowhere and the next look
   * at the view found it at the top and stopped following. The page opened
   * at the first message after every restart and every return from another
   * section (2026-11-16). The flag is set before the first paint, so nothing
   * is seen without the conversation. */
  const [placed, setPlaced] = useState(false);
  /* Only the one conversation with the assistant is lent: an agent's own chat
   * reads another store, and the chat beside its browser is two columns. */
  const lendable = showPanel;
  const setLender = useNodePeek((s) => s.setLender);
  // Into its column once; from then on only the window moves it, and back.
  useLayoutEffect(() => {
    if (home.current) home.current.appendChild(conversation);
    setPlaced(true);
    return () => conversation.remove();
  }, [conversation]);
  useLayoutEffect(() => {
    const column = home.current;
    if (!lendable || !column) return;
    setLender({ chat: useAgentChatStore, element: conversation, home: column });
    return () => {
      setLender(null);
      // No longer on offer (an agent's chat took the column, the page is
      // leaving): the conversation is here again before anything else is drawn.
      moveKeepingPlace(conversation, column);
    };
  }, [conversation, lendable, setLender]);
  /** From an earlier chat on the stage back to the one conversation. */
  const backToConversation = () => {
    useHomeStore.getState().setSurface("chat");
    startNewTextChat();
  };
  return (
    <div className="flex h-full min-h-0" data-testid="home-view">
      <div ref={home} className="relative flex min-h-0 min-w-0 flex-1 flex-col" data-testid="home-conversation-column">
        {placed && createPortal(<AssistantChat />, conversation)}
      </div>
      {showPanel && (
        <div data-testid="assistant-panel-frame" className="hidden lg:flex">
          <Suspense fallback={null}>
            <AssistantPanel onConversation={backToConversation} />
          </Suspense>
        </div>
      )}
    </div>
  );
}
