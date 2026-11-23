"""Bounded network-only lanes. No bot, collector or SQLite references."""
from __future__ import annotations

import copy
import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)


class OutboundWorker:
    """Two send slots and one independent best-effort callback slot.

    A slot remains occupied until the main thread commits its result. Daemon
    threads cannot cancel urllib; closing abandons results, never accesses SQL.
    """
    def __init__(self, transport):
        self.transport = transport
        self.stopping = threading.Event()
        self.results = queue.Queue(maxsize=3)
        self.jobs = {}
        self.slots = [queue.Queue(maxsize=1) for _ in range(3)]
        self.threads = []
        try:
            for index, slot in enumerate(self.slots):
                thread = threading.Thread(target=self._run, args=(slot,),
                                          name=f'telegram-outbound-{index}', daemon=True)
                thread.start()
                self.threads.append(thread)
        except BaseException:
            self.close()
            raise

    def available(self, reply):
        if self.stopping.is_set() or reply['id'] in self.jobs:
            return False
        callback = reply['method'] == 'answerCallbackQuery'
        if not callback and any(job['method'] == 'sendMessage' and job['user_id'] == reply['user_id'] for _, job in self.jobs.values()):
            return False
        candidates = [2] if callback else [0, 1]
        used = {slot for slot, _ in self.jobs.values()}
        return any(index not in used for index in candidates)

    def submit(self, reply):
        if not self.available(reply):
            return False
        candidates = [2] if reply['method'] == 'answerCallbackQuery' else [0, 1]
        used = {slot for slot, _ in self.jobs.values()}
        for index in candidates:
            if index not in used:
                job = copy.deepcopy(reply)
                self.jobs[job['id']] = (index, job)
                self.slots[index].put_nowait(job)
                return True
        return False

    def _run(self, slot):
        while not self.stopping.is_set():
            try:
                job = slot.get(timeout=.05)
            except queue.Empty:
                continue
            if self.stopping.is_set():
                return
            started = time.monotonic()
            result, error = None, None
            try:
                if job['method'] == 'sendMessage':
                    result = self.transport.send_message(**job['payload'])
                else:
                    result = self.transport.answer_callback_query(**job['payload'])
                if not isinstance(result, dict) or not result.get('ok'):
                    raise RuntimeError('Telegram rejected response')
            except Exception as exc:
                # Preserve only the class; exceptions may contain URLs/tokens.
                error = type(exc).__name__
            created = job.get('created_at')
            wait_ms = max(0, round((time.time() - created) * 1000 - (time.monotonic() - started) * 1000)) if created is not None else -1
            logger.info('event=telegram.outbound.completed method=%s elapsed_ms=%d queue_wait_ms=%d outcome=%s error_class=%s',
                        job['method'], round((time.monotonic() - started) * 1000), wait_ms,
                        'error' if error else 'success', error or 'none')
            if not self.stopping.is_set():
                self.results.put_nowait((job['id'], result, error))

    def completed(self):
        while True:
            try:
                row_id, result, error = self.results.get_nowait()
            except queue.Empty:
                return
            if row_id in self.jobs:
                yield self.jobs[row_id][1], result, error

    def acknowledge(self, row_id):
        self.jobs.pop(row_id, None)

    def close(self):
        self.stopping.set()
        deadline = time.monotonic() + .2
        for thread in self.threads:
            thread.join(max(0, deadline - time.monotonic()))
