from __future__ import annotations

from pathlib import Path

import pytest

from geminiwebapp_cli.actions.auth import _email_from_text
from geminiwebapp_cli.actions.chats import _response_payload, _select_video_aspect_ratio_if_needed, _tool_label, _video_aspect_ratio_label, chat_id_from_url, chat_url
from geminiwebapp_cli.cli import _argv_with_prompt_text, _image_output_dir, _parse_args, build_parser
from geminiwebapp_cli.conf import DEFAULT_DEEP_RESEARCH_TIMEOUT_S, DEFAULT_RESPONSE_TIMEOUT_S, GEMINI_APP_URL, GEMINI_BASE_URL, load_dotenv_file
from geminiwebapp_cli.cli import _chat_timeout


class TestChatUrl:
    def test_empty_chat_url_is_app(self):
        assert chat_url() == GEMINI_APP_URL

    def test_full_url_passes_through(self):
        url = "https://gemini.google.com/app/abc123"
        assert chat_url(url) == url

    def test_app_path(self):
        assert chat_url("/app/abc123") == f"{GEMINI_BASE_URL}/app/abc123"

    def test_id(self):
        assert chat_url("abc123") == f"{GEMINI_APP_URL}/abc123"

    def test_chat_id_from_url(self):
        assert chat_id_from_url("https://gemini.google.com/app/abc123?x=1") == "abc123"


class TestAuthParsing:
    def test_email_from_google_account_label(self):
        assert _email_from_text("Google Account: Darwin C (darwin@example.com)") == "darwin@example.com"

    def test_email_from_popover_text(self):
        assert _email_from_text("Darwin C\ndarwin.cr+gemini@example.co.uk\nManage your Google Account") == "darwin.cr+gemini@example.co.uk"

    def test_email_from_text_without_email(self):
        assert _email_from_text("Google Account") is None


class TestCliParsing:
    def test_login_defaults(self):
        args = _parse_args(["login"])
        assert args.verb == "login"
        assert args.name == "default"
        assert args.interactive is False

    def test_auth_status(self):
        args = _parse_args(["auth", "status", "--json"])
        assert args.verb == "auth-status"
        assert args.json is True

    def test_chats_list(self):
        args = _parse_args(["chats", "list", "--limit", "5"])
        assert args.verb == "chats-list"
        assert args.limit == 5

    def test_chats_tools(self):
        args = _parse_args(["chats", "tools", "--json"])
        assert args.verb == "chats-tools"
        assert args.json is True

    def test_chats_tools_not_rewritten_before_worker(self):
        argv = ["chats", "tools", "--json"]
        args = _parse_args(argv)
        assert _argv_with_prompt_text(args, argv) == argv

    def test_chats_new(self):
        args = _parse_args(["chats", "new", "--text", "hello", "--timeout", "30"])
        assert args.verb == "chats-new"
        assert args.text == "hello"
        assert args.timeout == 30
        assert args.tool == []
        assert args.file == []
        assert args.model is None
        assert args.plus_option == []
        assert args.wait_research_complete is False
        assert args.dry_run is False

    def test_chats_new_dry_run(self):
        args = _parse_args(["chats", "new", "--text", "hello", "--tool", "create-video", "--dry-run"])
        assert args.dry_run is True

    def test_chats_new_model(self):
        args = _parse_args(["chats", "new", "--text", "hello", "--model", "flash"])
        assert args.model == "flash"

    def test_chats_new_plus_menu_options(self, tmp_path: Path):
        upload = tmp_path / "data.txt"
        upload.write_text("hello", encoding="utf-8")
        args = _parse_args([
            "chats",
            "new",
            "--text",
            "hello",
            "--tool",
            "deep-research",
            "--tool",
            "create-image",
            "--model",
            "Pro",
            "--file",
            str(upload),
            "--plus-option",
            "Create image",
            "--wait-research-complete",
        ])
        assert args.tool == ["deep-research", "create-image"]
        assert args.model == "Pro"
        assert args.file == [upload]
        assert args.plus_option == ["Create image"]
        assert args.wait_research_complete is True

    def test_chats_new_create_image_defaults_to_output_dir(self):
        args = _parse_args(["chats", "new", "--text", "hello", "--tool", "create-image"])
        assert args.output_dir is None
        assert _image_output_dir(args) == Path.cwd()

    def test_chats_new_create_image_accepts_output_dir(self, tmp_path: Path):
        args = _parse_args(["chats", "new", "--text", "hello", "--tool", "create-image", "--output-dir", str(tmp_path)])
        assert _image_output_dir(args) == tmp_path

    def test_chats_new_create_image_output_dir_injected_before_worker(self):
        argv = ["chats", "new", "--text", "hello", "--tool", "create-image"]
        args = _parse_args(argv)
        assert _argv_with_prompt_text(args, argv) == ["chats", "new", "--text", "hello", "--tool", "create-image", "--output-dir", str(Path.cwd())]

    def test_chats_new_create_video_defaults_to_output_dir(self):
        args = _parse_args(["chats", "new", "--text", "hello", "--tool", "create-video"])
        assert args.output_dir is None
        assert _image_output_dir(args) == Path.cwd()

    def test_chats_new_create_video_accepts_output_dir(self, tmp_path: Path):
        args = _parse_args(["chats", "new", "--text", "hello", "--tool", "create-video", "--output-dir", str(tmp_path)])
        assert _image_output_dir(args) == tmp_path

    def test_chats_new_create_video_output_dir_injected_before_worker(self):
        argv = ["chats", "new", "--text", "hello", "--tool", "create-video"]
        args = _parse_args(argv)
        assert _argv_with_prompt_text(args, argv) == ["chats", "new", "--text", "hello", "--tool", "create-video", "--output-dir", str(Path.cwd())]

    def test_chats_new_create_music_defaults_to_output_dir(self):
        args = _parse_args(["chats", "new", "--text", "hello", "--tool", "create-music"])
        assert args.output_dir is None
        assert _image_output_dir(args) == Path.cwd()

    def test_chats_new_create_music_accepts_output_dir(self, tmp_path: Path):
        args = _parse_args(["chats", "new", "--text", "hello", "--tool", "create-music", "--output-dir", str(tmp_path)])
        assert _image_output_dir(args) == tmp_path

    def test_chats_new_create_music_output_dir_injected_before_worker(self):
        argv = ["chats", "new", "--text", "hello", "--tool", "create-music"]
        args = _parse_args(argv)
        assert _argv_with_prompt_text(args, argv) == ["chats", "new", "--text", "hello", "--tool", "create-music", "--output-dir", str(Path.cwd())]

    def test_generation_failure_response_payload(self):
        payload = _response_payload("Something went wrong with the music generation. Please try again.")
        assert payload == {
            "text": "Something went wrong with the music generation. Please try again.",
            "done": False,
            "error": {
                "type": "generation_failed",
                "message": "Something went wrong with the music generation. Please try again.",
            },
        }

    def test_success_response_payload(self):
        payload = _response_payload("Saved 1 generated music track(s)")
        assert payload == {"text": "Saved 1 generated music track(s)", "done": True}

    def test_chats_new_create_video_aspect_ratio(self):
        args = _parse_args(["chats", "new", "--text", "hello", "--tool", "create-video", "--aspect-ratio", "portrait"])
        assert args.aspect_ratio == "portrait"
        assert _video_aspect_ratio_label(args.aspect_ratio) == "Portrait (9:16)"

    @pytest.mark.parametrize(
        ("value", "label"),
        [("landscape", "Landscape (16:9)"), ("16:9", "Landscape (16:9)"), ("portrait", "Portrait (9:16)"), ("9:16", "Portrait (9:16)")],
    )
    def test_video_aspect_ratio_labels(self, value: str, label: str):
        assert _video_aspect_ratio_label(value) == label

    def test_invalid_video_aspect_ratio_rejected_by_parser(self):
        with pytest.raises(SystemExit):
            _parse_args(["chats", "new", "--text", "hello", "--tool", "create-video", "--aspect-ratio", "square"])

    def test_video_aspect_ratio_requires_create_video_tool(self):
        with pytest.raises(ValueError):
            _select_video_aspect_ratio_if_needed(None, selected={"tools": ["Create image"]}, aspect_ratio="landscape")

    @pytest.mark.parametrize("tool", ["image", "video", "research", "music"])
    def test_short_tool_aliases_are_rejected_by_parser(self, tool: str):
        with pytest.raises(SystemExit):
            _parse_args(["chats", "new", "--text", "hello", "--tool", tool])

    @pytest.mark.parametrize("tool", ["image", "video", "research", "music"])
    def test_short_tool_aliases_are_rejected_by_mapping(self, tool: str):
        with pytest.raises(ValueError):
            _tool_label(tool)

    def test_chats_new_wait_alias(self):
        args = _parse_args(["chats", "new", "--text", "hello", "--tool", "deep-research", "--wait"])
        assert args.wait_research_complete is True

    def test_deep_research_wait_uses_longer_default_timeout(self):
        args = _parse_args(["chats", "new", "--text", "hello", "--tool", "deep-research", "--wait"])
        assert args.timeout == DEFAULT_RESPONSE_TIMEOUT_S
        assert _chat_timeout(args) == DEFAULT_DEEP_RESEARCH_TIMEOUT_S

    def test_explicit_timeout_overrides_deep_research_default_timeout(self):
        args = _parse_args(["chats", "new", "--text", "hello", "--tool", "deep-research", "--wait", "--timeout", "60"])
        assert _chat_timeout(args) == 60

    def test_chats_new_input_file(self, tmp_path: Path):
        prompt = tmp_path / "prompt.md"
        prompt.write_text("hello from file", encoding="utf-8")
        args = _parse_args(["chats", "new", "--input-file", str(prompt)])
        assert args.verb == "chats-new"
        assert args.input_file == prompt

    def test_input_file_rewritten_before_worker(self, tmp_path: Path):
        prompt = tmp_path / "prompt.md"
        prompt.write_text("hello from file", encoding="utf-8")
        argv = ["chats", "new", "--input-file", str(prompt), "--timeout", "30"]
        args = _parse_args(argv)
        assert _argv_with_prompt_text(args, argv) == ["chats", "new", "--timeout", "30", "--text", "hello from file"]

    def test_input_file_equals_rewritten_before_worker(self, tmp_path: Path):
        prompt = tmp_path / "prompt.md"
        prompt.write_text("hello from file", encoding="utf-8")
        argv = ["chats", "new", f"--input-file={prompt}"]
        args = _parse_args(argv)
        assert _argv_with_prompt_text(args, argv) == ["chats", "new", "--text", "hello from file"]

    def test_upload_files_rewritten_before_worker(self, tmp_path: Path):
        upload = tmp_path / "upload.txt"
        upload.write_text("upload", encoding="utf-8")
        argv = ["chats", "new", "--text", "hello", "--file", str(upload)]
        args = _parse_args(argv)
        assert _argv_with_prompt_text(args, argv) == ["chats", "new", "--text", "hello", "--file", str(upload.resolve())]

    def test_upload_files_equals_rewritten_before_worker(self, tmp_path: Path):
        upload = tmp_path / "upload.txt"
        upload.write_text("upload", encoding="utf-8")
        argv = ["chats", "new", "--text", "hello", f"--file={upload}"]
        args = _parse_args(argv)
        assert _argv_with_prompt_text(args, argv) == ["chats", "new", "--text", "hello", "--file", str(upload.resolve())]

    def test_chats_images(self, tmp_path: Path):
        args = _parse_args(["chats", "images", "abc", "--output-dir", str(tmp_path), "--json"])
        assert args.verb == "chats-images"
        assert args.chat == "abc"
        assert args.output_dir == tmp_path
        assert args.json is True

    def test_chats_images_output_dir_rewritten_before_worker(self, tmp_path: Path):
        argv = ["chats", "images", "abc", "--output-dir", str(tmp_path)]
        args = _parse_args(argv)
        assert _argv_with_prompt_text(args, argv) == ["chats", "images", "abc", "--output-dir", str(tmp_path.resolve())]

    def test_chats_videos(self, tmp_path: Path):
        args = _parse_args(["chats", "videos", "abc", "--output-dir", str(tmp_path), "--json"])
        assert args.verb == "chats-videos"
        assert args.chat == "abc"
        assert args.output_dir == tmp_path
        assert args.json is True

    def test_chats_videos_output_dir_rewritten_before_worker(self, tmp_path: Path):
        argv = ["chats", "videos", "abc", "--output-dir", str(tmp_path)]
        args = _parse_args(argv)
        assert _argv_with_prompt_text(args, argv) == ["chats", "videos", "abc", "--output-dir", str(tmp_path.resolve())]

    def test_chats_music(self, tmp_path: Path):
        args = _parse_args(["chats", "music", "abc", "--output-dir", str(tmp_path), "--json"])
        assert args.verb == "chats-music"
        assert args.chat == "abc"
        assert args.output_dir == tmp_path
        assert args.json is True

    def test_chats_music_output_dir_rewritten_before_worker(self, tmp_path: Path):
        argv = ["chats", "music", "abc", "--output-dir", str(tmp_path)]
        args = _parse_args(argv)
        assert _argv_with_prompt_text(args, argv) == ["chats", "music", "abc", "--output-dir", str(tmp_path.resolve())]

    def test_chats_send(self):
        args = _parse_args(["chats", "send", "abc", "--text", "follow", "--dry-run"])
        assert args.verb == "chats-send"
        assert args.chat == "abc"
        assert args.text == "follow"
        assert args.dry_run is True

    def test_chats_continue_alias(self):
        args = _parse_args(["chats", "continue", "abc", "--text", "follow"])
        assert args.verb == "chats-continue"
        assert args.chat == "abc"

    def test_text_and_input_file_are_mutually_exclusive(self, tmp_path: Path):
        prompt = tmp_path / "prompt.md"
        prompt.write_text("hello", encoding="utf-8")
        with pytest.raises(SystemExit):
            _parse_args(["chats", "new", "--text", "hello", "--input-file", str(prompt)])

    def test_chats_read(self):
        args = _parse_args(["chats", "read", "1", "--limit", "10"])
        assert args.verb == "chats-read"
        assert args.chat == "1"
        assert args.limit == 10

    def test_chats_research(self):
        args = _parse_args(["chats", "research", "abc", "--wait", "--timeout", "900", "--json"])
        assert args.verb == "chats-research"
        assert args.chat == "abc"
        assert args.wait is True
        assert args.timeout == 900
        assert args.json is True

    def test_parser_contains_chats(self):
        parser = build_parser()
        subparsers_action = None
        for action in parser._actions:
            if hasattr(action, "choices") and "chats" in (action.choices or {}):
                subparsers_action = action
                break
        assert subparsers_action is not None

    def test_session_stop(self):
        args = _parse_args(["session", "stop", "--session", "work", "--json"])
        assert args.cmd == "session"
        assert args.subcmd == "stop"
        assert args.name == "work"
        assert args.json is True


class TestDotenv:
    def test_load_dotenv_file_fills_missing_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        env_file = tmp_path / ".env"
        env_file.write_text("GEMINIWEBAPP_CLI_SESSION=from-dotenv\nGEMINIWEBAPP_CLI_LOG=DEBUG\n", encoding="utf-8")
        monkeypatch.delenv("GEMINIWEBAPP_CLI_SESSION", raising=False)
        monkeypatch.delenv("GEMINIWEBAPP_CLI_LOG", raising=False)

        loaded = load_dotenv_file(env_file)

        assert loaded == {"GEMINIWEBAPP_CLI_SESSION": "from-dotenv", "GEMINIWEBAPP_CLI_LOG": "DEBUG"}
        assert _parse_args(["chats", "list"]).name == "from-dotenv"

    def test_load_dotenv_file_does_not_override_existing_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        env_file = tmp_path / ".env"
        env_file.write_text("GEMINIWEBAPP_CLI_SESSION=from-dotenv\n", encoding="utf-8")
        monkeypatch.setenv("GEMINIWEBAPP_CLI_SESSION", "from-shell")

        loaded = load_dotenv_file(env_file)

        assert loaded == {}
        assert _parse_args(["chats", "list"]).name == "from-shell"

    def test_load_dotenv_file_parses_quotes_export_and_comments(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# comment\nexport GEMINIWEBAPP_CLI_LOG='WARNING'\nGEMINIWEBAPP_CLI_HEADLESS=true # inline comment\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("GEMINIWEBAPP_CLI_LOG", raising=False)
        monkeypatch.delenv("GEMINIWEBAPP_CLI_HEADLESS", raising=False)

        loaded = load_dotenv_file(env_file)

        assert loaded == {"GEMINIWEBAPP_CLI_LOG": "WARNING", "GEMINIWEBAPP_CLI_HEADLESS": "true"}
