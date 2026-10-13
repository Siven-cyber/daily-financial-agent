"""Telegram bot entry point: handles updates, records transactions, answers questions.

Run with: python -m finance_agent.bot
The authenticated Telegram user_id is the only identity used for data access.
"""

from __future__ import annotations

import logging
from typing import Optional

from .agent import FinanceAgent
from .config import Config, load_config
from .currency import SUPPORTED_CURRENCIES, format_amount, get_currency, normalize_currency
from .db import Database
from .i18n import category_label, normalize_language, t
from .parser import detected_currency_mismatch
from .service import FinanceService
from .telegram_client import TelegramClient

logger = logging.getLogger("finance_agent.bot")

# A message is treated as a question (routed to the agent) when it has no amount but
# ends with a question mark or starts with a common question word.
_QUESTION_PREFIXES = (
    "berapa", "apa", "kenapa", "bagaimana", "how", "what", "why", "when", "which",
)


def _parse_int(text: str) -> Optional[int]:
    """Parse a positive integer id; return None if invalid."""
    text = text.strip()
    if not text.isdigit():
        return None
    value = int(text)
    return value if value > 0 else None


class FinanceBot:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._db = Database(config.db_path)
        self._service = FinanceService(self._db)
        self._tg = TelegramClient(config.telegram_bot_token)
        # The agent is created lazily on first need, so the bot can run the fast
        # (local parser) path even if the model backend is temporarily unavailable.
        self._agent: Optional[FinanceAgent] = None

    def _get_agent(self) -> Optional[FinanceAgent]:
        if self._agent is None:
            try:
                self._agent = FinanceAgent(self._config.openminion_config)
            except Exception as exc:  # noqa: BLE001
                logger.warning("agent unavailable: %s", exc)
                return None
        return self._agent

    # ----- update handling -------------------------------------------------

    def handle_update(self, update: dict) -> None:
        if "message" in update:
            self._handle_message(update["message"])
        elif "callback_query" in update:
            self._handle_callback(update["callback_query"])

    def _lang(self, user_id: int) -> str:
        return self._db.get_language(user_id) or "id"

    def _handle_message(self, message: dict) -> None:
        chat_id = message.get("chat", {}).get("id")
        user = message.get("from", {})
        user_id = user.get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or user_id is None or not text:
            return

        if text.startswith("/"):
            self._handle_command(chat_id, user_id, text)
            return

        # First contact: prompt language, then currency.
        if self._db.get_language(user_id) is None:
            self._db.ensure_user(user_id)
            self._prompt_language(chat_id)
            return
        if self._db.get_currency(user_id) is None:
            self._prompt_currency(chat_id, self._lang(user_id))
            return

        lang = self._lang(user_id)
        currency = self._service.user_currency(user_id)

        # A mismatched currency marker (e.g. "$5" for an IDR user) is ambiguous, so ask
        # the user to restate it instead of storing a wrong value.
        if detected_currency_mismatch(text, currency) is not None:
            self._tg.send_message(
                chat_id,
                t(lang, "wrong_currency", currency=get_currency(currency).code),
            )
            return

        # Fast path: local parser records instantly.
        result = self._service.record_from_text(user_id, text)
        if result is not None:
            self._send_record_confirmation(chat_id, lang, result)
            return

        # Otherwise treat it as a question if it looks like one.
        if self._looks_like_question(text):
            self._answer_question(chat_id, user_id, lang, text)
            return

        self._tg.send_message(chat_id, t(lang, "not_understood"))

    def _handle_command(self, chat_id: int, user_id: int, text: str) -> None:
        cmd = text.split()[0].lstrip("/").lower()
        lang = self._lang(user_id)
        if cmd == "start":
            self._db.ensure_user(user_id)
            self._prompt_language(chat_id)
        elif cmd in {"bahasa", "language", "lang"}:
            self._prompt_language(chat_id)
        elif cmd in {"matauang", "currency", "mata_uang"}:
            self._prompt_currency(chat_id, lang)
        elif cmd == "help":
            self._tg.send_message(chat_id, t(lang, "help"))
        elif cmd in {"ringkasan", "summary"}:
            self._send_summary(chat_id, user_id, lang)
        elif cmd in {"terakhir", "recent"}:
            self._send_recent(chat_id, user_id, lang)
        elif cmd in {"edit", "ubah"}:
            self._handle_edit(chat_id, user_id, lang, text)
        elif cmd in {"hapus", "delete", "del"}:
            self._handle_delete(chat_id, user_id, lang, text)
        else:
            self._tg.send_message(chat_id, t(lang, "help"))

    def _handle_callback(self, callback: dict) -> None:
        data = callback.get("data") or ""
        user = callback.get("from", {})
        user_id = user.get("id")
        message = callback.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        cb_id = callback.get("id")
        if cb_id:
            # Answering is best-effort: a 400 here (already answered / stale id) must not
            # abort the rest of the flow (e.g. sending the currency prompt).
            try:
                self._tg.answer_callback_query(cb_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("answer_callback_query failed: %s", exc)
        if chat_id is None or user_id is None:
            return
        if data.startswith("lang:"):
            lang = normalize_language(data.split(":", 1)[1])
            self._db.set_language(user_id, lang)
            self._tg.send_message(chat_id, t(lang, "language_set"))
            # Continue onboarding with currency if not set yet.
            if self._db.get_currency(user_id) is None:
                self._prompt_currency(chat_id, lang)
            else:
                self._tg.send_message(chat_id, t(lang, "welcome"))
        elif data.startswith("cur:"):
            lang = self._lang(user_id)
            currency = normalize_currency(data.split(":", 1)[1])
            self._db.set_currency(user_id, currency)
            self._tg.send_message(
                chat_id,
                t(lang, "currency_set", currency=get_currency(currency).code),
            )
            self._tg.send_message(chat_id, t(lang, "welcome"))
        elif data.startswith("del:"):
            lang = self._lang(user_id)
            self._confirm_delete(chat_id, user_id, lang, data.split(":", 1)[1])
        elif data.startswith("delcancel:"):
            pass  # user cancelled; nothing to do

    # ----- responses -------------------------------------------------------

    def _prompt_language(self, chat_id: int) -> None:
        keyboard = {
            "inline_keyboard": [[
                {"text": "Bahasa Indonesia", "callback_data": "lang:id"},
                {"text": "English", "callback_data": "lang:en"},
            ]]
        }
        self._tg.send_message(
            chat_id, t("id", "choose_language"), reply_markup=keyboard
        )

    def _prompt_currency(self, chat_id: int, lang: str) -> None:
        keyboard = {
            "inline_keyboard": [[
                {"text": get_currency(code).label, "callback_data": f"cur:{code}"}
                for code in SUPPORTED_CURRENCIES
            ]]
        }
        self._tg.send_message(
            chat_id, t(lang, "choose_currency"), reply_markup=keyboard
        )

    def _send_record_confirmation(self, chat_id: int, lang: str, result) -> None:
        tx = result.transaction
        key = "recorded_income" if tx.kind == "income" else "recorded_expense"
        label = category_label(tx.category, lang)
        msg = t(
            lang, key, amount=format_amount(tx.amount, tx.currency), category=label
        )
        if result.budget_warning:
            msg = f"{msg}\n{result.budget_warning}"
        self._tg.send_message(chat_id, msg)

    def _send_summary(self, chat_id: int, user_id: int, lang: str) -> None:
        s = self._service.month_summary(user_id)
        currency = s["currency"]
        if s["expense"] == 0 and s["income"] == 0:
            self._tg.send_message(chat_id, t(lang, "summary_empty"))
            return
        lines = [
            t(lang, "summary_title"),
            t(lang, "summary_line_income", amount=format_amount(s["income"], currency)),
            t(lang, "summary_line_expense", amount=format_amount(s["expense"], currency)),
        ]
        if s["by_category"]:
            lines.append("")
            lines.append(t(lang, "summary_by_category"))
            for category, total in s["by_category"]:
                label = category_label(category, lang)
                lines.append(f"- {label}: {format_amount(total, currency)}")
        self._tg.send_message(chat_id, "\n".join(lines))

    def _send_recent(self, chat_id: int, user_id: int, lang: str) -> None:
        rows = self._service.recent(user_id, 10)
        if not rows:
            self._tg.send_message(chat_id, t(lang, "recent_empty"))
            return
        lines = [t(lang, "recent_title")]
        for tx in rows:
            sign = "+" if tx.kind == "income" else "-"
            date = tx.occurred_at[:10]
            amount = format_amount(tx.amount, tx.currency)
            label = category_label(tx.category, lang)
            lines.append(f"#{tx.id} {date} {sign}{amount} {label} ({tx.note})")
        self._tg.send_message(chat_id, "\n".join(lines))

    def _handle_edit(self, chat_id: int, user_id: int, lang: str, text: str) -> None:
        parts = text.split()
        if len(parts) < 3:
            self._tg.send_message(chat_id, t(lang, "edit_usage"))
            return
        tx_id = _parse_int(parts[1])
        amount_text = " ".join(parts[2:])
        if tx_id is None:
            self._tg.send_message(chat_id, t(lang, "edit_usage"))
            return
        updated = self._service.edit_amount(user_id, tx_id, amount_text)
        if updated is None:
            # Distinguish "amount unreadable" from "id not found" by re-checking id.
            if self._service.get_transaction(user_id, tx_id) is None:
                self._tg.send_message(chat_id, t(lang, "not_found", id=tx_id))
            else:
                self._tg.send_message(chat_id, t(lang, "invalid_amount"))
            return
        label = category_label(updated.category, lang)
        self._tg.send_message(
            chat_id,
            t(
                lang,
                "edited",
                id=updated.id,
                amount=format_amount(updated.amount, updated.currency),
                category=label,
            ),
        )

    def _handle_delete(self, chat_id: int, user_id: int, lang: str, text: str) -> None:
        parts = text.split()
        if len(parts) < 2:
            self._tg.send_message(chat_id, t(lang, "delete_usage"))
            return
        tx_id = _parse_int(parts[1])
        if tx_id is None:
            self._tg.send_message(chat_id, t(lang, "delete_usage"))
            return
        tx = self._service.get_transaction(user_id, tx_id)
        if tx is None:
            self._tg.send_message(chat_id, t(lang, "not_found", id=tx_id))
            return
        label = category_label(tx.category, lang)
        keyboard = {
            "inline_keyboard": [[
                {"text": t(lang, "confirm_yes"), "callback_data": f"del:{tx_id}"},
                {"text": t(lang, "confirm_cancel"), "callback_data": f"delcancel:{tx_id}"},
            ]]
        }
        self._tg.send_message(
            chat_id,
            t(
                lang,
                "delete_confirm",
                id=tx.id,
                amount=format_amount(tx.amount, tx.currency),
                category=label,
            ),
            reply_markup=keyboard,
        )

    def _confirm_delete(self, chat_id: int, user_id: int, lang: str, tx_id_str: str) -> None:
        tx_id = _parse_int(tx_id_str)
        if tx_id is None:
            return
        if self._service.delete(user_id, tx_id):
            self._tg.send_message(chat_id, t(lang, "deleted", id=tx_id))
        else:
            self._tg.send_message(chat_id, t(lang, "not_found", id=tx_id))

    def _answer_question(self, chat_id: int, user_id: int, lang: str, text: str) -> None:
        agent = self._get_agent()
        if agent is None:
            # Model unavailable: fall back to a plain numeric summary.
            self._send_summary(chat_id, user_id, lang)
            return
        self._tg.send_message(chat_id, t(lang, "processing"))
        try:
            context = self._service.summary_context(user_id)
            answer = agent.answer(
                text, context=context, session_id=f"user-{user_id}"
            )
            self._tg.send_message(chat_id, answer or t(lang, "error_generic"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("answer failed: %s", exc)
            self._send_summary(chat_id, user_id, lang)

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        lowered = text.lower().strip()
        return lowered.endswith("?") or lowered.startswith(_QUESTION_PREFIXES)

    # ----- main loop -------------------------------------------------------

    def run(self) -> None:
        me = self._tg.get_me()
        username = me.get("result", {}).get("username", "?")
        logger.info("bot online as @%s", username)
        while True:
            for update in self._tg.poll_updates():
                try:
                    self.handle_update(update)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("update handling failed: %s", exc)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    if not config.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set (see .env.example)")
    bot = FinanceBot(config)
    bot.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
