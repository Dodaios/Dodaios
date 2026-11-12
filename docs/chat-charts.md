# Charts in a chat answer

When an answer rests on a series of numbers (a price over a month, a forecast,
amounts compared across several things), the assistant can add one small chart
to it. The chat draws the chart as a card in the app's own look, in both
themes; hovering reads the values, and a Table switch shows every number.

## The block

The assistant writes the chart as a fenced code block with the language
`chart` that holds one JSON object:

````
```chart
{"type": "line", "title": "ACME share price", "unit": "USD",
 "note": "daily close, 1 to 3 June", "value": "142.30 USD", "delta": "+2.1 % in 3 days",
 "x": ["1 Jun", "2 Jun", "3 Jun"],
 "series": [{"name": "ACME", "data": [139.4, 140.1, 142.3]}]}
```
````

| Field | Meaning |
|-------|---------|
| `type` | `line` or `area` (a trend over time), `column` (amounts per period), `bar` (named things compared, one row each). Default `line`. |
| `x` | The labels, 2 to 366 (`bar`: at most 24). |
| `series` | 1 to 6 entries of `{"name", "data"}`. Every `data` list is as long as `x`; `null` is a gap. One list `data` or `values` on the object itself is a single series. |
| `title`, `note`, `unit` | Optional. The unit is written beside every value. |
| `value`, `delta` | Optional headline figure and its change, as text. |

A block that does not hold a drawable chart (numbers that do not line up with
the labels, an unknown type, more than six series) stays an ordinary code
block. Nothing is drawn from numbers that do not fit.

## Where it is drawn

| Surface | Result |
|---------|--------|
| The assistant's conversation, coding threads, agent chats | The chart card. In the assistant's conversation it is a message of its own. |
| A report page or Markdown file in Artifacts | The chart card. |
| A phone chat (Telegram, Discord, WhatsApp) | The block is left out; the text stands without it. |
| Voice | The assistant is told not to write one. |

## What the assistant is told

`CHART_GUIDANCE` in `dodaios/core/response_style.py` is part of the
assistant's own chat prompt on both seats (the CLI seat's preamble and the
brain's written style). It says when a chart fits, gives the format, and sets
two rules: every number comes from a tool result or from the person, and the
text must make sense without the chart. A single number gets no chart.

## Code

| Part | File |
|------|------|
| Reading the block, number formats | `dodaios/ui/web/frontend/src/lib/chartSpec.ts` |
| The card | `dodaios/ui/web/frontend/src/components/outputs/ChartFence.tsx` |
| Chat and report wiring | `components/agentchat/ChatMarkdown.tsx`, `components/agentchat/LeadReply.tsx`, `components/outputs/MarkdownProse.tsx` |
| Prompt text, removal for surfaces that cannot draw | `dodaios/core/response_style.py` (`CHART_GUIDANCE`, `without_charts`) |
| Phone copy | `dodaios/channels/output_contract.py` |

The six series colours are fixed and in a fixed order that keeps neighbours
apart for colour-blind readers. Three of the light-theme colours have less
than 3:1 contrast on a white card, which is why the Table view is always
present.
