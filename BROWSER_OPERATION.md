# Browser Operation Guide

This CLI drives Gemini through a real Camoufox browser session. All commands are
run via `geminiwebapp-cli`.

## General Rules

- Always use `--json` to get structured, parseable output for agent workflows.
- Use `--session <name>` to target a specific session profile; the default is `default`.
- `.env` in the current working directory is loaded automatically, but existing shell/system env vars take precedence.
- Run `<command> --help` to get current usage, flags, and defaults.
- Expect occasional maintenance because Gemini's web UI is not a stable API.

## Authentication

Sessions start unauthenticated. The CLI never handles credentials; login is done
manually in the browser window.

1. Check state: `geminiwebapp-cli auth status --json`
2. If login is needed: `geminiwebapp-cli login --interactive --wait --timeout 300`
3. Complete login manually in the browser; the command exits automatically.

## Chat Usage

```bash
geminiwebapp-cli chats new --text "Hello" --json
geminiwebapp-cli chats new --input-file prompt.md --json
geminiwebapp-cli chats new --text "Analyze this" --file report.pdf --json
geminiwebapp-cli chats new --text "Create a watercolor cat" --tool create-image --json
geminiwebapp-cli chats new --text "Create a watercolor cat" --tool create-image --dry-run --json
geminiwebapp-cli chats new --text "Create a 5 second video of a paper airplane gliding across a desk" --tool create-video --aspect-ratio landscape --timeout 900 --json
geminiwebapp-cli chats new --text "Research this" --tool deep-research --json
geminiwebapp-cli chats new --text "Research this" --tool deep-research --model pro --json
geminiwebapp-cli chats new --text "Research this" --tool deep-research --wait --json
geminiwebapp-cli chats list --json
geminiwebapp-cli chats tools --json
geminiwebapp-cli chats read 1 --json
geminiwebapp-cli chats research 1 --json
geminiwebapp-cli chats research 1 --wait --timeout 900 --json
geminiwebapp-cli chats images 1 --json
geminiwebapp-cli chats videos 1 --json
geminiwebapp-cli chats music 1 --json
geminiwebapp-cli chats send 1 --text "Follow up" --json
geminiwebapp-cli session stop
```

`<chat>` may be a Gemini URL, an `/app/...` path, a chat id, or a 1-based index
from the visible sidebar list.

Use `--input-file FILE` instead of `--text` for long prompts. The CLI reads the
file before dispatching to the background worker, so relative paths are resolved
from the directory where you ran the command.

Use `--dry-run` to exercise the browser flow without submitting the prompt. It
opens the composer/chat, selects model/tool options, uploads files, and selects
video aspect ratio, then returns before generation starts. Live smoke tests use
dry-run by default to avoid consuming generation quota.

Use `--file FILE` to upload local attachments through Gemini's `+` menu before
sending. Use `--tool create-image`, `--tool create-video`, `--tool deep-research`,
or `--tool create-music` to select the matching `+` menu tool. Use
`chats tools --json` to discover visible `+` menu labels, then use
`--plus-option "Visible menu label"` for newly added Gemini menu items.
When `--tool create-image`, `--tool create-video`, or `--tool create-music` is
used, generated media is saved to the current directory. Add `--output-dir DIR`
to save it somewhere else. For video, add `--aspect-ratio landscape` for 16:9 or
`--aspect-ratio portrait` for 9:16. Video and music generation usually need a
longer timeout, for example `--timeout 900`.
Music downloads choose Gemini's `Audio only` option from the `Download track`
submenu.
Use `--model flash-lite`, `--model flash`, or `--model pro` to select the model.
Deep Research auto-selects Flash when no model is provided because Flash-Lite
does not expose the Deep Research tool.
For Deep Research, the CLI clicks `Start research` after Gemini shows the plan
and returns once research is in progress. Add `--wait` or `--wait-research-complete` to wait
for the final report and include report text and sources in JSON output. Use
`chats read <chat> --json` later to retrieve a completed report from an existing
Deep Research chat.
Completed report content is stored at `research.report.text`; `research.text` is
a short status summary.
Deep Research wait mode defaults to 900 seconds when `--timeout` is omitted;
normal chat response waits default to 180 seconds.
Use `chats research <chat> --json` to poll an existing Deep Research chat. It
returns `research.status: in_progress`, `completed`, or `not_found`. Add
`--wait --timeout SECONDS` to wait for completion.

Use `chats images <chat> --json` to save visible generated images from an
existing chat into the current directory. Add `--output-dir DIR` to save them
somewhere else.

Use `chats videos <chat> --json` to save visible generated videos from an
existing chat into the current directory. Add `--output-dir DIR` to save them
somewhere else.

Use `chats music <chat> --json` to save visible generated music from an existing
chat into the current directory. Add `--output-dir DIR` to save it somewhere
else.

Use `session stop` to close the background browser worker without deleting the
saved login state. Use `session clear` only when you want to delete the profile.

## Error Conventions

JSON errors include `ok: false` and an `error.type` field. When the error type is
`interactive_authentication_required`, run the `next_command` value and complete
manual login in the opened browser.

Visible Gemini media-generation failures are reported inside the successful chat
result instead of as transport errors. In JSON, check `response.done`; when it is
`false`, `response.error.type` may be `generation_failed` and
`response.error.message` contains Gemini's visible failure text.
