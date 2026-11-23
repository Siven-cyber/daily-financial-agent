"""Single in-flight Telegram poll with an explicit durable-receipt handshake."""
from __future__ import annotations

import logging
import queue
import threading

logger = logging.getLogger('finance_agent.bot')


class PollingWorker:
    """No database access or sends; only the owner supplies committed offsets.

    TelegramClient's fetch and send methods use independent request-local urllib
    calls. Capture the real client, never the bot's temporary reply collector.
    """

    def __init__(self, transport) -> None:
        self.transport = transport
        self.requests = queue.Queue(maxsize=1)
        self.results = queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, name='telegram-poll', daemon=True)

    def _run(self) -> None:
        while not self.stopping.is_set():
            try:
                offset = self.requests.get(timeout=0.05)
            except queue.Empty:
                continue
            while not self.stopping.is_set():
                try:
                    updates = self.transport.fetch_updates(offset=offset)
                except Exception as exc:
                    logger.warning('polling failed: %s', type(exc).__name__)
                    if self.stopping.wait(2):
                        return
                    continue
                if not self.stopping.is_set():
                    self.results.put_nowait(updates)
                break

    def start(self, transport, offset: int | None) -> None:
        self.transport = transport
        self.requests.put_nowait(offset)
        self.thread.start()

    def close(self) -> None:
        self.stopping.set()
        # urllib cannot reliably cancel an in-flight request. Do not make shutdown
        # wait for its network timeout; daemon owns no database/runtime resources.
        if self.thread.ident is not None:
            self.thread.join(timeout=0.2)
