"""What a live voice model knows about the product it runs inside.

A live call asked "what is this thing I downloaded?" and got a generic
"an AI helper for everyday tasks" (2026-10-01): the live instructions said
who the assistant is and nothing about the product. The brief below is the always-on
layer — short and static, so it costs a few hundred tokens and sits in the
provider's cached prompt prefix. Everything deeper (how to set something up,
where a setting lives, what a feature does exactly) stays in the curated
``docs/product/`` guide and is read on demand through ``product_help``.
"""

from __future__ import annotations

PRODUCT_BRIEF = (
    "Product: Dodaios (formerly Personal Jarvis), an open-source agent OS for the user's "
    "desktop (Windows, macOS, Linux); you are its voice, and 'this app' means Dodaios. The "
    "user picks the AI providers: keys, subscriptions or local models. Areas: Chats, Voice, "
    "Agents (background missions), Agentic IDE (coding agents in terminal panes), Computer "
    "Use, Wiki and memory, Skills, Plugins and MCP, Tasks, Outputs, Docs, API Keys, "
    "Settings. Actions carry a risk level (safe, monitor, ask, block); keys go only into API "
    "Keys. Setup and troubleshooting: product_help. Doing what an app screen offers: "
    "find-app-action, then run-app-action."
)
