from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


RUN_LIVE = os.environ.get("GEMINIWEBAPP_CLI_LIVE") in {"1", "true", "yes", "on"}
NUC_IMAGE = Path("/Users/darwin/Downloads/NUC13Extreme.jpg")
LIVE_SKIP_REASON = "set GEMINIWEBAPP_CLI_LIVE=1 to run live Gemini smoke tests"
LIVE_MUSIC_CHAT = os.environ.get("GEMINIWEBAPP_CLI_LIVE_MUSIC_CHAT", "").strip()


def _run(*args: str) -> dict:
    proc = subprocess.run(
        ["geminiwebapp-cli", *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def _session_args() -> list[str]:
    session = os.environ.get("GEMINIWEBAPP_CLI_LIVE_SESSION", os.environ.get("GEMINIWEBAPP_CLI_SESSION", "default"))
    return ["--session", session]


def _assert_authenticated(common: list[str]) -> None:
    status = _run("auth", "status", *common)
    assert status.get("authenticated"), status


def _assert_dry_run(result: dict) -> None:
    assert result.get("ok") is True
    assert result.get("dry_run") is True
    assert result.get("submitted") is False
    assert (result.get("response") or {}).get("done") is False


def _image_prompt() -> str:
    return (
        "Using the uploaded photo as the reference, keep the PC case, angle, "
        "lighting, and open chassis layout natural. Add a realistic modern GPU "
        "installed into the available PCIe/GPU slot. The GPU should be properly "
        "seated, aligned with the slot, and visually integrated with matching "
        "perspective and shadows. No text."
    )


def _research_file(tmp_path: Path) -> Path:
    source = tmp_path / "research-source.txt"
    source.write_text(
        "Geminiwebapp CLI live dry-run fixture. Use this local source as an "
        "attachment for exercising Deep Research setup without submitting.",
        encoding="utf-8",
    )
    return source


@pytest.mark.skipif(not RUN_LIVE, reason=LIVE_SKIP_REASON)
def test_live_authenticated_chat_smoke():
    common = _session_args()
    _assert_authenticated(common)

    prompt = "Reply with exactly: geminiwebapp-cli smoke ok"
    created = _run("chats", "new", *common, "--text", prompt, "--timeout", "120", "--dry-run")
    _assert_dry_run(created)

    listed = _run("chats", "list", *common, "--limit", "5")
    assert isinstance(listed.get("chats"), list)

    read = _run("chats", "read", *common, "1", "--limit", "10")
    assert isinstance(read.get("messages"), list)

    follow_up = _run("chats", "send", *common, "1", "--text", "Reply with exactly: follow-up ok", "--timeout", "120", "--dry-run")
    _assert_dry_run(follow_up)


@pytest.mark.skipif(not RUN_LIVE, reason=LIVE_SKIP_REASON)
def test_live_chats_tools_smoke():
    common = _session_args()
    _assert_authenticated(common)

    result = _run("chats", "tools", *common)
    assert result.get("ok") is True
    options = result.get("options") or []
    assert isinstance(options, list)
    assert any(option.get("label") == "Create image" for option in options)
    assert any(option.get("tool") == "create-image" for option in options)


@pytest.mark.skipif(not RUN_LIVE, reason=LIVE_SKIP_REASON)
@pytest.mark.skipif(not LIVE_MUSIC_CHAT, reason="set GEMINIWEBAPP_CLI_LIVE_MUSIC_CHAT to an existing Gemini music chat id or URL")
def test_live_chats_music_download_smoke(tmp_path: Path):
    common = _session_args()
    _assert_authenticated(common)

    result = _run("chats", "music", *common, LIVE_MUSIC_CHAT, "--output-dir", str(tmp_path))
    assert result.get("ok") is True
    music = result.get("music") or []
    assert music, result
    first = music[0]
    saved = Path(first.get("path") or "")
    assert saved.exists()
    assert saved.stat().st_size > 0
    assert str(saved).startswith(str(tmp_path))
    assert str(first.get("content_type") or "").startswith("audio/")


@pytest.mark.skipif(not RUN_LIVE, reason=LIVE_SKIP_REASON)
@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("flash-lite", "Flash-Lite"),
        ("flash", "Flash"),
        ("pro", "Pro"),
    ],
)
def test_live_model_selection_dry_run(model: str, expected: str):
    common = _session_args()
    _assert_authenticated(common)

    created = _run(
        "chats",
        "new",
        *common,
        "--text",
        f"Dry-run smoke test for Gemini {expected} model selection.",
        "--model",
        model,
        "--timeout",
        "120",
        "--dry-run",
    )
    _assert_dry_run(created)
    assert created.get("model") == expected
    assert (created.get("plus_options") or {}).get("tools") == []


@pytest.mark.skipif(not RUN_LIVE, reason=LIVE_SKIP_REASON)
@pytest.mark.parametrize(
    ("model", "expected_model"),
    [
        ("flash", "Flash"),
        ("pro", "Pro"),
    ],
)
def test_live_deep_research_model_and_file_dry_run(tmp_path: Path, model: str, expected_model: str):
    common = _session_args()
    _assert_authenticated(common)
    research_file = _research_file(tmp_path)

    created = _run(
        "chats",
        "new",
        *common,
        "--text",
        "Dry-run Deep Research option coverage. Do not submit this prompt.",
        "--tool",
        "deep-research",
        "--model",
        model,
        "--file",
        str(research_file),
        "--dry-run",
    )
    _assert_dry_run(created)
    assert created.get("model") == expected_model
    assert (created.get("plus_options") or {}).get("tools") == ["Deep Research"]
    assert str(research_file) in ((created.get("plus_options") or {}).get("files") or [])


@pytest.mark.skipif(not RUN_LIVE, reason=LIVE_SKIP_REASON)
def test_live_deep_research_default_model_dry_run():
    common = _session_args()
    _assert_authenticated(common)

    created = _run(
        "chats",
        "new",
        *common,
        "--text",
        "Dry-run Deep Research default model coverage. Do not submit this prompt.",
        "--tool",
        "deep-research",
        "--dry-run",
    )
    _assert_dry_run(created)
    assert created.get("model") == "Flash"
    assert (created.get("plus_options") or {}).get("tools") == ["Deep Research"]


@pytest.mark.skipif(not RUN_LIVE, reason=LIVE_SKIP_REASON)
def test_live_plus_option_escape_hatch_dry_run():
    common = _session_args()
    _assert_authenticated(common)

    created = _run(
        "chats",
        "new",
        *common,
        "--text",
        "Dry-run arbitrary plus-option coverage. Do not submit this prompt.",
        "--plus-option",
        "Deep Research",
        "--model",
        "flash",
        "--dry-run",
    )
    _assert_dry_run(created)
    assert created.get("model") == "Flash"
    assert (created.get("plus_options") or {}).get("tools") == ["Deep Research"]


@pytest.mark.skipif(not RUN_LIVE, reason=LIVE_SKIP_REASON)
@pytest.mark.skipif(not NUC_IMAGE.exists(), reason=f"missing live test image: {NUC_IMAGE}")
def test_live_create_image_from_file_nuc_gpu_smoke(tmp_path: Path):
    common = _session_args()
    _assert_authenticated(common)

    created = _run(
        "chats",
        "new",
        *common,
        "--tool",
        "create-image",
        "--text",
        _image_prompt(),
        "--file",
        str(NUC_IMAGE),
        "--output-dir",
        str(tmp_path),
        "--timeout",
        "300",
        "--dry-run",
    )
    _assert_dry_run(created)
    assert (created.get("plus_options") or {}).get("tools") == ["Create image"]
    assert str(NUC_IMAGE) in ((created.get("plus_options") or {}).get("files") or [])


@pytest.mark.skipif(not RUN_LIVE, reason=LIVE_SKIP_REASON)
@pytest.mark.skipif(not NUC_IMAGE.exists(), reason=f"missing live test image: {NUC_IMAGE}")
@pytest.mark.parametrize(
    ("aspect_ratio", "expected"),
    [
        ("landscape", "Landscape (16:9)"),
        ("portrait", "Portrait (9:16)"),
    ],
)
def test_live_create_video_from_file_aspect_ratio_dry_run(tmp_path: Path, aspect_ratio: str, expected: str):
    common = _session_args()
    _assert_authenticated(common)

    created = _run(
        "chats",
        "new",
        *common,
        "--tool",
        "create-video",
        "--aspect-ratio",
        aspect_ratio,
        "--text",
        "Create a 5 second video of this pc in the image",
        "--file",
        str(NUC_IMAGE),
        "--output-dir",
        str(tmp_path),
        "--timeout",
        "900",
        "--dry-run",
    )
    _assert_dry_run(created)
    assert (created.get("plus_options") or {}).get("tools") == ["Create video"]
    assert created.get("aspect_ratio") == expected
    assert str(NUC_IMAGE) in ((created.get("plus_options") or {}).get("files") or [])
