# The Connect card in a chat

When a task needs a service that is not connected (Gmail, Google Calendar,
Slack, a command-line tool), the chat shows a small card: the service's logo,
"Connect Gmail", one quiet line and a Connect button. The button runs the same
sign-in as the Plugins and CLIs pages. Nobody is sent to another page.

## When it appears

| Trigger | Where |
|---------|-------|
| A marketplace plugin's tool fails because the plugin is not connected, or its sign-in ended | Every attended chat: the assistant's conversation, an agent's chat, a coding thread |
| The agent calls `society_request_connect` (kind `plugin` or `cli`) | The assistant's conversation and agents' chats |

The first row needs nothing from the model. Every tool call of a chat passes
the `ToolExecutor`; a failed call whose error names the missing connection is
checked against the real connection state, and when the plugin is not usable
the card opens in that chat (`dodaios/society/connect_offer.py`). The model
reads what the person now sees and ends its reply with one sentence. A spoken
call, a routine and a task agent have nobody at a chat: they keep the tool's
own error.

A turn shows at most three cards. A service asked for again in a later turn
gets its card under that turn; the earlier one closes (`superseded`).

## After Connect

The card watches the sign-in and reports it. The backend checks that the
connection really exists before the card closes
(`connect_save` in `dodaios/society/connect_tool.py`).

Then the chat continues the request by itself, in a turn of its own
(`dodaios/agent_chat/connect_resume.py`). The chat shows only that turn's
answer: no bubble and no small-print line repeat the request. It starts once the chat's seat is
free: after the turn that showed the card, and after anything the person
started meanwhile. "Not now" closes the card and continues nothing.

The card stays open across turns and an app restart, in every chat.

## Why the turn ends on one sentence

Two automatic continuations send an agent back to work: the recovery after a
failed tool call and the guard against an offer where action was asked for.
With the card on screen the next step is the person's, so the card's tool
result counts as a blocker neither of them acts on
(`dodaios/agent_chat/task_recovery.py`).
