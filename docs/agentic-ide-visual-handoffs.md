# Visual references in coding work orders

`workspace-orchestrate` accepts `image_refs` on `create`, `open_workspace`
and `send`. These are opaque IDs from the current conversation, not paths,
URLs, or descriptions. Select the images used by the particular assignment.
An explicit empty list means the assignment does not use images. When usable
images exist and the field is omitted, the tool requests a selection before
creating a pane or sending a task. No global latest-appshot lookup is used.

## Sources and authorization

- `take_appshot` returns its filtered pixels, an image ID, and handoff guidance.
  The regular tool loop and Live both deliver pixels as image input rather
  than serializing them as tool-result text.
- Images on the current brain request receive IDs before tool routing.
- A Dodaios chat upload registers the images selected on that message. Paths
  must resolve inside that chat's working folder. Missing, oversized,
  unsupported or escaped files produce an unavailable notice.
- A chat upload keeps its ID for later messages of the same conversation: the
  person often shows a screenshot, talks it through, and confirms the work
  order a message later. The ID is derived from the conversation and the file,
  so it is the same when a later message registers the picture again. Every
  message to the Dodaios chat re-registers the pictures of its last 24 hours
  (at most 20, listed as `visual_references` on their `user_message` events)
  under the same folder checks, which also brings them back after an app
  restart emptied the store. The bytes stay in RAM only for the first 120
  seconds; afterwards a handoff reads the file again and refuses it when it was
  deleted or its SHA-256 no longer matches. Only the current message's pictures
  make a work order without `image_refs` ask for a selection; earlier ones are
  listed in that answer but block nothing.
- Appshots attached directly to a live call belong to that call's scope, in
  every live mode (backend thinking, native, and subscription). The ID rides
  beside the pixels wherever the call keeps them in model context, including
  a capture's retained snapshot after its tool output left the history.
  Chat, live-call and ordinary conversation scopes cannot resolve each other's
  IDs. A live-call reference lives as long as the call keeps the picture in
  context: closing the call clears it, and a one-hour bound expires a scope
  whose call never closed. Other captures retain their configured TTL; other
  temporary references (except chat uploads, above) expire after 120 seconds. One active timer removes
  expired bytes even when there are no later calls.

The existing ToolExecutor authorization, capture denylist/redaction, coding
pane permissions and prompt readiness checks remain in force. Pixels are
untrusted reference data. The assistant must not derive permission from text
inside them. A requested image-based coding handoff authorizes copying the
selected images to that coding workspace; taking a screenshot alone does not.

## Delivery and retention

Before typing the task, the coding gateway validates the image and copies the
actual bytes to `.jarvis/visual-references` inside the pane's working folder
(including a pane-specific worktree). It writes an ignore file, refuses
redirected directories, verifies the copied bytes, and includes the readable
absolute path in the CLI prompt using the CLI registry's file-reference syntax.
The prompt tells the agent to open every image and report an inability to view
it. No provider-specific clipboard or undocumented image flag is required.

For a pane on a connected computer, the copy uses that computer's existing
authenticated SFTP connection and remote working folder. It verifies the
remote bytes before sending the remote path. A failed transfer never falls back
to a local path or a description. Moving a pane during transfer/readiness
invalidates delivery. Long prompts that would truncate an image path are refused.

These explicit task attachments are separate from transient Screen Context:
copies survive a source expiry, process restart and ordinary session resume.
They are eligible for deletion after seven days; a later handoff sweeps expired
copies. This is not a promise of timed deletion from disk. Users can delete the
copies earlier, in which case the coding agent must report a missing file.
There is no extra local disk copy for a remote handoff. File permissions restrict
copies on systems that enforce POSIX permissions; Windows retains the workspace's
ACL boundary.

Receipts include the selected ID, destination path/computer, byte count, SHA-256,
and copy retention period. `accepted` proves CLI prompt submission and verified
file availability at handoff, not that a model opened the image or finished the
task. Refused/uncertain submission must never be reported as completed.
Image selection and conversation scope are part of the durable delivery claim;
retries cannot silently replace or duplicate an attachment.

## Verification

`tests/contract/test_coding_image_handoff.py` exercises upload, appshot-tool and
live-call appshot sources with new/existing sessions through the real workspace orchestrator, coding
gateway and registry into a fake PTY. It opens the delivered PNG, compares bytes,
checks the typed file path, receipt and retry behavior, and covers multiple images,
unrelated images, expiry, conversation isolation, invalid images, path traversal,
prompt truncation, pane-specific worktrees and moving destinations, and a chat
picture that goes with a work order confirmed half an hour later, also after a
restart, or is refused once its file changed or was deleted. SFTP tests
exercise verified transfers and corrupt-read refusals using an isolated transport
and a real in-process SSH/SFTP server bound to loopback.

These tests do not spend a provider key, capture the user's real screen, connect
to a user's remote host, or prove that an actual vendor model used its image tool.

## Implementation map

| Area | Files |
| --- | --- |
| Scoped references and expiry | `dodaios/core/image_references.py` |
| Upload intake | `dodaios/agent_chat/attachments.py`, `service.py` |
| Conversation and tool routing | `dodaios/brain/manager.py`, `dispatcher.py`, `tool_use_loop.py`, `workspace_tool.py` |
| Captures and live calls | `dodaios/plugins/tool/appshot.py`, `dodaios/live/tools.py`, `session.py`, `native.py`, `subscription.py` |
| Work order and CLI delivery | `dodaios/agentic_ide/orchestration.py`, `control.py`, `session.py`, `visual_handoff.py` |
| Regression evidence | `tests/contract/test_coding_image_handoff.py`, `tests/fakes/fake_visual_sftp.py`, `tests/unit/appshot/test_appshot_surfaces.py`, `tests/unit/live/test_subscription_session.py` |
