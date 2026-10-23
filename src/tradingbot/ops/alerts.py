"""Optional Telegram alerting. No-op when not configured."""

from __future__ import annotations

import os

import httpx


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def send_telegram(text: str, timeout: float = 10.0) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=timeout,
        )
        return response.status_code == 200
    except Exception:
        return False


def notify(title: str, lines: list[str]) -> bool:
    text = title + "\n" + "\n".join(f"- {line}" for line in lines)
    return send_telegram(text)
