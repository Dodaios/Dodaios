# Risky actions: what asks, in which mode

One table (`dodaios/safety/action_policy.py`) decides which risky actions stop
for the person. The browser, the tool gate and the chat's approval bridge all
read it.

## Severities

| Severity | What | Ask | Accept edits | Auto | Bypass |
|----------|------|-----|--------------|------|--------|
| free | reading, searching, opening pages, filling forms | – | – | – | – |
| ask | send, publish, delete, book, cancel, accept terms | asks | asks | asks | runs |
| confirm | buy, pay, transfer money, type card or bank details, delete the account, grant an app access to the account, wipe a disk or the home folder, read stored passwords | asks | asks | asks | **asks** |
| block | dark web: `.onion`, `.i2p`, Tor and I2P gateways, starting Tor | refused | refused | refused | refused |

A standing "always allow" rule removes `ask` cards, never `confirm` cards.
Nothing the person clicks makes a `block` action run; the agent is told why
and does not try another way.

## Where each one is detected

| Surface | How |
|---------|-----|
| Browser click | the label of the control (`society/browser/commit_gate.py`, English and German) |
| Browser typing | the field's autocomplete, name and label, or 13 to 19 typed digits (`payment_step`) |
| Browser navigation | the destination and the current page's host (`host_risk`) |
| Any tool | `url` arguments, `command` arguments (`shell_risk`), money tools (`trust/hard_limits.py`) via `tool_call_risk` in `RiskTierEvaluator.evaluate` |
| Chat in Bypass | `approval_bridge._decide_inline` asks for `confirm` calls before it answers for the person |

## The browser approval card

The card in the conversation (`ApprovalRequestCard.tsx`) shows:

- a chip: "Needs your OK", or "Always asks" for `confirm` steps, plus the kind of step and the site;
- the question: the exact control, or "May I enter your payment details on …?" (typed values are never quoted);
- a small live picture of the paused browser; a click opens it large;
- **Allow**, **Deny** (also Esc) and **Take over**. Take over ends the agent's turn and hands the page to the person.

The buttons wait 500 ms after the card appears, so a click meant for
something else never answers it. Once answered, the card folds to one line.
A `block` shows a card without buttons that says what was refused and why.

## Changing the rules

- Kinds of committing click: `commit_gate._KINDS`.
- Which kinds always ask: `action_policy.commit_severity`.
- Dark-web hosts: `action_policy._DARK_TLDS`, `_DARK_GATEWAYS`.
- Shell rules: `action_policy._SHELL_RULES`.
