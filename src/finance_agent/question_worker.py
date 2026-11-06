"""One model call at a time with a bounded submission queue and no Telegram I/O."""
from concurrent.futures import ThreadPoolExecutor


class QuestionWorker:
    def __init__(self, capacity=8):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='finance-model')
        self.jobs = {}
        self.capacity = capacity

    def submit(self, update_id, function):
        if update_id in self.jobs or len(self.jobs) >= self.capacity:
            return False
        self.jobs[update_id] = self.pool.submit(function)
        return True

    def completed(self):
        for update_id, future in list(self.jobs.items()):
            if future.done():
                del self.jobs[update_id]
                yield update_id, future

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
