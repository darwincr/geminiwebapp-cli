from __future__ import annotations

import os
from pathlib import Path

GEMINI_BASE_URL = "https://gemini.google.com"
GEMINI_APP_URL = f"{GEMINI_BASE_URL}/app"

BROWSER_DEFAULT_TIMEOUT_MS = 30_000
BROWSER_WIDTH = 1920
BROWSER_HEIGHT = 1080
BROWSER_LOGIN_TIMEOUT_MS = 60_000
HUMAN_TYPE_DELAY_MS = 55
HUMAN_MOUSE_MAX_TIME_S = 0.225
DEFAULT_MIN_PACE_S = 0.8
DEFAULT_MAX_PACE_S = 1.8
WORKER_IDLE_TIMEOUT_S = 900
DEFAULT_RESPONSE_TIMEOUT_S = 180
DEFAULT_DEEP_RESEARCH_TIMEOUT_S = 900
DEFAULT_DEEP_RESEARCH_POLL_INTERVAL_S = 30


def geminiwebapp_cli_home() -> Path:
    return Path(os.environ.get("GEMINIWEBAPP_CLI_HOME") or Path.home() / ".geminiwebapp-cli")


def browser_headless() -> bool:
    return os.environ.get("GEMINIWEBAPP_CLI_HEADLESS", "").lower() in {"1", "true", "yes", "on"}


def load_dotenv_file(path: Path | None = None) -> dict[str, str]:
    """Load KEY=VALUE pairs from .env without overriding existing env vars."""
    env_path = path or Path.cwd() / ".env"
    if not env_path.exists():
        return {}

    loaded = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_dotenv_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if key in os.environ:
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    elif " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return key, value
