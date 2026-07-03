# geminiwebapp-cli

Drive Gemini from the command line through a real Camoufox browser session.

This is a personal automation CLI for `https://gemini.google.com`. It uses a
persistent local browser profile, short commands, optional JSON output, and no
API key.

The CLI never handles Google credentials. Login is completed manually in the
opened Camoufox browser and then reused from the saved browser profile.

## Install

```bash
uv sync
uv run python -m camoufox fetch
```

## Docker Install

```bash
python -m pip install "git+https://github.com/darwincr/geminiwebapp-cli.git@main"
python -m camoufox fetch
geminiwebapp-cli --help
```

## Quickstart

```bash
uv run geminiwebapp-cli auth status --json
uv run geminiwebapp-cli login --interactive --wait --timeout 300
uv run geminiwebapp-cli chats new --text "Write a concise haiku about terminals" --json
uv run geminiwebapp-cli chats new --input-file prompt.md --json
uv run geminiwebapp-cli chats new --text "Analyze this" --file report.pdf --json
uv run geminiwebapp-cli chats new --text "Create a watercolor cat" --tool create-image --json
uv run geminiwebapp-cli chats new --text "Create a watercolor cat" --tool create-image --dry-run --json
uv run geminiwebapp-cli chats new --text "Create a 5 second video of a paper airplane gliding across a desk" --tool create-video --aspect-ratio landscape --timeout 900 --json
uv run geminiwebapp-cli chats new --text "Research this" --tool deep-research --json
uv run geminiwebapp-cli chats new --text "Research this" --tool deep-research --model pro --json
uv run geminiwebapp-cli chats new --text "Research this" --tool deep-research --wait --json
uv run geminiwebapp-cli chats list --json
uv run geminiwebapp-cli chats tools --json
uv run geminiwebapp-cli chats read 1 --json
uv run geminiwebapp-cli chats status 1 --json
uv run geminiwebapp-cli chats research 1 --json
uv run geminiwebapp-cli chats research 1 --wait --timeout 900 --poll-interval 30 --json
uv run geminiwebapp-cli chats research 1 --wait --timeout 1800 --json
uv run geminiwebapp-cli chats images 1 --json
uv run geminiwebapp-cli chats videos 1 --json
uv run geminiwebapp-cli chats music 1 --json
uv run geminiwebapp-cli chats send 1 --text "Make it funnier" --json
uv run geminiwebapp-cli session stop
```

Use `--session work` or `$GEMINIWEBAPP_CLI_SESSION` to keep separate browser
profiles. Profiles are stored in `~/.geminiwebapp-cli/profiles/<session>` unless
`$GEMINIWEBAPP_CLI_HOME` is set.

Commands reuse a per-session background Camoufox worker by default. The first
command for a session starts the browser, later commands connect to the same
browser instance, and rapid sequential commands are queued through one local
socket so only one action touches the session at a time. The worker exits after
being idle for a while; the next command starts it again using the same
persistent profile.

Run `session stop` when you want to close the background worker without deleting
login state. Run `session clear` only when you want to delete the saved profile.

## Commands

`--session <name>` and `--json` work on every command.

| Command | What it does |
|---|---|
| `login` | Verify the current Gemini session; reports `interactive_authentication_required` if sign-in is needed. |
| `login --interactive` | Open Gemini and keep the browser alive while you log in manually. |
| `login --interactive --wait --timeout 300` | Open Gemini, wait for manual login completion, then exit automatically. |
| `auth status` | Report whether the current session is authenticated. |
| `auth interactive` | Open Gemini and keep the browser alive while you log in manually. |
| `chats list` | List visible recent chats from the sidebar. |
| `chats tools` | Open Gemini's `+` menu and list visible options for `--tool` and `--plus-option`. |
| `chats new --text TEXT` | Open the Gemini `/app` composer, type a prompt, submit it, wait for Gemini to finish, and print the response. |
| `chats new --input-file FILE` | Open the Gemini `/app` composer using prompt text read from a UTF-8 file. |
| `chats new --file FILE --text TEXT` | Upload a local file through the Gemini `+` menu before submitting the prompt. Repeat `--file` for multiple files. |
| `chats new --dry-run --text TEXT` | Perform setup steps, including tool selection, file upload, and video aspect-ratio selection, then stop before submitting. Useful for live smoke tests. |
| `chats new --tool create-image --text TEXT` | Create an image and save visible generated images to the current directory. Use `--output-dir DIR` to choose another location. |
| `chats new --tool create-video --aspect-ratio landscape --text TEXT --timeout 900` | Create a video and save generated videos to the current directory. Use `--aspect-ratio portrait` for 9:16 or `--aspect-ratio landscape` for 16:9. Use `--output-dir DIR` to choose another location. Video generation usually needs a longer timeout. |
| `chats new --tool create-music --text TEXT --timeout 900` | Create music and save generated audio to the current directory. Use `--output-dir DIR` to choose another location. Music generation may need a longer timeout. |
| `chats new --tool deep-research --text TEXT` | Start Deep Research, confirm Gemini's plan, and return `response.research.status: in_progress` with the chat URL. Supported tools: `create-image`, `create-video`, `deep-research`, `create-music`. |
| `chats new --tool deep-research --wait --text TEXT` | Start Deep Research, wait for completion, and return `response.research.report.text` plus `response.research.sources`. Defaults to 900 seconds unless `--timeout` is provided. `--wait-research-complete` is also supported. |
| `chats send <chat> --text TEXT` | Open an existing chat and send a follow-up prompt. |
| `chats send <chat> --input-file FILE` | Open an existing chat and send a follow-up prompt from a UTF-8 file. |
| `chats send <chat> --file FILE --text TEXT` | Upload a local file to an existing chat before submitting the prompt. |
| `chats continue <chat> --text TEXT` | Alias for `chats send`. |
| `chats read <chat>` | Open a chat and extract visible message history. |
| `chats status <chat>` | Open a chat and auto-detect whether it is a Deep Research chat or a normal chat. Deep Research results include `type: deep_research` and `research.status`. |
| `chats research <chat>` | Open an existing Deep Research chat and return `research.status` as `in_progress`, `completed`, or `not_found`. |
| `chats research <chat> --wait --timeout 900 --poll-interval 30` | Wait for an existing Deep Research report to complete and return `research.report.text` plus `research.sources`. |
| `chats images <chat>` | Open an existing chat and save visible generated images to the current directory. Use `--output-dir DIR` to choose another location. |
| `chats videos <chat>` | Open an existing chat and save visible generated videos to the current directory. Use `--output-dir DIR` to choose another location. |
| `chats music <chat>` | Open an existing chat and save visible generated music to the current directory. Use `--output-dir DIR` to choose another location. |
| `session stop` | Stop the background worker without deleting the saved browser profile. |
| `session clear` | Delete the local browser profile for the session, including saved Google login state. |

`<chat>` can be a full Gemini URL, an `/app/...` path, a Gemini chat id, or a
1-based index from the currently visible sidebar list.

`chats new` intentionally navigates directly to `https://gemini.google.com/app`
instead of clicking the visible New chat link, because Gemini's New chat control
points to the same route. Once the composer is ready, the CLI types into the
focused input, waits briefly, and submits with Enter.

## Output

By default, chat commands print the Gemini response text. Add `--json` to get a
structured result with fields such as `ok`, `chat`, `prompt`, and `response`.
Errors emitted with `--json` include `ok: false` and `error.type`.
If Gemini visibly fails media generation, the command still returns `ok: true`
because the browser operation completed, but `response.done` is `false` and
`response.error` contains `type: generation_failed` plus Gemini's message.

Use `--input-file FILE` for long prompts. The file is read before dispatching to
the background worker, so relative paths are resolved from the directory where
you ran the command.

Use `--dry-run` to exercise the browser flow without submitting the prompt. It
opens the composer/chat, selects model/tool options, uploads files, and selects
video aspect ratio, then returns before generation starts. Live smoke tests use
dry-run by default to avoid consuming generation quota.

Use `--file FILE` for Gemini attachments from the `+` menu. These are uploaded
through Gemini's visible file picker and may be repeated. Use `--tool TOOL` to
select one of Gemini's visible `+` menu tools before sending. When `--tool
create-image`, `--tool create-video`, or `--tool create-music` is used,
generated media is saved to the current directory; add `--output-dir DIR` to
choose another location. For video,
add `--aspect-ratio landscape` for 16:9 or `--aspect-ratio portrait` for 9:16.
Video generation usually needs a longer `--timeout`, for example `--timeout
900`. If Gemini adds a new menu item before the CLI has a named shortcut for it,
run `chats tools --json` to discover visible labels, then use `--plus-option
"Visible menu label"` as an escape hatch.
Music downloads intentionally choose Gemini's `Audio only` option from the
`Download track` submenu.

Use `--model flash-lite`, `--model flash`, or `--model pro` to select the Gemini
model before sending. Deep Research is only available on Flash and Pro; when
`--tool deep-research` is used without `--model`, the CLI selects Flash before
opening the `+` menu.

For Deep Research, the CLI clicks the visible `Start research` confirmation when
Gemini presents a research plan. By default it returns after research starts with
`response.research.status: in_progress`, the plan, the chat URL, `next_command`,
`wait_command`, `status_command`, and `recommended_poll_seconds`. Agents should
prefer the returned `next_command`/`wait_command` because it uses a single blocking
CLI call with internal polling that returns the completed report in one result.
Add `--wait` or `--wait-research-complete` to the original `chats new` command only
when you want that command to block until the completed report is available.

Completed Deep Research report content is stored in `research.report.text`;
`research.text` is a short status summary. You can also retrieve a completed Deep
Research report later with `chats read <chat> --json`, which includes `research`
when the report is visible. Use `chats status <chat> --json` for generic agent
polling; it returns `type: deep_research` with `research.status` for Deep Research
chats, otherwise it returns a normal chat status and visible messages. Use
`chats research <chat> --json` when you explicitly want Deep Research status only.
It returns `research.status: in_progress` while the report is still running,
`completed` with `research.report.text` and sources when the report is visible, or
`not_found` when the chat does not contain visible Deep Research state. Add `--wait --timeout
SECONDS --poll-interval SECONDS` to poll until completion inside the CLI.

Deep Research wait mode defaults to a 900 second timeout when `--timeout` is not
provided. Normal chat commands still default to 180 seconds.

## Resilience

Gemini is not a stable API surface. The implementation intentionally uses
multiple fallback locators, visible accessibility labels, and DOM extraction
fallbacks rather than a single CSS selector. It should tolerate moderate UI
changes, but maintenance will still be needed when Gemini changes its web app.

## Environment

The CLI automatically loads `.env` from the current working directory before
parsing command defaults. Existing shell/system environment variables take
precedence over `.env`; `.env` only fills missing values. Copy `.env.example` to
`.env` if you want a local project-specific configuration.

- `GEMINIWEBAPP_CLI_SESSION`: default session name.
- `GEMINIWEBAPP_CLI_HOME`: state root, default `~/.geminiwebapp-cli`.
- `GEMINIWEBAPP_CLI_HEADLESS`: set to `1`, `true`, or `yes` for headless mode.
- `GEMINIWEBAPP_CLI_LOG`: Python logging level, default `INFO`.
- `GEMINIWEBAPP_CLI_LIVE`: set to `1`, `true`, `yes`, or `on` to run live smoke tests.
- `GEMINIWEBAPP_CLI_LIVE_SESSION`: session name used by live smoke tests.
- `GEMINIWEBAPP_CLI_LIVE_MUSIC_CHAT`: existing music chat for the live music download smoke test.

## Development

Use `uv` for local development:

```bash
uv sync
uv run pytest -v
uv run geminiwebapp-cli --help
```

## Live Testing

An authenticated live smoke test is available but skipped by default:

```bash
GEMINIWEBAPP_CLI_LIVE=1 uv run pytest tests/test_live_smoke.py -v -s
```

Set `GEMINIWEBAPP_CLI_LIVE_SESSION=<name>` to run it against a non-default
session.

Set `GEMINIWEBAPP_CLI_LIVE_MUSIC_CHAT=<chat>` to enable the live `chats music`
download smoke test against an existing Gemini music chat. `<chat>` can be a chat
id, `/app/...` path, or full Gemini URL. The test downloads visible audio into a
temporary pytest directory and does not generate new music.

Live browser tests require an authenticated Gemini session:

```bash
uv run geminiwebapp-cli login --interactive --wait --timeout 300
uv run geminiwebapp-cli chats new --text "Say hello" --json
```
