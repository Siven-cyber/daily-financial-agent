"""Minimal Telegram Bot API client using only the standard library.

Long-polling getUpdates plus sendMessage and answerCallbackQuery. Avoids an external
dependency so the project stays easy to audit and install.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator, Optional

_API_BASE = "https://api.telegram.org/bot"


class TelegramClient:
    def __init__(self, token: str, *, timeout: int = 15) -> None:
        if not token:
            raise ValueError("Telegram bot token is required")
        self._base = f"{_API_BASE}{token}"
        self._timeout = timeout
        self._offset: Optional[int] = None
        self._poll_failures = 0
        self._logger = logging.getLogger(__name__)

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}/{method}"
        data = urllib.parse.urlencode(
            {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
             for k, v in params.items() if v is not None}
        ).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        # Callback acknowledgement is best-effort on its own short lane. Keep
        # the historical send deadline: shortening it increases ambiguous sends.
        timeout = 3 if method == 'answerCallbackQuery' else self._timeout + 15
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def get_me(self) -> dict[str, Any]:
        return self._call("getMe", {})

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: Optional[dict] = None,
        parse_mode: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            },
        )

    def answer_callback_query(
        self, callback_query_id: str, text: Optional[str] = None
    ) -> dict[str, Any]:
        return self._call(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text},
        )

    def fetch_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        """Caller persists the batch before using a later acknowledgement offset."""
        started = time.monotonic()
        try:
            result = self._call('getUpdates', {
                'timeout': self._timeout, 'offset': offset,
                'allowed_updates': ['message', 'callback_query'],
            })
            if not result.get('ok'):
                raise RuntimeError('Telegram polling rejected')
        except Exception as exc:
            self._poll_failures += 1
            status = exc.code if isinstance(exc, urllib.error.HTTPError) else None
            status = status if type(status) is int and 100 <= status <= 599 else 'unknown'
            self._logger.warning(
                'event=telegram.poll.failed error_class=%s http_status=%s '
                'elapsed_ms=%d consecutive_failures=%d',
                type(exc).__name__, status,
                round((time.monotonic() - started) * 1000), self._poll_failures,
            )
            raise
        if self._poll_failures:
            self._logger.info(
                'event=telegram.poll.recovered elapsed_ms=%d previous_failures=%d',
                round((time.monotonic() - started) * 1000), self._poll_failures,
            )
        self._poll_failures = 0
        return result.get('result', [])

    def poll_updates(self) -> Iterator[dict[str, Any]]:
        """Yield updates via long polling, advancing the offset as it goes.

        Network errors are swallowed and the caller simply gets no updates for that
        cycle, so a transient outage does not crash the bot loop.
        """
        try:
            result = self._call(
                "getUpdates",
                {
                    "timeout": self._timeout,
                    "offset": self._offset,
                    "allowed_updates": ["message", "callback_query"],
                },
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return
        if not result.get("ok"):
            return
        for update in result.get("result", []):
            self._offset = int(update["update_id"]) + 1
            yield update
