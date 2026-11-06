"""AI-first recording contracts, synthetic data and fake models only."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.interpretation import validate_proposal


class InterpretationTests(unittest.TestCase):
    def proposal(self, **overrides):
        return dict(kind='expense', amount=5000, currency='IDR', category='food', note='pentol', **overrides)

    def test_pentol_category_comes_from_ai(self):
        p = validate_proposal(self.proposal(), 'pentol 5k', 'IDR')
        self.assertEqual(p['category'], 'food')
        self.assertEqual(p['amount'], 5000)

    def test_invalid_or_invented_amount_cannot_write(self):
        for amount in [True, 5.0, -5, 9000]:
            p = self.proposal(); p['amount'] = amount
            with self.assertRaises(ValueError):
                validate_proposal(p, 'pentol 5k', 'IDR')

    def test_ambiguous_or_foreign_currency_rejected(self):
        for text in ['pentol 5k atau 10k', 'pentol $5', 'berapa pentol', 'pentol -5k']:
            with self.assertRaises(ValueError):
                validate_proposal(self.proposal(), text, 'IDR')

    def test_expense_cannot_be_reversed_into_income(self):
        proposal = self.proposal()
        proposal.update(kind='income', category='income')
        with self.assertRaises(ValueError):
            validate_proposal(proposal, 'beli pentol 5k', 'IDR')

    def test_invalid_category_and_identity_fields_rejected(self):
        for p in [{**self.proposal(), 'category': 'invented'}, {**self.proposal(), 'user_id': 2}]:
            with self.assertRaises(ValueError):
                validate_proposal(p, 'pentol 5k', 'IDR')


if __name__ == '__main__':
    unittest.main()
