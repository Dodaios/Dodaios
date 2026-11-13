# Voice-First Desktop Assistant Build Plan

## Product goal

Adapt Dodaios into a voice-first desktop assistant with a local Qwen brain, an
ElevenLabs speaking voice, a neural-network-inspired home surface, and bounded
keyboard and mouse control. The assistant should stay out of the way while
another app is in use, remain visible when it is working, and make it easy to
inspect or stop a desktop task.

## Phase sequence

| Phase | Scope | Current state |
|---|---|---|
| 1. Neural home surface | Replace the static orb presentation with a responsive neural visual that reflects assistant activity. | Implemented in the current branch; TypeScript project check passed. Frontend tests and production build are blocked by Windows `EPERM` errors in Vite before tests or bundling begin. |
| 2. Focus-aware desktop behavior | Let the Windows overlay minimize on focus loss, with a user setting to control the behavior. | Implemented in the current branch; runtime verification in the desktop app remains pending. |
| 3. Visible computer-use control | Show recent computer-use runs in Home Activity and offer a per-run Stop control. | Implemented in the current branch; tests are present but Vite fails before executing them. |
| 4. Local brain setup | Connect the installed Ollama runtime and downloaded `qwen3.5:4b`, test it, and assign it to the Brain and relevant local-model roles. | Verified locally: Ollama lists `qwen3.5:4b` (Q4_K_M, tools and vision enabled) and returned the expected response to a local chat request. The Dodaios provider still needs selection and testing from a running app. |
| 5. Voice and wake phrase | Set the assistant name/wake phrase, choose an ElevenLabs voice, and test the full listen-think-speak loop. | Base repo already includes wake-word setup and ElevenLabs TTS. Actual voice selection needs the user's ElevenLabs credentials and a running app. |
| 6. Bounded desktop autonomy | Validate the existing Computer Use path for visible progress, cancellation, and deliberate handling of actions with lasting effects. | Base capability exists; end-to-end validation remains. |
| 7. Preview and release | Build the frontend, verify it in the Dodaios Dev app, then use the repository's PR and CI workflow. | Not started. `gh` is unavailable; the shell push failed because its Git credential helper could not start, and the connected GitHub integration rejected repository writes (403). No PR or Dev preview exists yet. |

## Working constraints

- Keep inference local through Ollama unless a feature explicitly uses a hosted
  service such as ElevenLabs TTS.
- Keep computer control inspectable and cancellable; do not hide ongoing runs.
- Never run this feature branch in the user's main Dodaios app. Use the Dev
  preview path required by the repository after a PR exists.
- A successful TypeScript check is not a production build. Do not call a UI
  change live until the built bundle is visible in the desktop app.
- Current verification evidence: `tsc -b --pretty false` passes; the focused
  Windows focus-watcher tests pass (2 tests); Python byte-compilation and
  `git diff --check` pass. Vitest fails with `EPERM` resolving the selected test
  files before execution; the Vite build fails with `EPERM` resolving
  `src/mobile/main.ts`, before bundling.
