from __future__ import annotations

from typing import Any

import requests


class TelegramError(RuntimeError):
    """Telegram Bot API 오류입니다."""


def get_bot_profile(
    bot_token: str,
    timeout: int = 15,
) -> dict[str, Any]:
    if not bot_token:
        raise TelegramError("TELEGRAM_BOT_TOKEN이 비어 있습니다.")

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getMe",
            timeout=timeout,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise TelegramError(
            "텔레그램 봇 정보를 확인하지 못했습니다."
        ) from exc

    if not response.ok or data.get("ok") is not True:
        description = data.get("description", "알 수 없는 오류")
        raise TelegramError(f"텔레그램 오류: {description}")

    return data.get("result", {}) or {}


def find_chat_by_link_code(
    bot_token: str,
    link_code: str,
    timeout: int = 15,
) -> dict[str, str] | None:
    """최근 메시지 중 정확히 일치하는 /start 연결코드만 찾습니다.

    다른 사용자의 Chat ID나 메시지는 반환하거나 화면에 노출하지 않습니다.
    """

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getUpdates",
            params={
                "limit": 100,
                "timeout": 0,
                "allowed_updates": '["message"]',
            },
            timeout=timeout,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise TelegramError(
            "텔레그램 연결 요청을 확인하지 못했습니다."
        ) from exc

    if not response.ok or data.get("ok") is not True:
        description = data.get("description", "알 수 없는 오류")
        raise TelegramError(f"텔레그램 오류: {description}")

    expected_suffix = f" {link_code}"

    # 최신 메시지부터 확인합니다.
    for update in reversed(data.get("result", [])):
        message = update.get("message") or {}
        text = str(message.get("text", "")).strip()

        # /start CODE 또는 /start@botname CODE
        if not text.startswith("/start"):
            continue
        if not text.endswith(expected_suffix):
            continue

        command_part = text[: -len(expected_suffix)].strip()
        if command_part != "/start" and not command_part.startswith("/start@"):
            continue

        chat = message.get("chat", {}) or {}
        chat_id = str(chat.get("id", "")).strip()

        if not chat_id:
            continue

        display_name = (
            " ".join(
                part
                for part in [
                    str(chat.get("first_name", "")).strip(),
                    str(chat.get("last_name", "")).strip(),
                ]
                if part
            ).strip()
            or str(chat.get("username", "")).strip()
            or "텔레그램 사용자"
        )

        return {
            "chat_id": chat_id,
            "display_name": display_name,
        }

    return None


def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    timeout: int = 15,
) -> None:
    if not bot_token:
        raise TelegramError("TELEGRAM_BOT_TOKEN이 비어 있습니다.")
    if not chat_id:
        raise TelegramError("사용자의 Telegram Chat ID가 없습니다.")

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
            },
            timeout=timeout,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise TelegramError(
            "텔레그램 메시지를 전송하지 못했습니다."
        ) from exc

    if not response.ok or data.get("ok") is not True:
        description = data.get("description", "알 수 없는 오류")
        raise TelegramError(f"텔레그램 전송 오류: {description}")
