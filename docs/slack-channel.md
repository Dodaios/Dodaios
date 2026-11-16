# Slack as a conversation channel

The person writes to the assistant in Slack, and the assistant answers there.
A direct message to the person's own Slack app is the same conversation as
the chat on the desktop, the phone app and Telegram. A mention of the app in a
channel is not answered unless the owner turns that on (see "Mentions in a
channel" below).

This is not the Slack plugin. The plugin signs in as the person and lets the
assistant search, read and post with their own permissions. The channel is a
small Slack app of the person's own, with a bot user they can message. Both
can be connected at the same time, and both live on the Slack plugin's page.

## Set it up

On the Slack plugin's page (Plugins → Slack), the card "Chat with the
assistant in Slack" has three steps:

1. **Create the Slack app.** The button opens Slack's "Create app from
   manifest" page with the app filled in: its name (the assistant's name),
   a bot user, the Messages tab open for direct messages, Socket Mode and
   interactivity on, and these bot scopes: `app_mentions:read`, `chat:write`,
   `files:read`, `im:history`, `im:read`, `im:write`, `users:read`. The bot
   listens to `message.im` and `app_mention`. Pick the workspace, click
   Create, then Install to Workspace and Allow. "Copy manifest" copies the
   same manifest as JSON, for "From a manifest" by hand.
2. **Paste the bot token** (`xoxb-…`): OAuth & Permissions → Bot User OAuth
   Token.
3. **Paste the app-level token** (`xapp-…`): Basic Information → App-Level
   Tokens → Generate Token and Scopes, with the scope `connections:write`.
   Slack does not let a manifest create this token, so it is one click more.

Connect checks both keys with Slack before anything is stored: the bot token
with `auth.test`, the app-level token by opening a Socket Mode link
(`apps.connections.open`), and that both belong to the same app. A refused
key, Socket Mode switched off, two keys of two apps, or no network each get
their own message on the card.

Socket Mode means no public address: the computer opens a WebSocket to Slack,
and Slack sends the app's events through it. It works behind any router.

## Who gets answers

Only the owner. The allowlist (`[integrations.slack] allowed_user_ids`, Slack
member ids) starts empty, and an empty allowlist answers nobody.

- If the person's own Slack sign-in (the Slack plugin) is connected in the
  same workspace, the connect knows the owner at once.
- Otherwise the first direct message to the app within ten minutes of the
  connect pairs its sender, and the app answers with one line that says so.
  After those ten minutes an empty allowlist stays closed; "Pair again" on the
  card opens it for another ten minutes ("Change owner" when somebody is
  paired already).

Anyone else who writes to the app, or mentions it, gets nothing back: no
answer and no refusal. Only the owner can press an approval's buttons.

## Mentions in a channel

Off by default. With `[integrations.slack] answer_mentions = true` in the
config file, the owner's mention of the app in a channel is answered in a
thread under the mention. **Everyone in that channel can read the answer**,
and in a channel shared with another company, so can its people. The answer
comes from the owner's private conversation, the same one as the direct
message, so it can carry what the assistant knows about the owner. Leave it
off unless the channel is one only trusted people read.

## What travels

- **Text** both ways, as written: links, code and line breaks stay. Only
  key-shaped text is masked, and Slack's three reserved characters are
  escaped. (The speech filter of the voice is not used: it would turn a link
  into "the website".)
- **Pictures** sent to the app go to the turn as attachments, as from
  Telegram. A picture sent without words waits 25 seconds for the words that
  follow it. The messages of one conversation are handled in the order they
  were sent, so a question typed right after a picture joins it even while
  the picture is still downloading.
- **Voice clips** recorded in Slack are transcribed like a Telegram voice
  note.
- **Approvals.** A tool call that waits for a yes also arrives in the direct
  message with Allow and Deny buttons. The command or the changed lines stand
  in a code block exactly as they will run. A decision in the app settles
  the Slack message, also when it comes while the message is still on its
  way; a button shrinks the message to its first line and the decision. Settings → Notifications → "Approvals in Slack" switches
  this off. A plain "yes" or "no" typed in Slack answers the oldest open
  approval too.
- **"Stop"** typed in Slack stops everything, as from any of the owner's
  chats.

The answer the owner reads in Slack is the short phone copy; the full answer
stays in the conversation in the app.

## Keys and logs

The two keys are stored in the Credential Manager (`slack_bot_token`,
`slack_app_token`; `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in the environment
for a headless server), never in `jarvis.toml`. Every Web API call sends a key
in the `Authorization` header, never in a URL. The log filter masks Slack key
shapes (`xoxb-`, `xapp-`, ...) and the Socket Mode link's ticket, and the
channel strips both keys from every error text it keeps. Files of a message
are fetched with the bot key only from Slack's own file hosts.

Disconnect removes both keys, the owner and the switch.

## Restart and reconnect

- **At start.** No network yet (the app starts at login) is a passing failure:
  the channel manager tries again after growing waits, and the chat bridge
  binds to the channel once it is up (the same retry as Telegram's). A
  refused key, a missing key or Socket Mode off is lasting and is not tried
  again; the card says why.
- **While running.** Slack refreshes a link every few hours (`disconnect` with
  `refresh_requested`, or `warning` shortly before). The channel opens a new
  link at once. A link that drops without a word (a network change, a Mac
  waking from sleep) is found by the WebSocket ping and replaced; while Slack
  is unreachable the channel tries again after 1, 2, 5, 10, 30 and then every
  60 seconds. If Socket Mode is switched off for the app (`link_disabled`) or
  the app-level key is revoked, the link ends for good and the card shows it.
- Slack sends an event again when its acknowledgement was late. Every
  envelope is acknowledged before it is handled, and a message seen once is
  not handled twice.

A second instance of the app (the Dev app) starts no chat channels, so it
never answers on the person's Slack app.

## Where it lives

| What | Where |
| --- | --- |
| The channel | `dodaios/channels/slack.py` |
| Web API calls, manifest, key check | `dodaios/channels/slack_api.py` |
| Setup routes (`/api/channels/slack`) | `dodaios/ui/web/slack_channel_routes.py` |
| Settings card | `dodaios/ui/web/frontend/src/views/plugins/SlackChatCard.tsx` |
| Approval buttons | `dodaios/channels/telegram_approvals.py` (`source="slack"`) |
| Into the lead conversation | `dodaios/channels/chat_bridge.py` (`slack_owner`) |
| Front page button | `dodaios/agent_chat/reach.py` (a chat once the app runs) |
| Stand-in for Slack in tests | `tests/fakes/slack_standin.py` |
| Tests | `tests/unit/channels/test_slack_channel.py` |

The tests run the real channel over the network against the stand-in, which
serves the Web API over HTTP and the Socket Mode link over a WebSocket, with
the envelope and method shapes of Slack's documentation.
