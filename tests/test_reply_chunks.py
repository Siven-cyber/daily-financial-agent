"""Long plain-text replies are split before durable outbox persistence."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.processing import ReplyCollector


class ReplyChunkTests(unittest.TestCase):
    def test_long_reply_preserves_all_text_and_bounds_utf16_units(self):
        text = ('Expense 💰 Rp20.000\n' * 600) + 'end'
        collector = ReplyCollector()
        collector.send_message(7, text)
        parts = [payload['text'] for _, payload in collector.calls]
        self.assertGreater(len(parts), 1)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(0 < len(p.encode('utf-16-le')) // 2 <= 4000 for p in parts))
        self.assertTrue(all(payload['chat_id'] == 7 for _, payload in collector.calls))

    def test_markup_attached_only_to_final_chunk(self):
        markup = {'inline_keyboard': [[{'text': 'Confirm', 'callback_data': 'test'}]]}
        collector = ReplyCollector()
        collector.send_message(7, 'x' * 9000, reply_markup=markup)
        self.assertEqual(len(collector.calls), 3)
        self.assertTrue(all('reply_markup' not in p for _, p in collector.calls[:-1]))
        self.assertEqual(collector.calls[-1][1]['reply_markup'], markup)


if __name__ == '__main__':
    unittest.main()
