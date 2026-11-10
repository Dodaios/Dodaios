---
title: "Memory"
slug: wiki-and-memory
summary: "Understand what Dodaios remembers about you, how it uses that memory in each conversation, and how to correct, forget or export it."
section: "Knowledge and sharing"
section_order: 4
order: 1
diataxis: explanation
status: active
owner: maintainers
last_reviewed: 2026-11-09
phase: "-"
audience: end-user
tags: [memory, context, profile, privacy, export]
related: [profile-and-contacts, jarvis-agents, privacy-and-local-data]
---

Dodaios keeps a personal memory: short sentences about you and your world,
such as where you live, how you like answers, the people you mention and the
projects you are working on. It lives in one file on your computer,
`data/memory/vault.db`, and you can read, correct, forget or export every
entry in the **Memory** section.

## What reaches the assistant

Dodaios does not load your whole memory into every conversation.

| Layer | What it holds | When the assistant sees it |
|---|---|---|
| **Always in mind** | Pinned memories, who you are, your preferences, standing instructions, the people and projects that matter | In every chat and voice conversation; it is kept small (about 600 tokens) |
| **Looked up** | Everything else: moments, older facts, private entries | Only when your message matches it, or when the assistant searches its memory to answer you |

The Memory section shows the exact always-in-mind text under **How it
works**, with a meter for how full it is. A compass mark on a memory means it
is always in mind.

## How memories are made

- **You say it.** "Remember that I prefer short answers" is saved at once, in
  your words.
- **It is learned.** After a conversation, one background pass compares what
  you said with what is stored. It can add a memory, replace one that changed
  ("I live in Berlin now"), or mark one as no longer true. Each change must be
  grounded in something you actually said.
- **You add it.** Use **New** in the Memory section.

Secrets such as API keys or passwords are never stored. Health, religion,
politics and similar topics are only kept when you ask, and then as private
entries that never sit in the always-on layer.

## History instead of overwriting

When something changes, the old memory is closed with a date instead of being
deleted, so the assistant knows both how things are now and how they were
before. Open a memory to see its timeline. **No longer true** ends a memory
without a replacement.

## Forget

**Forget** erases a memory and every earlier version of it. Dodaios will not
learn it again on its own; only you can save it again.

## Export and import

Your memory is yours to take along:

- **Export memory (.zip)** writes a complete, re-importable bundle (one JSON
  line per memory, an audit log, the list of forgotten entries and checksums).
- **Export as Markdown** writes readable files, one per kind of memory. The
  **Files** view in the Memory section shows the same files.
- **Import a memory file** reads such a bundle back. Importing the same bundle
  twice changes nothing, and anything you had forgotten stays forgotten.

## Earlier versions

Before November 2026 Dodaios kept a Markdown wiki vault (optionally opened in
Obsidian). On first start the new memory copied the useful facts from it once;
the old folder is left on disk untouched and is no longer read or written.

## How It Fits Together

- **Chat and voice** read the same memory, so something said on a call is
  known in the next typed message.
- **Agents** see only your preferences and standing instructions, never your
  profile, people or private entries, and they cannot change your memory.
- **Profile and Contacts** stay separate: the Profile keeps settings about
  you, Contacts keep phone numbers and addresses. Memory keeps sentences.
- **Calendar**, when connected, adds the next two weeks of appointments as
  short-lived memories that disappear after the event.

## Check That It Works

1. Say or type "Remember that I prefer short answers."
2. Open **Memory**: the sentence appears under **Preferences**, marked
   *You said*, with a compass when it is always in mind.
3. Ask a new question; the answer follows the preference.

## Troubleshooting

- **A memory is wrong.** Open it and choose **Edit**; the old version stays in
  its timeline.
- **The assistant keeps learning something you do not want kept.** Choose
  **Forget**; it will not be learned again on its own. To stop learning for a
  while, use **Pause learning** in the Memory sidebar.
- **"Memory is not running."** Restart the app; the memory file is
  `data/memory/vault.db` and opens on start.

## Next Steps

- Review your profile and people in [Profile and Contacts](profile-and-contacts).
- See what stays on your computer in [Privacy and Local Data](privacy-and-local-data).
