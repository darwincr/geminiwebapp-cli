---
name: geminiwebapp-cli
description: "Operate geminiwebapp-cli to drive Gemini (https://gemini.google.com) through a real browser: sending prompts, file attachments, media generation (images/videos/music), Deep Research. USE FOR: performing deep research using google services, or image and video genration and editing images or videos"
---

# geminiwebapp-cli Skill

Operate `geminiwebapp-cli`, a CLI that drives https://gemini.google.com through
a real Camoufox browser with a persistent local profile. No API key; login is
done manually once and reused. The browser UI is not a stable API — expect
occasional locator maintenance.

## Core conventions

- **Always invoke via `uv run geminiwebapp-cli ...`** from the project root. This runs the version from the current source code (not the system-installed CLI at `/Users/darwin/.local/bin/geminiwebapp-cli`), so code changes take effect immediately without a reinstall.
- **Always pass `--json`** for structured, parseable agent output. Errors emit `ok: false` and `error.type`.
- **`--session <name>`** (or `$GEMINIWEBAPP_CLI_SESSION`) targets a profile; default `default`. Profiles live under `~/.geminiwebapp-cli/profiles/<session>` (override with `$GEMINIWEBAPP_CLI_HOME`).
- **`<chat>`** accepts: full Gemini URL, `/app/...` path, Gemini chat id, or a 1-based index from `chats list`.
- A per-session background Camoufox worker is reused across commands; the first command starts it, it exits when idle. Run `session stop` to close it without losing login.
- `.env` in the cwd is auto-loaded; existing env vars take precedence.

## Check current browser state (read-only)

These are the **only** commands documented inline, because they are needed to
assess state before acting. All accept `--session` and emit `--json`.

| Goal | Command |
|------|---------|
| Am I logged in? | `uv run geminiwebapp-cli auth status --json` |
| What chats are in the sidebar? | `uv run geminiwebapp-cli chats list --json` |
| What does the page look like now? | `uv run geminiwebapp-cli screenshot --output shot.png --json` |
| What messages are in a chat? | `uv run geminiwebapp-cli chats read <chat> --json` |
| What type/status is a chat (auto-detect Deep Research)? | `uv run geminiwebapp-cli chats status <chat> --json` |
| What is a Deep Research chat's status? | `uv run geminiwebapp-cli chats research <chat> --json` |

If `auth status` (or any command) returns `error.type: interactive_authentication_required`, follow the returned `next_command` value and complete manual login in the opened browser.

## Functional help index

For every action below, **run the listed `<command> --help` to get current
flags, choices, and defaults** before composing the command. This skill
intentionally does not duplicate flag lists — fetch help on demand per task.

### Top-level & subcommand discovery
| When | Run |
|------|-----|
| See all top-level commands | `uv run geminiwebapp-cli --help` |
| See chats subcommands | `uv run geminiwebapp-cli chats --help` |
| See auth subcommands | `uv run geminiwebapp-cli auth --help` |
| See session subcommands | `uv run geminiwebapp-cli session --help` |

### Authentication (log in)
| When | Run |
|------|-----|
| Log in or verify current session; supports `--interactive`, `--wait`, `--timeout` | `uv run geminiwebapp-cli login --help` |
| Open Gemini for manual login; supports `--wait`, `--timeout` | `uv run geminiwebapp-cli auth interactive --help` |

### Session lifecycle
| When | Run |
|------|-----|
| Stop the background worker, keep the saved profile | `uv run geminiwebapp-cli session stop --help` |
| Delete the local browser profile (also logs out) | `uv run geminiwebapp-cli session clear --help` |

### Send a prompt
| When | Run |
|------|-----|
| Start a NEW chat and send a prompt (covers `--file`, `--tool`, `--model`, `--aspect-ratio`, `--dry-run`, `--wait`, `--timeout`) | `uv run geminiwebapp-cli chats new --help` |
| Send a follow-up to an EXISTING chat (same flags as `new`, plus positional `<chat>`) | `uv run geminiwebapp-cli chats send --help` |
| Alias of `chats send` | `uv run geminiwebapp-cli chats continue --help` |

### Media generation & download
| When | Run |
|------|-----|
| Save generated images from a chat (`--output-dir`) | `uv run geminiwebapp-cli chats images --help` |
| Save generated videos from a chat (`--output-dir`) | `uv run geminiwebapp-cli chats videos --help` |
| Save generated music from a chat (`--output-dir`) | `uv run geminiwebapp-cli chats music --help` |

### Discovery
| When | Run |
|------|-----|
| List sidebar chats (`--limit`) | `uv run geminiwebapp-cli chats list --help` |
| List visible `+` menu options for `--tool` / `--plus-option` | `uv run geminiwebapp-cli chats tools --help` |

## Agent workflow tips (not obvious from `--help`)

- **Deep Research completion**: `chats new --tool deep-research` returns `next_command`, `wait_command`, `status_command`, and `recommended_poll_seconds`. **Prefer `wait_command`** — one blocking call returns the completed report and sources. Report text is in `research.report.text`; `research.text` is only a short status summary.
- **Media generation failure is not a transport error**: the command returns `ok: true` even when Gemini visibly fails. Check `response.done`; when `false`, inspect `response.error.type` (e.g. `generation_failed`) and `response.error.message`.
- **Video/music needs longer timeouts**: use `--timeout 900` or higher for `create-video` / `create-music`.
- **Music downloads** intentionally select Gemini's `Audio only` option from the `Download track` submenu.
- **`--dry-run`** exercises the full browser flow (model/tool/file/aspect-ratio selection) and stops before submitting — use it for smoke tests without consuming generation quota.

## Environment variables

- `GEMINIWEBAPP_CLI_SESSION` — default session name.
- `GEMINIWEBAPP_CLI_HOME` — state root (default `~/.geminiwebapp-cli`).
- `GEMINIWEBAPP_CLI_HEADLESS` — `1`/`true`/`yes` for headless mode.
- `GEMINIWEBAPP_CLI_LOG` — Python logging level (default `INFO`).

## References

- `README.md` — full command table and install steps.
- `BROWSER_OPERATION.md` — deep operational notes (attachments, Deep Research, media, error conventions). Read this for any non-trivial browser workflow.
