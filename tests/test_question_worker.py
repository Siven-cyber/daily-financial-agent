"""Bounded worker acceptance with synthetic blocking work only."""
import sys
import threading
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.question_worker import QuestionWorker


class WorkerTests(unittest.TestCase):
    def test_capacity_and_duplicate_admission(self):
        worker = QuestionWorker(capacity=2)
        release = threading.Event()
        self.addCleanup(worker.close)
        self.addCleanup(release.set)
        self.assertTrue(worker.submit(1, lambda: release.wait(2)))
        self.assertFalse(worker.submit(1, lambda: None))
        self.assertTrue(worker.submit(2, lambda: 'second'))
        self.assertFalse(worker.submit(3, lambda: 'third'))
        release.set()
        for future in worker.jobs.values():
            future.result(timeout=2)
        completed = list(worker.completed())
        self.assertEqual([uid for uid, _ in completed], [1, 2])
        self.assertEqual(worker.jobs, {})
        self.assertTrue(worker.submit(3, lambda: 'third'))


if __name__ == '__main__':
    unittest.main()
