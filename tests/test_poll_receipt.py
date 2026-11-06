"""Polling never acknowledges an unpersisted batch."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.telegram_client import TelegramClient


class PollTests(unittest.TestCase):
    def test_explicit_offset_does_not_advance_implicitly(self):
        client = TelegramClient('synthetic')
        calls = []
        def call(method, params):
            calls.append(params)
            return {'ok': True, 'result': [{'update_id': 4}]}
        client._call = call
        self.assertEqual(client.fetch_updates(offset=4), [{'update_id': 4}])
        self.assertEqual(client.fetch_updates(offset=4), [{'update_id': 4}])
        self.assertEqual([c['offset'] for c in calls], [4, 4])


if __name__ == '__main__':
    unittest.main()
