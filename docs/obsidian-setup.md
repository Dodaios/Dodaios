# Obsidian Setup

## What this gives you

Dodaios keeps a long-term knowledge wiki on disk as plain
Markdown. Wiring it up with [Obsidian](https://obsidian.md) gives you
a visual memory map of everything Dodaios has remembered, two-way
sync between the Desktop App and your own notes, and the comfort of
opening any of Dodaios's pages in a real editor whenever you want to
read or edit them by hand.

## Quick start

1. Install Obsidian from [obsidian.md/download](https://obsidian.md/download).
   The default installer puts Obsidian into your user profile and
   does not need administrator rights.

   ![Step 1 — Install screen](./images/obsidian-setup-step1.png)

2. Open the Dodaios Desktop App and switch to the **Wiki** tab. Choose
   either an existing Obsidian vault or a separate Dodaios vault. When
   an existing vault is selected, Dodaios stores its pages in a `Jarvis`
   subdirectory. The parent vault remains the registered Obsidian vault;
   Dodaios recognizes the nested directory as connected.

   ![Step 2 — Register vault](./images/obsidian-setup-step2.png)

3. Click **"In Obsidian oeffnen"** (Open in Obsidian)  <!-- i18n-allow --> in the same
   dialog. Dodaios sends the absolute page path to Obsidian, which selects
   the most specific registered parent vault and opens the page. Confirm the
   live test succeeded by clicking **"Hat geklappt"** (It worked) — the  <!-- i18n-allow -->
   wizard then closes for good and never auto-opens again on this
   machine.

   ![Step 3 — Open in Obsidian](./images/obsidian-setup-step3.png)

## Troubleshooting

### "config_missing" — Obsidian not started yet

Obsidian only creates its vault index the first time it launches. It is
stored under `%APPDATA%\obsidian` on Windows, Application Support on
macOS, and the XDG configuration directory on Linux. If the wizard reports
`config_missing`, open
Obsidian once — even just briefly — close it again, then click
**"Jetzt registrieren"** (Register now) in the Dodaios wizard. The
second attempt will find the file and succeed.

### "rolled_back" — write failed and was undone

Dodaios writes the new vault entry through an atomic pipeline: backup
first, then a tempfile, then `os.replace`, then a re-read verification.
If anything in that pipeline fails, the original `obsidian.json` is
restored automatically and the wizard reports `rolled_back`.

If the automatic restore did not put `obsidian.json` back into a
state you trust, open `%APPDATA%\obsidian\` in Windows Explorer and
look for a file named
`obsidian.json.b9-backup-YYYYMMDD-HHMMSS`. Copy that file over the
real `obsidian.json` (Dodaios already did this internally, but the
backup is kept so you can verify by hand or recover from an older
state if needed).

### Vault shows in Obsidian but pages are stale

Press **Ctrl-R** inside Obsidian to force a reload. The Dodaios
Wiki-Watcher keeps the page index live-updated on the Dodaios side,
but Obsidian maintains its own file cache that occasionally lags by
a few seconds — especially right after the WikiCurator adds a new
page during a conversation.

If Dodaios search is stale, use **Rebuild index** in the Wiki health panel
or run `jarvis wiki reindex`. The command rebuilds the derived FTS index
from the configured vault and does not modify Markdown pages.

## Where the vault lives

The vault location is selected during setup and stored in
`memory.wiki.vault_root`. It can be a standalone vault or the `Jarvis`
directory inside an existing Obsidian vault. Any change you make in Obsidian appears inside
the Dodaios Desktop App within seconds (the wiki-watcher monitors
that directory). Conversely, any page Dodaios adds through its
WikiCurator appears in Obsidian on the next file-system poll.

That symmetry is the whole point: one folder, two front-ends,
zero export/import.
