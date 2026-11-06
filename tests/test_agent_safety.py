"""Agent contract tests without provider calls."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from finance_agent.agent import FinanceAgent


class AgentTests(unittest.TestCase):
    def test_cancel_active_turn_is_explicit(self):
        called = []
        agent = FinanceAgent.__new__(FinanceAgent)
        agent._active_handle = SimpleNamespace(cancel=lambda: called.append('cancel'))
        agent.cancel_active()
        self.assertEqual(called, ['cancel'])

    def test_answer_has_explicit_empty_tools(self):
        payloads = []
        class Handle:
            def result(self, **kwargs):
                return SimpleNamespace(final_text='answer')
        class Runtime:
            def submit_turn(self, *, payload):
                payloads.append(payload)
                return Handle()
        agent = FinanceAgent.__new__(FinanceAgent)
        agent._runtime = Runtime()
        agent._agent_id = None
        self.assertEqual(agent.answer('question', context='IDR 100', session_id='synthetic'), 'answer')
        self.assertEqual(payloads[0].get('allowed_tools'), [])

    def test_failed_or_timed_out_answer_cancels_handle(self):
        class Handle:
            cancelled = False
            def result(self, **kwargs):
                raise TimeoutError('deadline')
            def cancel(self):
                self.cancelled = True
        handle = Handle()
        class Runtime:
            def submit_turn(self, **kwargs):
                return handle
        agent = FinanceAgent.__new__(FinanceAgent)
        agent._runtime = Runtime()
        agent._agent_id = None
        with self.assertRaises(TimeoutError):
            agent.answer('question', context='', session_id='synthetic')
        self.assertTrue(handle.cancelled)


if __name__ == '__main__':
    unittest.main()
