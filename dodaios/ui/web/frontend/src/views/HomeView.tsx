import { lazy, Suspense } from "react";

import { useHomeStore } from "@/store/home";
import { AssistantChat } from "@/components/home/AssistantChat";
import { startNewTextChat } from "@/lib/newChat";

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
 */
export function HomeView() {
  const agentChatId = useHomeStore((s) => s.agentChatId);
  const showPanel = !agentChatId;
  /** From an earlier chat on the stage back to the one conversation. */
  const backToConversation = () => {
    useHomeStore.getState().setSurface("chat");
    startNewTextChat();
  };
  return (
    <div className="flex h-full min-h-0" data-testid="home-view">
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        <AssistantChat />
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
