from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from geminiwebapp_cli.conf import DEFAULT_DEEP_RESEARCH_TIMEOUT_S, DEFAULT_RESPONSE_TIMEOUT_S, load_dotenv_file
from geminiwebapp_cli.exceptions import (
    AuthenticationError,
    ChatNotFoundError,
    ElementNotFoundError,
    GeminiUnavailableError,
    ImageDownloadError,
    InteractiveAuthenticationRequired,
    MusicDownloadError,
    ResponseTimeoutError,
    VideoDownloadError,
)
from geminiwebapp_cli.session import GeminiSession, clear_profile, session_lock

logger = logging.getLogger("geminiwebapp_cli")

_ERROR_TYPES = [
    (InteractiveAuthenticationRequired, "interactive_authentication_required"),
    (AuthenticationError, "authentication"),
    (ChatNotFoundError, "chat_not_found"),
    (ResponseTimeoutError, "response_timeout"),
    (ElementNotFoundError, "element_not_found"),
    (GeminiUnavailableError, "gemini_unavailable"),
    (ImageDownloadError, "image_download"),
    (VideoDownloadError, "video_download"),
    (MusicDownloadError, "music_download"),
]


def _out(text: str) -> None:
    sys.stdout.write(f"{text}\n")
    sys.stdout.flush()


def _err(text: str) -> None:
    print(text, file=sys.stderr)


def _error_type(exc: Exception) -> str | None:
    for cls, name in _ERROR_TYPES:
        if isinstance(exc, cls):
            return name
    return None


def _render(command: str, result: dict, as_json: bool) -> None:
    if as_json:
        _out(json.dumps(result, ensure_ascii=False, default=str))
        return
    if command in {"login", "auth-interactive"}:
        _out(f"logged in: {result.get('email') or result.get('account') or result.get('url')}")
    elif command == "auth-status":
        if result.get("authenticated"):
            _out(f"logged in: {result.get('email') or result.get('account') or result.get('url')}")
        else:
            _out(f"not logged in: {result.get('state')}")
    elif command == "chats-list":
        chats = result.get("chats") or []
        _out("(no chats)" if not chats else "\n".join(f"{idx + 1}. {chat.get('title') or chat.get('id') or chat.get('url')}" for idx, chat in enumerate(chats)))
    elif command == "chats-tools":
        options = result.get("options") or []
        _out("(no tools)" if not options else "\n".join(str(option.get("label") or "") for option in options))
    elif command in {"chats-new", "chats-send", "chats-continue"}:
        if result.get("dry_run"):
            _out("Dry run completed before submission")
            return
        response = result.get("response") or {}
        images = response.get("images") or []
        videos = response.get("videos") or []
        music = response.get("music") or []
        artifacts = [str(image.get("path") or "") for image in images]
        artifacts.extend(str(video.get("path") or "") for video in videos)
        artifacts.extend(str(track.get("path") or "") for track in music)
        if artifacts:
            _out("\n".join(artifacts))
        else:
            _out(response.get("text") or "")
    elif command == "chats-read":
        messages = result.get("messages") or []
        _out("(no messages)" if not messages else "\n\n".join(f"{message.get('role', 'message')}: {message.get('text', '')}" for message in messages))
    elif command == "chats-research":
        research = result.get("research") or {}
        _out(research.get("text") or research.get("status") or "")
    elif command == "chats-images":
        images = result.get("images") or []
        _out("(no images)" if not images else "\n".join(str(image.get("path") or "") for image in images))
    elif command == "chats-videos":
        videos = result.get("videos") or []
        _out("(no videos)" if not videos else "\n".join(str(video.get("path") or "") for video in videos))
    elif command == "chats-music":
        music = result.get("music") or []
        _out("(no music)" if not music else "\n".join(str(track.get("path") or "") for track in music))
    elif command == "session-clear":
        _out(f"cleared {result.get('name')}")
    elif command == "session-stop":
        _out(f"stopped {result.get('name')}")
    else:
        _out("\n".join(f"{key}: {value}" for key, value in result.items()))


def _verb_login(session, args) -> dict:
    if args.interactive:
        from geminiwebapp_cli.actions.auth import interactive_auth

        return interactive_auth(session, wait=args.wait, timeout=args.timeout)

    from geminiwebapp_cli.actions.auth import ensure_logged_in

    return ensure_logged_in(session)


def _verb_auth_interactive(session, args) -> dict:
    from geminiwebapp_cli.actions.auth import interactive_auth

    return interactive_auth(session, wait=args.wait, timeout=args.timeout)


def _verb_auth_status(session, args) -> dict:
    from geminiwebapp_cli.actions.auth import auth_status

    return auth_status(session)


def _verb_chats_list(session, args) -> dict:
    from geminiwebapp_cli.actions.chats import list_chats

    return list_chats(session, limit=args.limit)


def _verb_chats_tools(session, args) -> dict:
    from geminiwebapp_cli.actions.chats import list_plus_options

    return list_plus_options(session)


def _verb_chats_new(session, args) -> dict:
    from geminiwebapp_cli.actions.chats import new_chat

    return new_chat(
        session,
        _prompt_text(args),
        timeout=_chat_timeout(args),
        tools=args.tool,
        files=args.file,
        model=args.model,
        plus_options=args.plus_option,
        wait_research_complete=args.wait_research_complete,
        output_dir=_media_output_dir(args),
        aspect_ratio=args.aspect_ratio,
        dry_run=args.dry_run,
    )


def _verb_chats_send(session, args) -> dict:
    from geminiwebapp_cli.actions.chats import send_to_chat

    return send_to_chat(
        session,
        args.chat,
        _prompt_text(args),
        timeout=_chat_timeout(args),
        tools=args.tool,
        files=args.file,
        model=args.model,
        plus_options=args.plus_option,
        wait_research_complete=args.wait_research_complete,
        output_dir=_media_output_dir(args),
        aspect_ratio=args.aspect_ratio,
        dry_run=args.dry_run,
    )


def _verb_chats_read(session, args) -> dict:
    from geminiwebapp_cli.actions.chats import read_chat

    return read_chat(session, args.chat, limit=args.limit)


def _verb_chats_research(session, args) -> dict:
    from geminiwebapp_cli.actions.chats import research_status

    return research_status(session, args.chat, wait=args.wait, timeout=args.timeout)


def _verb_chats_images(session, args) -> dict:
    from geminiwebapp_cli.actions.chats import save_chat_images

    return save_chat_images(session, args.chat, output_dir=args.output_dir)


def _verb_chats_videos(session, args) -> dict:
    from geminiwebapp_cli.actions.chats import save_chat_videos

    return save_chat_videos(session, args.chat, output_dir=args.output_dir)


def _verb_chats_music(session, args) -> dict:
    from geminiwebapp_cli.actions.chats import save_chat_music

    return save_chat_music(session, args.chat, output_dir=args.output_dir)


def _chat_timeout(args) -> int:
    if getattr(args, "timeout", None) == DEFAULT_RESPONSE_TIMEOUT_S and getattr(args, "wait_research_complete", False):
        return DEFAULT_DEEP_RESEARCH_TIMEOUT_S
    return args.timeout


def _media_output_dir(args) -> Path | None:
    tools = getattr(args, "tool", None) or []
    plus_options = getattr(args, "plus_option", None) or []
    wants_media = any(str(tool).strip().lower().replace("_", "-").replace(" ", "-") in {"create-image", "create-video", "create-music"} for tool in tools)
    wants_media = wants_media or any(str(option).strip().lower() in {"create image", "create video", "create music"} for option in plus_options)
    if not wants_media:
        return None
    return getattr(args, "output_dir", None) or Path.cwd()


def _image_output_dir(args) -> Path | None:
    return _media_output_dir(args)


_VERBS = {
    "login": _verb_login,
    "auth-interactive": _verb_auth_interactive,
    "auth-status": _verb_auth_status,
    "chats-list": _verb_chats_list,
    "chats-tools": _verb_chats_tools,
    "chats-new": _verb_chats_new,
    "chats-send": _verb_chats_send,
    "chats-continue": _verb_chats_send,
    "chats-read": _verb_chats_read,
    "chats-research": _verb_chats_research,
    "chats-images": _verb_chats_images,
    "chats-videos": _verb_chats_videos,
    "chats-music": _verb_chats_music,
}


def _error_payload(exc: Exception, error_type: str) -> dict:
    payload = {
        "ok": False,
        "authenticated": False,
        "error": {
            "type": error_type,
            "message": str(exc),
        },
    }
    if error_type == "interactive_authentication_required":
        payload["state"] = "login_required"
        payload["next_command"] = "geminiwebapp-cli login --interactive --wait --timeout 300"
    return payload


def _execute_verb(args, session) -> int:
    try:
        _render(args.verb, _VERBS[args.verb](session, args), args.json)
        return 0
    except Exception as exc:  # noqa: BLE001
        error_type = _error_type(exc)
        if error_type is None:
            raise
        if args.json:
            _out(json.dumps(_error_payload(exc, error_type), ensure_ascii=False, default=str))
            return 1
        _err(f"error: {error_type}: {exc}")
        return 1


def _run_verb_local(args) -> int:
    with session_lock(args.name):
        session = GeminiSession(args.name)
        with session:
            return _execute_verb(args, session)


def _run_verb(args, argv: list[str]) -> int:
    if os.environ.get("GEMINIWEBAPP_CLI_WORKER") == "1":
        return _run_verb_local(args)
    from geminiwebapp_cli.worker import run_via_worker

    return run_via_worker(args.name, _argv_with_prompt_text(args, argv))


def _cmd_session_clear(args) -> int:
    from geminiwebapp_cli.worker import stop_worker

    stop_worker(args.name)
    with session_lock(args.name):
        clear_profile(args.name)
    _render("session-clear", {"name": args.name, "cleared": True}, args.json)
    return 0


def _cmd_session_stop(args) -> int:
    from geminiwebapp_cli.worker import stop_worker

    stop_worker(args.name)
    _render("session-stop", {"name": args.name, "stopped": True}, args.json)
    return 0


def _prompt_text(args) -> str:
    if args.text is not None:
        return args.text
    if args.input_file:
        try:
            return args.input_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"error: could not read input file {args.input_file}: {exc}") from exc
    raise SystemExit("error: one of --text or --input-file is required")


def _argv_with_prompt_text(args, argv: list[str]) -> list[str]:
    if not getattr(args, "input_file", None) and not getattr(args, "file", None) and not getattr(args, "output_dir", None) and _media_output_dir(args) is None:
        return argv
    rewritten = []
    skip_next = False
    for item in argv:
        if skip_next:
            skip_next = False
            continue
        if item == "--input-file":
            skip_next = True
            continue
        if item.startswith("--input-file="):
            continue
        rewritten.append(item)
    if getattr(args, "input_file", None):
        rewritten.extend(["--text", _prompt_text(args)])
    rewritten = _rewrite_file_args(args, rewritten)
    rewritten = _rewrite_output_dir_arg(args, rewritten)
    return rewritten


def _rewrite_file_args(args, argv: list[str]) -> list[str]:
    files = getattr(args, "file", None) or []
    if not files:
        return argv
    rewritten = []
    skip_next = False
    for item in argv:
        if skip_next:
            skip_next = False
            continue
        if item == "--file":
            skip_next = True
            continue
        if item.startswith("--file="):
            continue
        rewritten.append(item)
    for path in files:
        rewritten.extend(["--file", str(path.expanduser().resolve())])
    return rewritten


def _rewrite_output_dir_arg(args, argv: list[str]) -> list[str]:
    output_dir = getattr(args, "output_dir", None) or _media_output_dir(args)
    if output_dir is None:
        return argv
    rewritten = []
    skip_next = False
    for item in argv:
        if skip_next:
            skip_next = False
            continue
        if item == "--output-dir":
            skip_next = True
            continue
        if item.startswith("--output-dir="):
            continue
        rewritten.append(item)
    rewritten.extend(["--output-dir", str(output_dir.expanduser().resolve())])
    return rewritten


def _add_prompt_input_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Prompt text to send")
    group.add_argument("--input-file", type=Path, help="Read prompt text from a UTF-8 file")


def _add_plus_menu_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model",
        choices=["flash-lite", "flash", "pro", "Flash-Lite", "Flash", "Pro"],
        help="Select Gemini model before sending. Deep Research auto-selects Flash when omitted.",
    )
    parser.add_argument(
        "--tool",
        action="append",
        default=[],
        choices=["create-image", "create-video", "deep-research", "create-music"],
        help="Select a Gemini + menu tool before submitting; repeatable",
    )
    parser.add_argument("--file", action="append", default=[], type=Path, help="Upload a local file through Gemini's + menu before submitting; repeatable")
    parser.add_argument("--plus-option", action="append", default=[], help="Click an arbitrary visible Gemini + menu option by label before submitting; repeatable")
    parser.add_argument("--output-dir", type=Path, default=None, help="With --tool create-image/create-video/create-music, save generated media to this directory")
    parser.add_argument("--aspect-ratio", choices=["landscape", "portrait", "16:9", "9:16"], help="With --tool create-video, select Landscape (16:9) or Portrait (9:16)")
    parser.add_argument("--dry-run", action="store_true", help="Perform setup steps but stop before submitting the prompt")
    parser.add_argument(
        "--wait-research-complete",
        "--wait",
        dest="wait_research_complete",
        action="store_true",
        help=f"With --tool deep-research, wait for the completed report and return report text/sources (default timeout: {DEFAULT_DEEP_RESEARCH_TIMEOUT_S}s)",
    )


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--session", "--name", dest="name",
        default=os.environ.get("GEMINIWEBAPP_CLI_SESSION", "default"),
        help="Session/profile name (default: $GEMINIWEBAPP_CLI_SESSION or 'default')",
    )
    common.add_argument("--json", action="store_true", help="Emit full JSON instead of a short summary")

    parser = argparse.ArgumentParser(prog="geminiwebapp-cli", description="Drive Gemini through Camoufox")
    sub = parser.add_subparsers(dest="cmd", required=True)

    session_cmd = sub.add_parser("session", help="Manage local browser session state")
    session_sub = session_cmd.add_subparsers(dest="subcmd", required=True)
    session_sub.add_parser("clear", parents=[common], help="Delete the local browser profile for a session")
    session_sub.add_parser("stop", parents=[common], help="Stop the background worker without deleting the browser profile")

    p_login = sub.add_parser("login", parents=[common], help="Log in or verify the current Gemini session")
    p_login.add_argument("--interactive", action="store_true", help="Open Gemini and wait while you complete Google login manually")
    p_login.add_argument("--wait", action="store_true", help="With --interactive, poll until login completes instead of waiting for Enter")
    p_login.add_argument("--timeout", type=int, default=300, help="Maximum seconds to wait with --interactive --wait (default: 300)")

    auth_cmd = sub.add_parser("auth", help="Authenticate the persistent browser profile")
    auth_sub = auth_cmd.add_subparsers(dest="auth_cmd", required=True)
    auth_sub.add_parser("status", parents=[common], help="Report the current authentication state")
    p_auth_interactive = auth_sub.add_parser("interactive", parents=[common], help="Open Gemini and wait while you log in manually")
    p_auth_interactive.add_argument("--wait", action="store_true", help="Poll until login completes instead of waiting for Enter")
    p_auth_interactive.add_argument("--timeout", type=int, default=300, help="Maximum seconds to wait with --wait (default: 300)")

    chats_cmd = sub.add_parser("chats", help="Read and send Gemini chats")
    chats_sub = chats_cmd.add_subparsers(dest="chats_cmd", required=True)

    p_chats_list = chats_sub.add_parser("list", parents=[common], help="List recent Gemini chats from the sidebar")
    p_chats_list.add_argument("--limit", type=int, default=20, help="Maximum chats to return (default: 20)")

    chats_sub.add_parser("tools", parents=[common], help="List visible Gemini + menu options for --tool/--plus-option")

    p_chats_new = chats_sub.add_parser("new", parents=[common], help="Start a new chat and send a prompt")
    _add_prompt_input_args(p_chats_new)
    _add_plus_menu_args(p_chats_new)
    p_chats_new.add_argument("--timeout", type=int, default=DEFAULT_RESPONSE_TIMEOUT_S, help=f"Maximum seconds to wait for response completion (default: {DEFAULT_RESPONSE_TIMEOUT_S}; Deep Research --wait default: {DEFAULT_DEEP_RESEARCH_TIMEOUT_S})")

    p_chats_send = chats_sub.add_parser("send", parents=[common], help="Send a follow-up prompt to an existing chat")
    p_chats_send.add_argument("chat", help="Chat URL, /app path, Gemini chat id, or 1-based index from the sidebar")
    _add_prompt_input_args(p_chats_send)
    _add_plus_menu_args(p_chats_send)
    p_chats_send.add_argument("--timeout", type=int, default=DEFAULT_RESPONSE_TIMEOUT_S, help=f"Maximum seconds to wait for response completion (default: {DEFAULT_RESPONSE_TIMEOUT_S}; Deep Research --wait default: {DEFAULT_DEEP_RESEARCH_TIMEOUT_S})")

    p_chats_continue = chats_sub.add_parser("continue", parents=[common], help="Alias for chats send")
    p_chats_continue.add_argument("chat", help="Chat URL, /app path, Gemini chat id, or 1-based index from the sidebar")
    _add_prompt_input_args(p_chats_continue)
    _add_plus_menu_args(p_chats_continue)
    p_chats_continue.add_argument("--timeout", type=int, default=DEFAULT_RESPONSE_TIMEOUT_S, help=f"Maximum seconds to wait for response completion (default: {DEFAULT_RESPONSE_TIMEOUT_S}; Deep Research --wait default: {DEFAULT_DEEP_RESEARCH_TIMEOUT_S})")

    p_chats_read = chats_sub.add_parser("read", parents=[common], help="Open a chat and extract visible message history")
    p_chats_read.add_argument("chat", help="Chat URL, /app path, Gemini chat id, or 1-based index from the sidebar")
    p_chats_read.add_argument("--limit", type=int, default=20, help="Maximum visible messages to return (default: 20)")

    p_chats_research = chats_sub.add_parser("research", parents=[common], help="Check Deep Research status or retrieve a completed report")
    p_chats_research.add_argument("chat", help="Chat URL, /app path, Gemini chat id, or 1-based index from the sidebar")
    p_chats_research.add_argument("--wait", action="store_true", help="Wait until the Deep Research report is completed")
    p_chats_research.add_argument("--timeout", type=int, default=DEFAULT_RESPONSE_TIMEOUT_S, help=f"Maximum seconds to wait with --wait (default: {DEFAULT_RESPONSE_TIMEOUT_S})")

    p_chats_images = chats_sub.add_parser("images", parents=[common], help="Save visible generated images from an existing chat")
    p_chats_images.add_argument("chat", help="Chat URL, /app path, Gemini chat id, or 1-based index from the sidebar")
    p_chats_images.add_argument("--output-dir", type=Path, default=Path.cwd(), help="Directory where images are saved (default: current directory)")

    p_chats_videos = chats_sub.add_parser("videos", parents=[common], help="Save visible generated videos from an existing chat")
    p_chats_videos.add_argument("chat", help="Chat URL, /app path, Gemini chat id, or 1-based index from the sidebar")
    p_chats_videos.add_argument("--output-dir", type=Path, default=Path.cwd(), help="Directory where videos are saved (default: current directory)")

    p_chats_music = chats_sub.add_parser("music", parents=[common], help="Save visible generated music from an existing chat")
    p_chats_music.add_argument("chat", help="Chat URL, /app path, Gemini chat id, or 1-based index from the sidebar")
    p_chats_music.add_argument("--output-dir", type=Path, default=Path.cwd(), help="Directory where music is saved (default: current directory)")
    return parser


def _configure_logging() -> None:
    level = os.environ.get("GEMINIWEBAPP_CLI_LOG", "INFO").upper()
    logging.basicConfig(level=level, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _parse_args(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "auth":
        args.verb = f"auth-{args.auth_cmd}"
    elif args.cmd == "chats":
        args.verb = f"chats-{args.chats_cmd}"
    else:
        args.verb = args.cmd
    return args


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    load_dotenv_file()
    args = _parse_args(argv)
    _configure_logging()
    if args.cmd == "session":
        if args.subcmd == "stop":
            return _cmd_session_stop(args)
        return _cmd_session_clear(args)
    return _run_verb(args, argv)


if __name__ == "__main__":
    raise SystemExit(main())
