import "./leadConversation.css";

/**
 * The assistant is working on its next message: three dots in a bubble of
 * its own, the way a messenger shows that someone is typing (maintainer,
 * 2026-11-12). It stands where the next message will, as tall as a
 * one-line message, so the message that replaces it moves nothing. The dots
 * are drawing only: the state is said beside it for assistive technology.
 */
export function TypingBubble() {
  return (
    <div className="lead-bubble lead-typing jarvis-chat-in" data-testid="typing-indicator" aria-hidden>
      <span /><span /><span />
    </div>
  );
}
