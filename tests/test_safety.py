"""Offline safety regressions, using synthetic data only."""
import sys
import unittest
from typing import Any, cast
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.bot import FinanceBot
from finance_agent.db import Database
from finance_agent.service import FinanceService
from finance_agent.parser import parse_amount, parse_message, detected_currency_mismatch


class Transport:
    def __init__(self):
        self.sent = []
    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))
    def answer_callback_query(self, *args, **kwargs):
        pass


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.db.ensure_user(1, currency='IDR')
        self.bot: Any = FinanceBot.__new__(FinanceBot)
        self.bot._db = self.db
        self.bot._service = FinanceService(self.db)
        self.bot._tg = Transport()
        self.bot._agent = None
    def tearDown(self):
        self.db.close()
    def test_database_rejects_noninteger_and_out_of_range_money(self):
        for amount in (1.75, True, 9_223_372_036_854_775_808):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.db.add_transaction(user_id=1, kind='expense', amount=cast(Any, amount), currency='IDR', category='food')

    def test_legacy_delete_button_is_rejected(self):
        result = self.bot._service.record_from_text(1, 'kopi 20rb')
        assert result is not None
        self.bot.handle_update({'callback_query': {'id': 'old', 'from': {'id': 1}, 'data': f'del:{result.transaction.seq}', 'message': {'message_id': 2, 'chat': {'id': 1, 'type': 'private'}}}})
        self.assertEqual(len(self.db.recent_transactions(1)), 1)

    def test_suffix_does_not_consume_next_word(self):
        result = parse_message('20000 makan', 'IDR')
        assert result is not None
        self.assertEqual(result.amount, 20000)
        self.assertEqual(result.note, 'makan')
        self.assertIsNone(parse_message('kopi 20rubbish', 'IDR'))

    def test_currency_words_do_not_match_substrings(self):
        self.assertIsNone(detected_currency_mismatch('beli audio 20rb', 'IDR'))
        self.assertIsNotNone(parse_message('beli audio 20rb', 'IDR'))

    def test_ambiguous_amounts_are_rejected(self):
        for text, currency in (('-20rb', 'IDR'), ('20rb 30rb', 'IDR'), ('20rb', 'USD'), ('1.5', 'IDR'), ('999999999999999999999999999', 'IDR')):
            with self.subTest(text=text, currency=currency):
                self.assertIsNone(parse_amount(text, currency))
                self.assertIsNone(parse_message('kopi ' + text, currency))

    def test_edit_uses_original_transaction_currency(self):
        result = self.bot._service.record_from_text(1, 'kopi 20rb')
        assert result is not None
        tx = result.transaction
        self.db.set_currency(1, 'USD')
        edited = self.bot._service.edit_amount(1, tx.seq, '5000')
        assert edited is not None
        self.assertEqual(edited.currency, 'IDR')
        self.assertEqual(edited.amount, 5000)

    def test_numeric_question_does_not_create_transaction(self):
        self.bot._answer_question = lambda *args: None
        self.bot.handle_update({'message': {'chat': {'id': 1, 'type': 'private'}, 'from': {'id': 1}, 'text': 'berapa pengeluaran 20000?'}})
        self.assertEqual(self.db.recent_transactions(1), [])

    def test_nonprivate_updates_do_not_access_finance(self):
        for chat_type in ('group', 'supergroup', 'channel'):
            with self.subTest(chat_type=chat_type):
                self.bot.handle_update({'message': {'chat': {'id': -9, 'type': chat_type}, 'from': {'id': 1}, 'text': 'kopi 20rb'}})
                self.bot.handle_update({'callback_query': {'id': 'x', 'from': {'id': 1}, 'data': 'cur:USD', 'message': {'chat': {'id': -9, 'type': chat_type}}}})
                self.assertEqual(self.db.recent_transactions(1), [])
                self.assertEqual(self.db.get_currency(1), 'IDR')
                self.assertEqual(self.bot._tg.sent, [])


if __name__ == '__main__':
    unittest.main()
