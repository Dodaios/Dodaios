# Public claims: what to say and what not to say

The checklist for every public text about Dodaios: the README, the website, a
launch post. It belongs to [positioning.md](positioning.md). Checked against
the code on 15 November 2026. Check a number again on the day you use it.

## Three questions a reader asks first

Answer them before they are asked:

1. **"May I use my plan here?"** Dodaios sells no model access and does not
   sign in for the person. It starts each agent's official command-line tool,
   and the person signs in to each one. (GLM Coding Plan runs Claude Code
   against Z.ai.) Say it in those words, and say "plans and keys": Claude Code
   needs a paid Claude plan, and four agents run on keys.
2. **"Is it really local?"** Say what stays on the computer (chats, memory,
   nodes, settings) and what leaves it (what a model or a connected service
   needs for its part of a request). Name the token service the project runs
   for Google, Slack and Figma sign-ins. Never write "nothing leaves" or
   "nothing passes our servers".
3. **"What stops the agent?"** Say that a new chat starts at Bypass
   permissions, where nothing asks, and what the asking modes hold back.

## Do not claim

- That Dodaios is better than a named product, or modelled on one.
- Slack as a chat channel that anybody in a workspace can use. Only the
  owner of the Slack app gets answers, and the person creates that app
  themselves (one click from a manifest, then two keys). Until the first
  recorded take in a real workspace, its checks ran against a stand-in for
  Slack (`tests/fakes/slack_standin.py`); say so if asked.
- Discord as a chat channel. Its direct messages are in the code but have no
  recorded live check; name them only once one exists.
- A native phone app. The phone app is a web app that the desktop serves.
- WhatsApp, or phone calls as a finished feature.
- That all 48 plugins are proven. Two passed a recorded end-to-end run. The
  others carry a Preview badge in the app.
- A full marketplace. Publishing works, and the community catalog is nearly
  empty.
- Office files. Nodes do not import or export Word, PowerPoint or Excel
  files, and a sheet has column formulas, not cell formulas.
- Rituals as a finished feature. In 5.3.3 a spoken or typed phrase starts
  one and the assistant writes them; the panel and the dialog that writes one
  came after that release (#1721).
- That a new chat asks before it acts. The trust layer's hard limits
  (money, credentials, permanent deletion, first contact) ask in every mode
  except Bypass permissions, which a new chat starts in; say so wherever
  the limits are named.
- That macOS and Linux are checked as thoroughly as Windows 11.
- That a model maker approves of its plan being used this way. The person's
  use of each service follows that service's terms.

## Words

- **Dodaios** is the app. **The assistant** is the one you talk to. The person
  names it, and the name is the wake word. The recordings call it Nova. Its
  name when nobody chose one is "Assistant". Never use the name of a
  recording's assistant as a product name.
- **Coding agent** means a command-line coding tool that Dodaios runs, such as
  Claude Code or Codex. Do not call the assistant an agent in the same
  sentence.
- **Node** is a document the assistant made. Say "docs, decks, sheets and
  whiteboards" first, and "node" after that.
- Say what Dodaios is before what it holds ("Dodaios is an open-source
  desktop app"), and the reader's problem before the features. A list of
  features in one sentence is not a definition.
- Keep caveats where a reader looks for them: a short question and answer, or
  the section of the part they belong to. A caveat in every sentence of the
  opening makes the whole text sound unsure.
- Plain words. No "revolutionary", "seamless", "supercharge", "10x". No
  "Jarvis": it is a third party's registered trademark. The one exception is
  the former name, Personal Jarvis, in a rename note.

## Numbers and where they come from

| Number | Source |
| --- | --- |
| Nine coding agents | `dodaios/workspace/agents.py`, `dodaios/agent_chat/catalog.py` |
| 48 plugins | `dodaios/marketplace/seed_catalog.json` |
| Seven kinds of node | `dodaios/nodes/types.py` |
| Four threads side by side | `dodaios/ui/web/frontend/src/store/ideThreads.ts` |
| Team threads of two to eight | `dodaios/agent_chat/team/engine.py` |
| Eleven families of model providers | `pyproject.toml`, the provider entry points |
| Five interface languages | the locale files of the frontend |
| Stars, releases, merged pull requests | the GitHub API, at the time of writing |
