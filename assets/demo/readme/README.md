# README demo videos

The README shows four short, real recordings of the app. GitHub plays a video
inline only when it is a user attachment, so the files are uploaded to a GitHub
comment and the README links their `user-attachments` URLs. They are not stored
in the repository.

| Where in the README | Shows |
|---|---|
| Top | 24 s: the strongest moments of the Agentic IDE and Agents recordings |
| Code by talking | 53 s with sound: the maintainer asks by voice for a new Claude Code session, which starts working. It is a cut of the original recording from the October 2026 README, made before the rename, so the app and the voice still say Personal Jarvis and some panes show German text. The cut leaves out the parts with personal details and an error message. |
| Run every coding agent at once | 38 s: three coding agents in panes, the Git panel and the browser preview |
| A team of agents | 35 s: a new agent gets a research job, writes a brief and sets up a routine |

## Requirements for a new recording

- The real app, recorded from an isolated demo instance. No mock-ups, no
  motion-graphics montage, no text overlays.
- H.264 MP4, 1920 x 1080, 60 fps, at most 10 MB (GitHub's limit for inline
  video), first frame shows the app.
- Nothing private on screen: no real names, email addresses, account ids or keys,
  no error output and no warning cards. The Code by talking cut is the one
  exception kept by the maintainer's choice: it is an older real recording.

To replace one, upload the MP4 in a comment on an issue or pull request and post
the comment (an attachment in an unposted comment stays private), then put the
new URL on its own line in `README.md` and `README.zh-CN.md`.
