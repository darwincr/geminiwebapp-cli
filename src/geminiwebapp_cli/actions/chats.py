from __future__ import annotations

import re
import shlex
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from math import ceil
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from geminiwebapp_cli.actions.auth import ensure_logged_in, ensure_prompt_ready
from geminiwebapp_cli.browser import clean_url, first_visible, goto_domcontentloaded, safe_attr, visible_text
from geminiwebapp_cli.conf import GEMINI_APP_URL, GEMINI_BASE_URL
from geminiwebapp_cli.exceptions import ChatNotFoundError, ElementNotFoundError, GeminiUnavailableError, ImageDownloadError, MusicDownloadError, ResponseTimeoutError, VideoDownloadError

CHAT_LINK_RE = re.compile(r"/app/([^/?#]+)")

PROMPT_LOCATORS = [
    lambda p: p.locator('rich-textarea textarea'),
    lambda p: p.locator('textarea[aria-label*="Enter a prompt" i]'),
    lambda p: p.locator('textarea[placeholder*="Enter a prompt" i]'),
    lambda p: p.locator('textarea'),
    lambda p: p.locator('[contenteditable="true"][role="textbox"]'),
    lambda p: p.locator('div[role="textbox"][contenteditable="true"]'),
]
SEND_BUTTON_LOCATORS = [
    lambda p: p.get_by_role("button", name=re.compile(r"^(send|submit)$", re.I)),
    lambda p: p.locator('button[aria-label*="Send" i]'),
    lambda p: p.locator('[role="button"][aria-label*="Send" i]'),
    lambda p: p.locator('button:has(mat-icon:has-text("send"))'),
]
STOP_BUTTON_LOCATORS = [
    lambda p: p.get_by_role("button", name=re.compile("stop", re.I)),
    lambda p: p.locator('button[aria-label*="Stop" i]'),
    lambda p: p.locator('[role="button"][aria-label*="Stop" i]'),
]
START_RESEARCH_LOCATORS = [
    lambda p: p.get_by_role("button", name=re.compile(r"start research", re.I)),
    lambda p: p.locator('button[aria-label*="Start research" i]'),
    lambda p: p.locator('button').filter(has_text=re.compile(r"start research", re.I)),
]
NEW_CHAT_LOCATORS = [
    lambda p: p.get_by_role("button", name=re.compile("new chat", re.I)),
    lambda p: p.get_by_role("link", name=re.compile("new chat", re.I)),
    lambda p: p.locator('a[href="/app"]'),
    lambda p: p.locator('a[href="/app/"]'),
    lambda p: p.locator('[aria-label*="New chat" i]'),
]
MESSAGE_CONTAINER_LOCATORS = [
    lambda p: p.locator('message-content'),
    lambda p: p.locator('[data-message-author-role]'),
    lambda p: p.locator('[class*="conversation"] [class*="message"]'),
    lambda p: p.locator('main markdown, main .markdown'),
]
PLUS_MENU_LOCATORS = [
    lambda p: p.locator('button[aria-label*="Upload and tools" i]'),
    lambda p: p.locator('button[aria-label*="Open" i][aria-label*="upload" i]'),
    lambda p: p.locator('button[aria-label*="Add" i][aria-label*="upload" i]'),
    lambda p: p.locator('button[aria-label*="Attach" i]'),
    lambda p: p.locator('button:has(mat-icon[fonticon="plus"])'),
    lambda p: p.locator('button:has(mat-icon[data-mat-icon-name="plus"])'),
    lambda p: p.locator('button:has(mat-icon[fonticon="add"])'),
    lambda p: p.locator('button:has(mat-icon[data-mat-icon-name="add"])'),
]
MODEL_MENU_LOCATORS = [
    lambda p: p.get_by_role("button", name=re.compile(r"model|gemini|flash|pro|lite", re.I)),
    lambda p: p.locator('button[aria-label*="model" i]'),
    lambda p: p.locator('button[aria-label*="Gemini" i]'),
    lambda p: p.locator('button').filter(has_text=re.compile(r"flash|pro|lite", re.I)),
    lambda p: p.locator('[role="combobox"][aria-label*="model" i]'),
]

TOOL_LABELS = {
    "create-image": "Create image",
    "create-video": "Create video",
    "deep-research": "Deep Research",
    "create-music": "Create music",
}

VIDEO_ASPECT_RATIO_LABELS = {
    "landscape": "Landscape (16:9)",
    "16:9": "Landscape (16:9)",
    "16-9": "Landscape (16:9)",
    "portrait": "Portrait (9:16)",
    "9:16": "Portrait (9:16)",
    "9-16": "Portrait (9:16)",
}
MODEL_LABELS = {
    "flash-lite": "Flash-Lite",
    "flashlite": "Flash-Lite",
    "lite": "Flash-Lite",
    "flash": "Flash",
    "pro": "Pro",
}


def chat_url(value: str | None = None) -> str:
    if not value:
        return GEMINI_APP_URL
    target = value.strip()
    if target.startswith("http://") or target.startswith("https://"):
        return target
    target = target.lstrip("/")
    if target == "app" or target.startswith("app/"):
        return f"{GEMINI_BASE_URL}/{target}"
    return f"{GEMINI_APP_URL}/{target}"


def chat_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = CHAT_LINK_RE.search(url)
    return match.group(1) if match else None


def list_chats(session, *, limit: int = 20) -> dict:
    ensure_logged_in(session)
    page = session.page
    _open_sidebar_if_needed(page)
    chats = _collect_chats(page, limit=limit)
    return {"ok": True, "url": page.url, "chats": chats}


def list_plus_options(session) -> dict:
    ensure_prompt_ready(session)
    page = session.page
    _open_plus_menu(page)
    options = _visible_plus_menu_options(page)
    _dismiss_open_overlay(page)
    return {"ok": True, "url": clean_url(page.url), "options": options}


def new_chat(
    session,
    text: str,
    *,
    timeout: int,
    tools: Sequence[str] = (),
    files: Sequence[Path] = (),
    model: str | None = None,
    plus_options: Sequence[str] = (),
    wait_research_complete: bool = False,
    poll_interval: int = 2,
    output_dir: Path | None = None,
    aspect_ratio: str | None = None,
    dry_run: bool = False,
) -> dict:
    ensure_prompt_ready(session)
    page = session.page
    selected_model = _select_model_for_request(page, model=model, tools=tools)
    before = _message_signature(page)
    before_image_count = len(_visible_chat_images(page))
    before_video_count = len(_visible_chat_videos(page))
    before_music_count = len(_visible_chat_music(page))
    before_failure = _visible_generation_failure(page)
    selected = _apply_plus_options(page, tools=tools, files=files, plus_options=plus_options)
    selected_aspect_ratio = _select_video_aspect_ratio_if_needed(page, selected=selected, aspect_ratio=aspect_ratio)
    if dry_run:
        return _dry_run_result(page, text=text, selected_model=selected_model, selected=selected, selected_aspect_ratio=selected_aspect_ratio)
    _submit_prompt(page, text)
    saves_images = _should_save_generated_images(selected, output_dir)
    saves_videos = _should_save_generated_videos(selected, output_dir)
    saves_music = _should_save_generated_music(selected, output_dir)
    if saves_images:
        response_text = _wait_for_image_generation(page, before_image_count=before_image_count, before_failure=before_failure, timeout=timeout)
    elif saves_videos:
        response_text = _wait_for_video_generation(page, before_video_count=before_video_count, before_failure=before_failure, timeout=timeout)
    elif saves_music:
        response_text = _wait_for_music_generation(page, before_music_count=before_music_count, before_failure=before_failure, timeout=timeout)
    else:
        response_text = _wait_for_response(page, before_signature=before, timeout=timeout)
    research = _confirm_deep_research_if_needed(page, response_text, selected=selected, timeout=timeout, wait_complete=wait_research_complete, poll_interval=poll_interval)
    response_text = _response_text_for_research(research, response_text)
    response = _response_payload(response_text)
    if research is not None:
        response["research"] = research
    if saves_images and output_dir is not None and len(_visible_chat_images(page)) > before_image_count:
        response["images"] = _save_visible_chat_images(page, output_dir=output_dir, start_index=before_image_count)
    if saves_videos and output_dir is not None and len(_visible_chat_videos(page)) > before_video_count:
        response["videos"] = _save_visible_chat_videos(page, output_dir=output_dir, start_index=before_video_count)
    if saves_music and output_dir is not None and len(_visible_chat_music(page)) > before_music_count:
        response["music"] = _save_visible_chat_music(page, output_dir=output_dir, start_index=before_music_count)
    return {
        "ok": True,
        "chat": {"id": chat_id_from_url(page.url), "url": clean_url(page.url)},
        "prompt": text,
        "model": selected_model,
        "plus_options": selected,
        "aspect_ratio": selected_aspect_ratio,
        "response": response,
    }


def send_to_chat(
    session,
    chat: str,
    text: str,
    *,
    timeout: int,
    tools: Sequence[str] = (),
    files: Sequence[Path] = (),
    model: str | None = None,
    plus_options: Sequence[str] = (),
    wait_research_complete: bool = False,
    poll_interval: int = 2,
    output_dir: Path | None = None,
    aspect_ratio: str | None = None,
    dry_run: bool = False,
) -> dict:
    ensure_logged_in(session)
    page = session.page
    opened = _open_chat(page, chat)
    selected_model = _select_model_for_request(page, model=model, tools=tools)
    before = _message_signature(page)
    before_image_count = len(_visible_chat_images(page))
    before_video_count = len(_visible_chat_videos(page))
    before_music_count = len(_visible_chat_music(page))
    before_failure = _visible_generation_failure(page)
    selected = _apply_plus_options(page, tools=tools, files=files, plus_options=plus_options)
    selected_aspect_ratio = _select_video_aspect_ratio_if_needed(page, selected=selected, aspect_ratio=aspect_ratio)
    if dry_run:
        result = _dry_run_result(page, text=text, selected_model=selected_model, selected=selected, selected_aspect_ratio=selected_aspect_ratio)
        result["chat"] = opened
        return result
    _submit_prompt(page, text)
    saves_images = _should_save_generated_images(selected, output_dir)
    saves_videos = _should_save_generated_videos(selected, output_dir)
    saves_music = _should_save_generated_music(selected, output_dir)
    if saves_images:
        response_text = _wait_for_image_generation(page, before_image_count=before_image_count, before_failure=before_failure, timeout=timeout)
    elif saves_videos:
        response_text = _wait_for_video_generation(page, before_video_count=before_video_count, before_failure=before_failure, timeout=timeout)
    elif saves_music:
        response_text = _wait_for_music_generation(page, before_music_count=before_music_count, before_failure=before_failure, timeout=timeout)
    else:
        response_text = _wait_for_response(page, before_signature=before, timeout=timeout)
    research = _confirm_deep_research_if_needed(page, response_text, selected=selected, timeout=timeout, wait_complete=wait_research_complete, poll_interval=poll_interval)
    response_text = _response_text_for_research(research, response_text)
    response = _response_payload(response_text)
    if research is not None:
        response["research"] = research
    if saves_images and output_dir is not None and len(_visible_chat_images(page)) > before_image_count:
        response["images"] = _save_visible_chat_images(page, output_dir=output_dir, start_index=before_image_count)
    if saves_videos and output_dir is not None and len(_visible_chat_videos(page)) > before_video_count:
        response["videos"] = _save_visible_chat_videos(page, output_dir=output_dir, start_index=before_video_count)
    if saves_music and output_dir is not None and len(_visible_chat_music(page)) > before_music_count:
        response["music"] = _save_visible_chat_music(page, output_dir=output_dir, start_index=before_music_count)
    return {
        "ok": True,
        "chat": opened,
        "prompt": text,
        "model": selected_model,
        "plus_options": selected,
        "aspect_ratio": selected_aspect_ratio,
        "response": response,
    }


def read_chat(session, chat: str, *, limit: int = 20) -> dict:
    ensure_logged_in(session)
    page = session.page
    opened = _open_chat(page, chat)
    _scroll_messages_up(page, scrolls=max(1, ceil(max(limit, 1) / 12)))
    messages = _visible_messages(page, limit=limit)
    result = {"ok": True, "chat": opened, "messages": messages, "url": page.url}
    research = _extract_deep_research_report(page)
    if research is not None:
        result["messages"] = _without_research_messages(messages, research)
        result["research"] = research
    return result


def research_status(session, chat: str, *, wait: bool = False, timeout: int = 180, poll_interval: int = 2) -> dict:
    ensure_logged_in(session)
    page = session.page
    deadline = time.monotonic() + timeout
    opened = _open_chat(page, chat)
    _scroll_messages_down(page)
    research = _extract_research_status(page)
    if wait and research.get("status") == "in_progress":
        remaining = max(1, int(deadline - time.monotonic()))
        try:
            research = _wait_for_deep_research_report(page, timeout=remaining, plan=research.get("plan") or "", chat=opened, poll_interval=poll_interval)
        except ResponseTimeoutError as exc:
            latest = str(exc).split("latest status:", 1)[1].strip() if "latest status:" in str(exc) else research.get("text", "")
            raise ResponseTimeoutError(f"Deep Research report did not complete within {timeout} seconds; latest status: {latest}") from exc
    return {"ok": True, "chat": opened, "research": research, "url": page.url}


def chat_status(session, chat: str, *, wait: bool = False, timeout: int = 180, poll_interval: int = 2) -> dict:
    ensure_logged_in(session)
    page = session.page
    deadline = time.monotonic() + timeout
    opened = _open_chat(page, chat)
    _scroll_messages_down(page)
    research = _extract_research_status(page)
    if research.get("status") != "not_found":
        if wait and research.get("status") == "in_progress":
            remaining = max(1, int(deadline - time.monotonic()))
            try:
                research = _wait_for_deep_research_report(page, timeout=remaining, plan=research.get("plan") or "", chat=opened, poll_interval=poll_interval)
            except ResponseTimeoutError as exc:
                latest = str(exc).split("latest status:", 1)[1].strip() if "latest status:" in str(exc) else research.get("text", "")
                raise ResponseTimeoutError(f"Deep Research report did not complete within {timeout} seconds; latest status: {latest}") from exc
        return {"ok": True, "chat": opened, "type": "deep_research", "research": research, "url": page.url}

    messages = _visible_messages(page, limit=20)
    return {
        "ok": True,
        "chat": opened,
        "type": "chat",
        "status": "available" if messages else "empty",
        "messages": messages,
        "media": {
            "images": len(_visible_chat_images(page)),
            "videos": len(_visible_chat_videos(page)),
            "music": len(_visible_chat_music(page)),
        },
        "url": page.url,
    }


def save_chat_images(session, chat: str, *, output_dir: Path) -> dict:
    ensure_logged_in(session)
    page = session.page
    opened = _open_chat(page, chat)
    saved = _save_visible_chat_images(page, output_dir=output_dir)
    return {"ok": True, "chat": opened, "images": saved, "output_dir": str(output_dir), "url": page.url}


def save_chat_videos(session, chat: str, *, output_dir: Path) -> dict:
    ensure_logged_in(session)
    page = session.page
    opened = _open_chat(page, chat)
    saved = _save_visible_chat_videos(page, output_dir=output_dir)
    return {"ok": True, "chat": opened, "videos": saved, "output_dir": str(output_dir), "url": page.url}


def save_chat_music(session, chat: str, *, output_dir: Path) -> dict:
    ensure_logged_in(session)
    page = session.page
    opened = _open_chat(page, chat)
    saved = _save_visible_chat_music(page, output_dir=output_dir)
    return {"ok": True, "chat": opened, "music": saved, "output_dir": str(output_dir), "url": page.url}


def _dry_run_result(page, *, text: str, selected_model: str | None, selected: dict, selected_aspect_ratio: str | None) -> dict:
    return {
        "ok": True,
        "dry_run": True,
        "submitted": False,
        "chat": {"id": chat_id_from_url(page.url), "url": clean_url(page.url)},
        "prompt": text,
        "model": selected_model,
        "plus_options": selected,
        "aspect_ratio": selected_aspect_ratio,
        "response": {"text": "Dry run completed before submission", "done": False},
    }


def _save_visible_chat_images(page, *, output_dir: Path, start_index: int = 0) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    images = _visible_chat_images(page)[start_index:]
    saved = []
    for index, image in enumerate(images, start=1):
        download = _download_full_size_image(page, image_index=start_index + index - 1)
        ext = _download_extension(download.suggested_filename)
        path = _available_image_path(output_dir, index, ext)
        download.save_as(str(path))
        saved.append(
            {
                "path": str(path),
                "source": image["src"],
                "alt": image.get("alt") or "",
                "width": image.get("width"),
                "height": image.get("height"),
                "content_type": _content_type_from_extension(ext),
                "suggested_filename": download.suggested_filename,
                "bytes": path.stat().st_size,
            }
        )
    return saved


def _open_new_chat(page) -> None:
    locator = first_visible(page, NEW_CHAT_LOCATORS, timeout_ms=2500)
    if locator is not None:
        locator.click()
        try:
            page.wait_for_load_state("domcontentloaded")
        except PlaywrightTimeoutError:
            pass
        return
    goto_domcontentloaded(page, GEMINI_APP_URL)


def _open_chat(page, chat: str) -> dict:
    clicked_sidebar = False
    if chat.isdigit():
        _open_sidebar_if_needed(page)
        chats = _collect_chats(page, limit=max(int(chat), 20))
        index = int(chat) - 1
        if index < 0 or index >= len(chats):
            raise ChatNotFoundError(f"Could not resolve chat index {chat}; only found {len(chats)} visible chat(s)")
        url = chats[index].get("url")
        clicked_sidebar = _click_sidebar_chat(page, url)
    else:
        url = chat_url(chat)

    if not url:
        raise ChatNotFoundError(f"Could not resolve chat {chat!r}")
    target_id = chat_id_from_url(url)
    if not clicked_sidebar:
        goto_domcontentloaded(page, url)
    try:
        page.wait_for_url(re.compile(r".*/app(/.*)?"), timeout=15000)
    except PlaywrightTimeoutError:
        pass
    _wait_for_chat_content(page, timeout_ms=15000, accept_prompt=target_id is None)
    if not _has_chat_content(page, accept_prompt=target_id is None) and not clicked_sidebar:
        goto_domcontentloaded(page, GEMINI_APP_URL)
        page.wait_for_timeout(1000)
        _open_sidebar_if_needed(page)
        if _click_sidebar_chat(page, url):
            _wait_for_chat_content(page, timeout_ms=15000, accept_prompt=target_id is None)
    if not _has_chat_content(page, accept_prompt=target_id is None):
        raise ChatNotFoundError(f"Could not open Gemini chat {chat!r}; current URL: {page.url}")
    return {"id": chat_id_from_url(page.url) or chat_id_from_url(url), "url": clean_url(page.url)}


def _click_sidebar_chat(page, url: str | None) -> bool:
    if not url:
        return False
    chat_id = chat_id_from_url(url)
    if not chat_id:
        return False
    deadline = time.monotonic() + 12
    selector = f'a[href$="/app/{chat_id}"], a[href*="/app/{chat_id}"]'
    while time.monotonic() < deadline:
        try:
            link = page.locator(selector).first
            link.wait_for(state="visible", timeout=1000)
            link.click(timeout=5000)
            page.wait_for_load_state("domcontentloaded")
            return True
        except (PlaywrightTimeoutError, PlaywrightError):
            page.wait_for_timeout(500)
    return False


def _wait_for_chat_content(page, *, timeout_ms: int, accept_prompt: bool = True) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if _has_chat_content(page, accept_prompt=accept_prompt):
            return
        page.wait_for_timeout(500)


def _has_chat_content(page, *, accept_prompt: bool = True) -> bool:
    if _extract_deep_research_report(page) is not None or _visible_messages(page, limit=1):
        return True
    return accept_prompt and first_visible(page, PROMPT_LOCATORS, timeout_ms=500) is not None


def _visible_chat_images(page) -> list[dict]:
    try:
        return page.evaluate(
            r"""
            () => {
              const visible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width >= 128 && rect.height >= 128;
              };
              const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
              const images = [];
              const seen = new Set();
              for (const img of document.querySelectorAll('main img, [role="main"] img, img')) {
                if (!visible(img)) continue;
                const src = img.currentSrc || img.src || '';
                if (!src || seen.has(src)) continue;
                const width = img.naturalWidth || Math.round(img.getBoundingClientRect().width);
                const height = img.naturalHeight || Math.round(img.getBoundingClientRect().height);
                if (width < 256 || height < 256) continue;
                const alt = clean(img.alt || img.getAttribute('aria-label') || '');
                const className = String(img.className || '').toLowerCase();
                const parentText = clean(img.closest('[aria-label]')?.getAttribute('aria-label') || '');
                if (/avatar|profile|account|logo|icon|user/.test(className)) continue;
                if (/avatar|profile|account|logo|user/.test(`${alt} ${parentText}`.toLowerCase())) continue;
                seen.add(src);
                images.push({ src, alt, width, height });
              }
              return images;
            }
            """
        )
    except PlaywrightError:
        return []


def _visible_chat_videos(page) -> list[dict]:
    try:
        return page.evaluate(
            r"""
            () => {
              const visible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width >= 128 && rect.height >= 128;
              };
              const videos = [];
              const seen = new Set();
              for (const video of document.querySelectorAll('main video, [role="main"] video, video')) {
                if (!visible(video)) continue;
                const src = video.currentSrc || video.src || video.querySelector('source')?.src || '';
                const key = src || `${video.getBoundingClientRect().x}:${video.getBoundingClientRect().y}`;
                if (seen.has(key)) continue;
                const rect = video.getBoundingClientRect();
                seen.add(key);
                videos.push({
                  src,
                  width: video.videoWidth || Math.round(rect.width),
                  height: video.videoHeight || Math.round(rect.height),
                  duration: Number.isFinite(video.duration) ? video.duration : null,
                  poster: video.poster || '',
                });
              }
              return videos;
            }
            """
        )
    except PlaywrightError:
        return []


def _visible_chat_music(page) -> list[dict]:
    try:
        return page.evaluate(
            r"""
            () => {
              const visible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0;
              };
              const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
              const tracks = [];
              const seen = new Set();

              for (const audio of document.querySelectorAll('main audio, [role="main"] audio, audio')) {
                if (!visible(audio)) continue;
                const src = audio.currentSrc || audio.src || audio.querySelector('source')?.src || '';
                const key = src || `${audio.getBoundingClientRect().x}:${audio.getBoundingClientRect().y}`;
                if (seen.has(key)) continue;
                seen.add(key);
                tracks.push({
                  src,
                  duration: Number.isFinite(audio.duration) ? audio.duration : null,
                  title: clean(audio.closest('[aria-label]')?.getAttribute('aria-label') || audio.closest('[role="group"], mat-card, div')?.innerText || ''),
                });
              }

              if (tracks.length) return tracks;

              const candidates = [...document.querySelectorAll('main button, main [role="button"], [role="main"] button, [role="main"] [role="button"]')];
              for (const button of candidates) {
                if (!visible(button)) continue;
                const label = clean(`${button.getAttribute('aria-label') || ''} ${button.innerText || button.textContent || ''}`);
                if (!/download/i.test(label) || !/(music|audio|song|track)/i.test(label)) continue;
                const key = `${button.getBoundingClientRect().x}:${button.getBoundingClientRect().y}:${label}`;
                if (seen.has(key)) continue;
                seen.add(key);
                tracks.push({ src: '', duration: null, title: label });
              }

              return tracks;
            }
            """
        )
    except PlaywrightError:
        return []


def _should_save_generated_images(selected: dict, output_dir: Path | None) -> bool:
    return output_dir is not None and "Create image" in (selected.get("tools") or [])


def _should_save_generated_videos(selected: dict, output_dir: Path | None) -> bool:
    return output_dir is not None and "Create video" in (selected.get("tools") or [])


def _should_save_generated_music(selected: dict, output_dir: Path | None) -> bool:
    return output_dir is not None and "Create music" in (selected.get("tools") or [])


def _video_aspect_ratio_label(aspect_ratio: str) -> str:
    key = aspect_ratio.strip().lower().replace("_", "-").replace(" ", "-")
    if key not in VIDEO_ASPECT_RATIO_LABELS:
        valid = ", ".join(["landscape", "portrait", "16:9", "9:16"])
        raise ValueError(f"Unknown video aspect ratio {aspect_ratio!r}; valid values: {valid}")
    return VIDEO_ASPECT_RATIO_LABELS[key]


def _select_video_aspect_ratio_if_needed(page, *, selected: dict, aspect_ratio: str | None) -> str | None:
    if aspect_ratio is None:
        return None
    if "Create video" not in (selected.get("tools") or []):
        raise ValueError("--aspect-ratio can only be used with --tool create-video")
    label = _video_aspect_ratio_label(aspect_ratio)
    item = page.get_by_role("menuitemradio", name=label).first
    try:
        item.wait_for(state="visible", timeout=1000)
    except PlaywrightError:
        _open_video_options_menu(page)
        item = page.get_by_role("menuitemradio", name=label).first
        try:
            item.wait_for(state="visible", timeout=5000)
        except PlaywrightError as exc:
            raise ElementNotFoundError(f"Could not find Gemini video aspect ratio option {label!r}") from exc
    checked = safe_attr(item, "aria-checked") == "true"
    if not checked:
        item.click()
        page.wait_for_timeout(500)
    _dismiss_open_overlay(page)
    return label


def _open_video_options_menu(page) -> None:
    try:
        handle = page.evaluate_handle(
            r"""
            () => {
              const visible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0 && rect.y > window.innerHeight * 0.45;
              };
              const text = (node) => `${node.getAttribute('aria-label') || ''} ${node.innerText || ''}`;
              const controls = [...document.querySelectorAll('button,[role="button"]')];
              return controls.find((node) => visible(node) && /Landscape \(16:9\)|Portrait \(9:16\)|aspect ratio/i.test(text(node))) || null;
            }
            """
        )
        element = handle.as_element()
    except PlaywrightError as exc:
        raise ElementNotFoundError("Could not inspect Gemini video aspect ratio control") from exc
    if element is None:
        raise ElementNotFoundError("Could not find Gemini video aspect ratio/options menu")
    element.click()
    page.wait_for_timeout(500)


def _wait_for_image_generation(page, *, before_image_count: int, before_failure: str = "", timeout: int) -> str:
    deadline = time.monotonic() + timeout
    last_text = ""
    while time.monotonic() < deadline:
        images = _visible_chat_images(page)[before_image_count:]
        if images:
            return f"Saved {len(images)} generated image(s)"
        failure = _visible_generation_failure(page)
        if failure and failure != before_failure:
            return failure
        messages = _visible_messages(page, limit=80)
        model_messages = [m for m in messages if m.get("role") != "user" and m.get("text")]
        if model_messages:
            last_text = model_messages[-1]["text"]
        stop_visible = first_visible(page, STOP_BUTTON_LOCATORS, timeout_ms=250) is not None
        if last_text and not stop_visible and re.search(r"couldn.t|unable|can.t|sorry|failed", last_text, re.I):
            return last_text
        page.wait_for_timeout(1000)
    if last_text:
        raise ResponseTimeoutError(f"Gemini image generation did not finish within {timeout} seconds; latest response: {last_text[:240]}")
    raise ResponseTimeoutError(f"Gemini did not produce a visible generated image within {timeout} seconds")


def _wait_for_video_generation(page, *, before_video_count: int, before_failure: str = "", timeout: int) -> str:
    deadline = time.monotonic() + timeout
    last_text = ""
    while time.monotonic() < deadline:
        videos = _visible_chat_videos(page)[before_video_count:]
        if videos:
            return f"Saved {len(videos)} generated video(s)"
        failure = _visible_generation_failure(page)
        if failure and failure != before_failure:
            return failure
        messages = _visible_messages(page, limit=80)
        model_messages = [m for m in messages if m.get("role") != "user" and m.get("text")]
        if model_messages:
            last_text = model_messages[-1]["text"]
        stop_visible = first_visible(page, STOP_BUTTON_LOCATORS, timeout_ms=250) is not None
        if last_text and not stop_visible and re.search(r"couldn.t|unable|can.t|sorry|failed|not available", last_text, re.I):
            return last_text
        page.wait_for_timeout(2000)
    if last_text:
        raise ResponseTimeoutError(f"Gemini video generation did not finish within {timeout} seconds; latest response: {last_text[:240]}")
    raise ResponseTimeoutError(f"Gemini did not produce a visible generated video within {timeout} seconds")


def _wait_for_music_generation(page, *, before_music_count: int, before_failure: str = "", timeout: int) -> str:
    deadline = time.monotonic() + timeout
    last_text = ""
    while time.monotonic() < deadline:
        music = _visible_chat_music(page)[before_music_count:]
        if music:
            return f"Saved {len(music)} generated music track(s)"
        failure = _visible_generation_failure(page)
        if failure and failure != before_failure:
            return failure
        messages = _visible_messages(page, limit=80)
        model_messages = [m for m in messages if m.get("role") != "user" and m.get("text")]
        if model_messages:
            last_text = model_messages[-1]["text"]
        stop_visible = first_visible(page, STOP_BUTTON_LOCATORS, timeout_ms=250) is not None
        if last_text and not stop_visible and re.search(r"couldn.t|unable|can.t|sorry|failed|not available", last_text, re.I):
            return last_text
        page.wait_for_timeout(2000)
    if last_text:
        raise ResponseTimeoutError(f"Gemini music generation did not finish within {timeout} seconds; latest response: {last_text[:240]}")
    raise ResponseTimeoutError(f"Gemini did not produce visible generated music within {timeout} seconds")


def _visible_generation_failure(page) -> str:
    try:
        text = page.evaluate(
            r"""
            () => {
              const visible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0;
              };
              const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
              const selectors = [
                'main [role="alert"]',
                '[role="main"] [role="alert"]',
                '.cdk-overlay-container [role="alert"]',
                'main .error',
                '[role="main"] .error',
                'main div',
                '[role="main"] div'
              ];
              const pattern = /something went wrong|please try again|generation failed|failed to generate|couldn.t generate|unable to generate|can.t generate|not available/i;
              const seen = new Set();
              for (const selector of selectors) {
                for (const node of document.querySelectorAll(selector)) {
                  if (seen.has(node) || !visible(node)) continue;
                  seen.add(node);
                  const text = clean(node.innerText || node.textContent || node.getAttribute('aria-label') || '');
                  if (text && pattern.test(text)) return text;
                }
              }
              return '';
            }
            """
        )
    except PlaywrightError:
        return ""
    return " ".join(str(text or "").split())


def _is_generation_failure(text: str) -> bool:
    return bool(re.search(r"something went wrong|please try again|generation failed|failed to generate|couldn.t generate|unable to generate|can.t generate|not available", text or "", re.I))


def _response_payload(text: str) -> dict:
    payload = {"text": text, "done": not _is_generation_failure(text)}
    if not payload["done"]:
        payload["error"] = {"type": "generation_failed", "message": text}
    return payload


def _save_visible_chat_videos(page, *, output_dir: Path, start_index: int = 0) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    videos = _visible_chat_videos(page)[start_index:]
    saved = []
    for index, video in enumerate(videos, start=1):
        download = _download_generated_video(page, video_index=start_index + index - 1)
        ext = _video_download_extension(download.suggested_filename)
        path = _available_video_path(output_dir, index, ext)
        download.save_as(str(path))
        saved.append(
            {
                "path": str(path),
                "source": video.get("src") or "",
                "poster": video.get("poster") or "",
                "width": video.get("width"),
                "height": video.get("height"),
                "duration": video.get("duration"),
                "content_type": _video_content_type_from_extension(ext),
                "suggested_filename": download.suggested_filename,
                "bytes": path.stat().st_size,
            }
        )
    return saved


def _save_visible_chat_music(page, *, output_dir: Path, start_index: int = 0) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tracks = _visible_chat_music(page)[start_index:]
    saved = []
    for index, track in enumerate(tracks, start=1):
        download = _download_generated_music(page, music_index=start_index + index - 1)
        ext = _music_download_extension(download.suggested_filename)
        path = _available_music_path(output_dir, index, ext)
        download.save_as(str(path))
        saved.append(
            {
                "path": str(path),
                "source": track.get("src") or "",
                "title": track.get("title") or "",
                "duration": track.get("duration"),
                "content_type": _music_content_type_from_extension(ext),
                "suggested_filename": download.suggested_filename,
                "bytes": path.stat().st_size,
            }
        )
    return saved


def _download_generated_video(page, *, video_index: int):
    _dismiss_open_overlay(page)
    labels = [
        re.compile(r"download.*video", re.I),
        re.compile(r"download", re.I),
    ]
    errors = []
    for label in labels:
        buttons = page.get_by_label(label)
        try:
            button = buttons.nth(video_index)
            button.scroll_into_view_if_needed(timeout=5000)
            with page.expect_download(timeout=45000) as download_info:
                button.click(timeout=10000)
            return download_info.value
        except PlaywrightError as exc:
            errors.append(str(exc))
            continue
    raise VideoDownloadError(f"Could not download generated video {video_index + 1}: {'; '.join(errors[-2:])}")


def _download_generated_music(page, *, music_index: int):
    _dismiss_open_overlay(page)
    labels = [
        re.compile(r"download track", re.I),
        re.compile(r"download.*(music|audio|song|track)", re.I),
        re.compile(r"(music|audio|song|track).*download", re.I),
        re.compile(r"download", re.I),
    ]
    errors = []
    for label in labels:
        buttons = page.get_by_label(label)
        try:
            button = buttons.nth(music_index)
            button.scroll_into_view_if_needed(timeout=5000)
            button.click(timeout=10000, force=True)
            page.wait_for_timeout(500)
            return _download_music_audio_only(page)
        except PlaywrightError as exc:
            errors.append(str(exc))
            continue
    raise MusicDownloadError(f"Could not download generated music track {music_index + 1}: {'; '.join(errors[-2:])}")


def _download_music_audio_only(page):
    locators = [
        lambda p: p.get_by_role("menuitem", name=re.compile(r"audio only", re.I)),
        lambda p: p.get_by_role("button", name=re.compile(r"audio only", re.I)),
        lambda p: p.get_by_text(re.compile(r"audio only", re.I)),
        lambda p: p.locator('[role="menuitem"], button, [role="button"]').filter(has_text=re.compile(r"audio only", re.I)),
    ]
    option = first_visible(page, locators, timeout_ms=5000)
    if option is None:
        raise MusicDownloadError("Could not find Gemini music download option 'Audio only'")
    with page.expect_download(timeout=45000) as download_info:
        option.click(timeout=10000, force=True)
    return download_info.value


def _dismiss_open_overlay(page) -> None:
    try:
        backdrop = page.locator(".cdk-overlay-backdrop.cdk-overlay-backdrop-showing").first
        if backdrop.count() and backdrop.is_visible(timeout=250):
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except PlaywrightError:
        pass


def _download_full_size_image(page, *, image_index: int):
    buttons = page.get_by_label("Download full-sized image")
    errors = []
    for _ in range(3):
        try:
            button = buttons.nth(image_index)
            button.scroll_into_view_if_needed(timeout=5000)
            page.wait_for_timeout(10000)
            with page.expect_download(timeout=30000) as download_info:
                button.click(timeout=5000)
            return download_info.value
        except PlaywrightError as exc:
            errors.append(str(exc))
    raise ImageDownloadError(f"Could not download full-sized generated image {image_index + 1}: {'; '.join(errors[-2:])}")


def _download_extension(suggested_filename: str | None) -> str:
    suffix = Path(suggested_filename or "").suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".png"


def _video_download_extension(suggested_filename: str | None) -> str:
    suffix = Path(suggested_filename or "").suffix.lower()
    if suffix in {".mp4", ".webm", ".mov", ".m4v"}:
        return suffix
    return ".mp4"


def _music_download_extension(suggested_filename: str | None) -> str:
    suffix = Path(suggested_filename or "").suffix.lower()
    if suffix in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}:
        return suffix
    return ".mp3"


def _content_type_from_extension(ext: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext.lower(), "application/octet-stream")


def _video_content_type_from_extension(ext: str) -> str:
    return {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".m4v": "video/x-m4v",
    }.get(ext.lower(), "application/octet-stream")


def _music_content_type_from_extension(ext: str) -> str:
    return {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }.get(ext.lower(), "application/octet-stream")


def _available_image_path(output_dir: Path, index: int, ext: str) -> Path:
    base = output_dir / f"gemini-image-{index:03d}{ext}"
    if not base.exists():
        return base
    counter = 2
    while True:
        candidate = output_dir / f"gemini-image-{index:03d}-{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


def _available_video_path(output_dir: Path, index: int, ext: str) -> Path:
    base = output_dir / f"gemini-video-{index:03d}{ext}"
    if not base.exists():
        return base
    counter = 2
    while True:
        candidate = output_dir / f"gemini-video-{index:03d}-{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


def _available_music_path(output_dir: Path, index: int, ext: str) -> Path:
    base = output_dir / f"gemini-music-{index:03d}{ext}"
    if not base.exists():
        return base
    counter = 2
    while True:
        candidate = output_dir / f"gemini-music-{index:03d}-{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


def _apply_plus_options(page, *, tools: Sequence[str], files: Sequence[Path], plus_options: Sequence[str]) -> dict:
    labels = [_tool_label(tool) for tool in tools]
    labels.extend(plus_options)
    selected_tools = []
    for label in labels:
        _click_plus_menu_item(page, label)
        selected_tools.append(label)
        page.wait_for_timeout(500)

    uploaded_files = []
    if files:
        _upload_local_files(page, files)
        uploaded_files = [str(path) for path in files]

    return {"tools": selected_tools, "files": uploaded_files}


def _tool_label(tool: str) -> str:
    key = tool.strip().lower().replace("_", "-").replace(" ", "-")
    if key not in TOOL_LABELS:
        valid = ", ".join(sorted(TOOL_LABELS))
        raise ValueError(f"Unknown Gemini tool {tool!r}; valid tools: {valid}")
    return TOOL_LABELS[key]


def _select_model_for_request(page, *, model: str | None, tools: Sequence[str]) -> str | None:
    needs_deep_research = any(_tool_label(tool) == "Deep Research" for tool in tools)
    requested = _model_label(model) if model else None
    if needs_deep_research and requested is None:
        requested = "Flash"
    if needs_deep_research and requested == "Flash-Lite":
        raise GeminiUnavailableError("Deep Research is not available with Flash-Lite; use --model flash or --model pro")
    if requested is None:
        return None
    _select_model(page, requested)
    return requested


def _response_text_for_research(research: dict | None, fallback: str) -> str:
    if research is None:
        return fallback
    if research.get("status") == "completed":
        return "Deep Research completed"
    return research.get("text") or fallback


def _model_label(model: str) -> str:
    key = model.strip().lower().replace("_", "-").replace(" ", "-")
    if key not in MODEL_LABELS:
        valid = ", ".join(["flash-lite", "flash", "pro"])
        raise ValueError(f"Unknown Gemini model {model!r}; valid models: {valid}")
    return MODEL_LABELS[key]


def _select_model(page, label: str) -> None:
    if _current_model_matches(page, label):
        return
    button = first_visible(page, MODEL_MENU_LOCATORS, timeout_ms=2500)
    if button is None:
        raise ElementNotFoundError("Could not find Gemini model selector")
    button.click()
    page.wait_for_timeout(400)
    if not _click_model_option(page, label):
        raise ElementNotFoundError(f"Could not find Gemini model option {label!r}")
    page.wait_for_timeout(700)


def _current_model_matches(page, label: str) -> bool:
    selector = first_visible(page, MODEL_MENU_LOCATORS, timeout_ms=1000)
    if selector is None:
        return False
    try:
        text = " ".join((selector.inner_text(timeout=1000) or "").split())
        aria = selector.get_attribute("aria-label", timeout=1000) or ""
    except PlaywrightError:
        return False
    return _model_text_matches(" ".join([text, aria]), label)


def _model_text_matches(text: str, label: str) -> bool:
    value = text.lower().replace("-", " ")
    target = label.lower().replace("-", " ")
    if target not in value:
        return False
    if target == "flash" and "lite" in value:
        return False
    return True


def _click_model_option(page, label: str) -> bool:
    try:
        return bool(
            page.evaluate(
                r"""
                (label) => {
                  const normalize = (text) => (text || '').toLowerCase().replace(/\s+/g, ' ').trim();
                  const target = normalize(label).replace('-', ' ');
                  const matches = (text) => {
                    const value = normalize(text).replace('-', ' ');
                    if (!value.includes(target)) return false;
                    if (target === 'flash' && value.includes('lite')) return false;
                    return true;
                  };
                  const selectors = ['[role="menuitem"]', '[role="option"]', 'button', '[role="button"]'];
                  const nodes = selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)));
                  for (const node of nodes) {
                    const rect = node.getBoundingClientRect();
                    if (!rect || rect.width <= 0 || rect.height <= 0) continue;
                    if (!matches(node.innerText || node.textContent || node.getAttribute('aria-label') || '')) continue;
                    node.click();
                    return true;
                  }
                  return false;
                }
                """,
                label,
            )
        )
    except PlaywrightError:
        return False


def _click_plus_menu_item(page, label: str) -> None:
    item = _plus_menu_item(page, label, timeout_ms=400)
    if item is None:
        _open_plus_menu(page)
        item = _plus_menu_item(page, label, timeout_ms=3000)
    if item is None:
        raise ElementNotFoundError(f"Could not find Gemini + menu option {label!r}")
    item.click()


def _upload_local_files(page, files: Sequence[Path]) -> None:
    for path in files:
        if not path.exists():
            raise FileNotFoundError(f"Upload file does not exist: {path}")
    item = _plus_menu_item(page, "Upload files", timeout_ms=400)
    if item is None:
        _open_plus_menu(page)
        item = _plus_menu_item(page, "Upload files", timeout_ms=3000)
    if item is None:
        raise ElementNotFoundError("Could not find Gemini + menu option 'Upload files'")
    with page.expect_file_chooser(timeout=5000) as chooser_info:
        item.click()
    chooser_info.value.set_files([str(path) for path in files])
    page.wait_for_timeout(3000)


def _plus_menu_item(page, label: str, *, timeout_ms: int):
    escaped = re.escape(label.strip())
    locators = [
        lambda p: p.get_by_role("menuitem", name=re.compile(escaped, re.I)),
        lambda p: p.get_by_role("menuitemcheckbox", name=re.compile(escaped, re.I)),
        lambda p: p.locator('button').filter(has_text=re.compile(escaped, re.I)),
    ]
    return first_visible(page, locators, timeout_ms=timeout_ms)


def _open_plus_menu(page) -> None:
    _dismiss_open_overlay(page)
    button = first_visible(page, PLUS_MENU_LOCATORS, timeout_ms=2500)
    if button is None:
        raise ElementNotFoundError("Could not find Gemini + menu button")
    try:
        button.click(timeout=5000)
    except PlaywrightError:
        _dismiss_open_overlay(page)
        button.click(timeout=5000, force=True)
    page.wait_for_timeout(700)


def _visible_plus_menu_options(page) -> list[dict]:
    try:
        labels = page.evaluate(
            r"""
            () => {
              const visible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0;
              };
              const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
              const selectors = [
                '.cdk-overlay-pane [role="menuitem"]',
                '.cdk-overlay-pane [role="menuitemcheckbox"]',
                '.cdk-overlay-pane [role="menuitemradio"]',
                '.cdk-overlay-pane button',
                '[role="menu"] [role="menuitem"]',
                '[role="menu"] [role="menuitemcheckbox"]',
                '[role="menu"] [role="menuitemradio"]',
                '[role="menu"] button'
              ];
              const seenNodes = new Set();
              const seenLabels = new Set();
              const labels = [];
              for (const selector of selectors) {
                for (const node of document.querySelectorAll(selector)) {
                  if (seenNodes.has(node) || !visible(node)) continue;
                  seenNodes.add(node);
                  const label = clean(node.innerText || node.textContent || node.getAttribute('aria-label') || '');
                  if (!label || seenLabels.has(label.toLowerCase())) continue;
                  seenLabels.add(label.toLowerCase());
                  labels.push(label);
                }
              }
              return labels;
            }
            """
        )
    except PlaywrightError:
        labels = []

    shortcut_by_label = {label.lower(): tool for tool, label in TOOL_LABELS.items()}
    return [{"label": label, "tool": shortcut_by_label.get(label.lower())} for label in labels]


def _submit_prompt(page, text: str) -> None:
    prompt = None if _active_prompt_focused(page) else _wait_for_prompt(page, timeout_ms=15000)
    _fill_prompt(page, prompt, text)
    page.wait_for_timeout(2000)
    page.keyboard.press("Enter")


def _wait_for_prompt(page, *, timeout_ms: int):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        prompt = first_visible(page, PROMPT_LOCATORS, timeout_ms=250)
        if prompt is not None:
            return prompt
        page.wait_for_timeout(100)
    raise ElementNotFoundError("Could not find visible Gemini prompt box")


def _fill_prompt(page, prompt, text: str) -> None:
    if prompt is not None and not _active_prompt_focused(page):
        prompt.focus()
    page.keyboard.press("Meta+A")
    page.keyboard.press("Backspace")
    page.keyboard.type(text, delay=20)


def _active_prompt_focused(page) -> bool:
    try:
        return bool(
            page.evaluate(
                r"""
                () => {
                  const active = document.activeElement;
                  if (!active) return false;
                  if (active.matches('textarea, [contenteditable="true"][role="textbox"], div[role="textbox"][contenteditable="true"]')) return true;
                  return !!active.closest('rich-textarea, [contenteditable="true"][role="textbox"], div[role="textbox"][contenteditable="true"]');
                }
                """
            )
        )
    except PlaywrightError:
        return False


def _wait_for_response(page, *, before_signature: str, timeout: int) -> str:
    deadline = time.monotonic() + timeout
    last_text = ""
    stable_since = 0.0
    saw_new_text = False

    while time.monotonic() < deadline:
        messages = _visible_messages(page, limit=80)
        signature = _messages_signature(messages)
        model_messages = [m for m in messages if m.get("role") != "user" and m.get("text")]
        current = model_messages[-1]["text"] if model_messages else ""

        if signature != before_signature and current:
            saw_new_text = True
            if current == last_text:
                if stable_since == 0.0:
                    stable_since = time.monotonic()
            else:
                last_text = current
                stable_since = time.monotonic()

        stop_visible = first_visible(page, STOP_BUTTON_LOCATORS, timeout_ms=250) is not None
        if saw_new_text and not stop_visible and stable_since and time.monotonic() - stable_since >= 2.0:
            return last_text

        page.wait_for_timeout(700)

    if last_text:
        raise ResponseTimeoutError(f"Gemini response did not finish within {timeout} seconds; partial response: {last_text[:240]}")
    raise ResponseTimeoutError(f"Gemini did not produce a visible response within {timeout} seconds")


def _confirm_deep_research_if_needed(page, response_text: str, *, selected: dict, timeout: int, wait_complete: bool, poll_interval: int) -> dict | None:
    if "Deep Research" not in (selected.get("tools") or []):
        return None

    start = first_visible(page, START_RESEARCH_LOCATORS, timeout_ms=1500)
    if start is None:
        report = _extract_deep_research_report(page)
        if report is not None:
            return report
        return {"status": "plan_ready", "text": response_text, "report": None, "sources": []}

    start.click()
    page.wait_for_timeout(1000)
    chat = {"id": chat_id_from_url(page.url), "url": clean_url(page.url)}
    if not wait_complete:
        return _research_payload("in_progress", text="Deep Research started", chat=chat, plan=response_text)
    return _wait_for_deep_research_report(page, timeout=timeout, plan=response_text, chat=chat, poll_interval=poll_interval)


def _wait_for_deep_research_report(page, *, timeout: int, plan: str, chat: dict, poll_interval: int) -> dict:
    deadline = time.monotonic() + timeout
    status_text = ""
    interval_ms = max(1, poll_interval) * 1000
    while time.monotonic() < deadline:
        report = _extract_deep_research_report(page)
        if report is not None:
            report.setdefault("plan", plan)
            report.setdefault("chat", chat)
            return report
        messages = _visible_messages(page, limit=80)
        model_messages = [m for m in messages if m.get("role") != "user" and m.get("text")]
        if model_messages:
            status_text = model_messages[-1]["text"]
        page.wait_for_timeout(interval_ms)
    raise ResponseTimeoutError(f"Deep Research report did not complete within {timeout} seconds; latest status: {status_text[:240]}")


def _extract_research_status(page) -> dict:
    report = _extract_deep_research_report(page)
    if report is not None:
        return report
    progress = _extract_deep_research_progress(page)
    if progress is not None:
        return progress
    return _research_payload("not_found", text="No visible Deep Research report or in-progress research status found")


def _extract_deep_research_progress(page) -> dict | None:
    messages = _visible_messages(page, limit=80)
    model_messages = [m for m in messages if m.get("role") != "user" and m.get("text")]
    research_markers = re.compile(r"\b(deep research|research|researching|sources?|create report|ready in|analyz(e|ing)|start research)\b", re.I)
    for message in reversed(model_messages):
        text = message.get("text") or ""
        if research_markers.search(text):
            return _research_payload("in_progress", text=_research_progress_text(text), plan=text)
    return None


def _research_progress_text(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return "Deep Research is still in progress"
    if re.search(r"ready in|researching|analyz(e|ing)|create report", cleaned, re.I):
        return cleaned
    return "Deep Research is still in progress"


def _extract_deep_research_report(page) -> dict | None:
    try:
        payload = page.evaluate(
            r"""
            () => {
              const visible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0;
              };
              const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
              const candidateSelectors = [
                'structured-content-container[data-test-id="message-content"]',
                'structured-content-container',
                'message-content',
                '[data-message-author-role="model"]',
                '[class*="model-response"]',
                '[class*="response-container"]',
                'main markdown',
                'main .markdown'
              ];
              const candidates = [];
              const seenNodes = new Set();
              for (const selector of candidateSelectors) {
                for (const node of document.querySelectorAll(selector)) {
                  if (!visible(node) || seenNodes.has(node)) continue;
                  seenNodes.add(node);
                  const text = clean(node.innerText || node.textContent || '');
                  if (text.length < 80) continue;
                  const lower = text.toLowerCase();
                  const looksLikePlan = lower.includes('start research') && lower.includes('research websites');
                  const hasCompletion = lower.includes("i've completed your research")
                    || lower.includes('completed your research')
                    || lower.includes('sources used in the report')
                    || lower.includes('sources read but not used in the report');
                  const hasReportStructure = lower.includes('sources used in the report')
                    || lower.includes('executive')
                    || lower.includes('key metrics')
                    || lower.includes('summary');
                  const isResearchReport = !looksLikePlan && (hasCompletion || (text.length > 500 && hasReportStructure));
                  if (!isResearchReport) continue;
                  candidates.push({ node, text });
                }
              }
              candidates.sort((a, b) => {
                const ar = a.node.getBoundingClientRect();
                const br = b.node.getBoundingClientRect();
                return b.text.length - a.text.length || br.top - ar.top;
              });
              const reportCandidate = candidates[0];
              const reportNode = reportCandidate?.node;
              if (!reportNode) return null;
              const text = reportCandidate.text;
              if (!text) return null;

              const sourceRoot = Array.from(document.querySelectorAll('.source-list.used-sources, div.source-list.used-sources'))
                .filter((node) => visible(node))
                .sort((a, b) => b.getBoundingClientRect().height - a.getBoundingClientRect().height)[0];
              const sources = [];
              if (sourceRoot) {
                const seen = new Set();
                for (const link of sourceRoot.querySelectorAll('a[href]')) {
                  const url = link.href || '';
                  const title = clean(link.innerText || link.textContent || link.getAttribute('aria-label') || '');
                  if (!url || seen.has(url)) continue;
                  seen.add(url);
                  sources.push({ title: title || url, url });
                }
                if (!sources.length) {
                  const raw = clean(sourceRoot.innerText || sourceRoot.textContent || '');
                  for (const part of raw.split(/ Opens in a new window /i)) {
                    const item = clean(part);
                    if (item) sources.push({ title: item, url: null });
                  }
                }
              }
              return { status: 'completed', text: 'Deep Research completed', report: { text }, sources };
            }
            """
        )
    except PlaywrightError:
        return None
    if payload and (payload.get("report") or {}).get("text"):
        payload["report"]["text"] = _trim_research_report_text(payload["report"]["text"])
    return payload


def _research_payload(status: str, *, text: str, report: dict | None = None, sources: list | None = None, plan: str | None = None, chat: dict | None = None) -> dict:
    payload = {"status": status, "text": text, "report": report, "sources": sources or []}
    if plan is not None:
        payload["plan"] = plan
    if chat is not None:
        payload["chat"] = chat
        payload["next_command"] = _research_next_command(chat)
        payload["status_command"] = _research_status_command(chat)
        payload["wait_command"] = _research_wait_command(chat)
    if status == "in_progress":
        payload["recommended_poll_seconds"] = 120
    payload["last_checked_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return payload


def _research_next_command(chat: dict | None) -> str | None:
    return _research_wait_command(chat)


def _research_status_command(chat: dict | None) -> str | None:
    url = (chat or {}).get("url") or (chat or {}).get("id")
    if not url:
        return None
    return f"geminiwebapp-cli chats status {shlex.quote(str(url))} --json"


def _research_wait_command(chat: dict | None) -> str | None:
    url = (chat or {}).get("url") or (chat or {}).get("id")
    if not url:
        return None
    return f"geminiwebapp-cli chats research {shlex.quote(str(url))} --wait --timeout 1800 --poll-interval 30 --json"


def _trim_research_report_text(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    cut_patterns = [
        r"\bSources read but not used in the report\b",
        r"\bThoughts\s+(Mapping|I am|Identifying|Investigating|Uncovering|Analyzing|Resolving|Formulating)\b",
    ]
    cut_at = len(cleaned)
    for pattern in cut_patterns:
        match = re.search(pattern, cleaned, re.I)
        if match:
            cut_at = min(cut_at, match.start())
    return cleaned[:cut_at].rstrip()


def _without_research_messages(messages: list[dict], research: dict) -> list[dict]:
    report_text = ((research.get("report") or {}).get("text") or "").strip()
    filtered = []
    seen = set()
    for message in messages:
        role = message.get("role")
        text = " ".join((message.get("text") or "").split())
        normalized = _strip_spoken_prefix(text)
        if not normalized or normalized.lower() == "said":
            continue
        if role != "user" and _is_research_artifact(text, report_text):
            continue
        if role == "user" and re.fullmatch(r"start research", normalized, re.I):
            continue
        key = (role, normalized)
        if key in seen:
            continue
        seen.add(key)
        cleaned = dict(message)
        cleaned["text"] = normalized
        filtered.append(cleaned)
    return filtered


def _is_research_artifact(text: str, report_text: str) -> bool:
    cleaned = _strip_spoken_prefix(text)
    if report_text:
        report_cleaned = _strip_spoken_prefix(" ".join(report_text.split()))
        if cleaned.startswith(report_cleaned[:200]) or report_cleaned.startswith(cleaned[:200]):
            return True
    return bool(
        re.search(r"\b(research plan|research websites|start research|create report|analyz(e|ing) results|ready in a few mins)\b", cleaned, re.I)
        or re.search(r"\bI've completed your research\b", cleaned, re.I)
    )


def _strip_spoken_prefix(text: str) -> str:
    return re.sub(r"^said\s+", "", text, flags=re.I).strip()


def _open_sidebar_if_needed(page) -> None:
    if _collect_chats(page, limit=1):
        return
    toggles = [
        lambda p: p.get_by_role("button", name=re.compile("menu|navigation|sidebar", re.I)),
        lambda p: p.locator('button[aria-label*="menu" i]'),
        lambda p: p.locator('button[aria-label*="navigation" i]'),
        lambda p: p.locator('button[aria-label*="sidebar" i]'),
    ]
    toggle = first_visible(page, toggles, timeout_ms=1000)
    if toggle is not None:
        try:
            toggle.click(timeout=2500)
        except PlaywrightError:
            try:
                toggle.click(force=True, timeout=2500)
            except PlaywrightError:
                return
        page.wait_for_timeout(700)


def _collect_chats(page, *, limit: int) -> list[dict]:
    try:
        return page.evaluate(
            r"""
            (limit) => {
              const visible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0;
              };
              const absolute = (href) => {
                try { return new URL(href, location.origin).toString().split('#')[0].split('?')[0]; }
                catch { return null; }
              };
              const links = Array.from(document.querySelectorAll('a[href^="/app/"], a[href*="gemini.google.com/app/"]'));
              const seen = new Set();
              const rows = [];
              for (const link of links) {
                if (!visible(link)) continue;
                const url = absolute(link.getAttribute('href'));
                if (!url || seen.has(url)) continue;
                if (!/\/app\/[^/?#]+/.test(url)) continue;
                const title = (link.innerText || link.textContent || link.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
                if (!title || /^gemini$/i.test(title)) continue;
                seen.add(url);
                const id = (url.match(/\/app\/([^/?#]+)/) || [])[1] || null;
                rows.push({ id, title, url });
                if (rows.length >= limit) break;
              }
              return rows;
            }
            """,
            limit,
        )
    except PlaywrightError:
        return []


def _message_signature(page) -> str:
    return _messages_signature(_visible_messages(page, limit=80))


def _messages_signature(messages: list[dict]) -> str:
    return "\n---\n".join(f"{m.get('role')}:{m.get('text')}" for m in messages)


def _visible_messages(page, *, limit: int) -> list[dict]:
    rich = _visible_messages_from_dom(page, limit=limit)
    if rich:
        return rich[-limit:]

    messages = []
    for factory in MESSAGE_CONTAINER_LOCATORS:
        locators = factory(page)
        try:
            count = min(locators.count(), limit * 3)
        except PlaywrightError:
            continue
        for index in range(count):
            text = visible_text(locators.nth(index))
            if text and text not in {m.get("text") for m in messages}:
                messages.append({"role": "model", "text": text})
        if messages:
            return messages[-limit:]
    return []


def _visible_messages_from_dom(page, *, limit: int) -> list[dict]:
    try:
        return page.evaluate(
            r"""
            (limit) => {
              const visible = (node) => {
                const rect = node && node.getBoundingClientRect();
                return !!rect && rect.width > 0 && rect.height > 0;
              };
              const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
              const roleFor = (node, text) => {
                const attr = clean(node.getAttribute('data-message-author-role') || node.getAttribute('aria-label') || '').toLowerCase();
                const klass = String(node.className || '').toLowerCase();
                if (/user|you|your prompt/.test(attr) || /user/.test(klass)) return 'user';
                if (/gemini|model|response/.test(attr) || /model|response|assistant/.test(klass)) return 'model';
                const parentText = clean(node.closest('[aria-label], [class]')?.getAttribute('aria-label') || '');
                if (/you|user|your prompt/i.test(parentText)) return 'user';
                if (/gemini|response|answer/i.test(parentText)) return 'model';
                if (/^you\b/i.test(text)) return 'user';
                return 'model';
              };
              const selectors = [
                '[data-message-author-role]',
                'message-content',
                '[class*="user-query"]',
                '[class*="model-response"]',
                '[class*="response-container"]',
                'main markdown',
                'main .markdown'
              ];
              const nodes = [];
              const seenNodes = new Set();
               for (const selector of selectors) {
                 for (const node of document.querySelectorAll(selector)) {
                   if (!visible(node) || seenNodes.has(node)) continue;
                   seenNodes.add(node);
                   nodes.push(node);
                 }
               }
              nodes.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
              const rows = [];
              const seenText = new Set();
              for (const node of nodes) {
                let text = clean(node.innerText || node.textContent || '');
                text = text.replace(/^(Gemini|You)\s+/i, '').trim();
                if (!text || text.length < 2) continue;
                if (/^(share|export|copy|thumbs up|thumbs down|listen)$/i.test(text)) continue;
                const key = `${roleFor(node, text)}:${text}`;
                if (seenText.has(key)) continue;
                seenText.add(key);
                rows.push({ role: roleFor(node, text), text });
              }
              return rows.slice(-limit);
            }
            """,
            limit,
        )
    except PlaywrightError:
        return []


def _scroll_messages_up(page, *, scrolls: int) -> None:
    for _ in range(scrolls):
        try:
            page.evaluate(
                r"""
                () => {
                  const candidates = Array.from(document.querySelectorAll('main, [role="main"], [class*="conversation"], [class*="chat"]'));
                  const scrollables = candidates
                    .filter((node) => {
                      const rect = node.getBoundingClientRect();
                      return rect && rect.width > 200 && rect.height > 200 && node.scrollHeight > node.clientHeight + 40;
                    })
                    .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
                  if (scrollables[0]) scrollables[0].scrollTop = Math.max(0, scrollables[0].scrollTop - scrollables[0].clientHeight);
                  else window.scrollBy(0, -window.innerHeight);
                }
                """
            )
            page.wait_for_timeout(700)
        except PlaywrightError:
            return


def _scroll_messages_down(page) -> None:
    try:
        page.evaluate(
            r"""
            () => {
              const candidates = Array.from(document.querySelectorAll('main, [role="main"], [class*="conversation"], [class*="chat"]'));
              const scrollables = candidates
                .filter((node) => {
                  const rect = node.getBoundingClientRect();
                  return rect && rect.width > 200 && rect.height > 200 && node.scrollHeight > node.clientHeight + 40;
                })
                .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
              if (scrollables[0]) scrollables[0].scrollTop = scrollables[0].scrollHeight;
              else window.scrollTo(0, document.body.scrollHeight);
            }
            """
        )
        page.wait_for_timeout(700)
    except PlaywrightError:
        return
