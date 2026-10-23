from __future__ import annotations

from types import SimpleNamespace

import httpx

from tradingbot.ops.alerts import send_telegram, telegram_configured


def test_telegram_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert telegram_configured() is False
    assert send_telegram("hello") is False


def test_telegram_configured(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    assert telegram_configured() is True

    def fake_post(*args, **kwargs):
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(httpx, "post", fake_post)
    assert send_telegram("hello") is True
